#!/usr/bin/env python3
"""Vision PAL - VLM Watcher
MJPEGスナップショットをGemini Flash Liteに送り、シーン認識結果をMQTT publishする。
独立プロセスとして動作。cognitive_loop.pyとはMQTTで疎結合。

Usage:
    python vlm_watcher.py                          # デフォルト5秒間隔
    python vlm_watcher.py --interval 10            # 10秒間隔
    python vlm_watcher.py --once                   # 1回だけ実行して終了
    python vlm_watcher.py --snap-url http://...    # MJPEG snap URL指定
"""

import argparse
import base64
import json
import os
import signal
import sys
import time
import urllib.request
import urllib.error

# MQTT (optional)
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[VLM] paho-mqtt not found, MQTT disabled (stdout only)")

# ─── Config ───────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.3.5")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_SCENE = "vision_pal/perception/scene"

SNAP_URL = os.environ.get("MJPEG_SNAP_URL", "http://192.168.3.8:8554/snap")

PROMPT_JSON = (
    "ロボットの目として画像を分析。全て日本語で返して。JSON形式。"
    '{"obstacles":["自然な日本語の説明"],"people":数,"summary":"日本語1文","changes":"前回との変化(あれば)"}'
    " 例: obstacles=[\"中央に椅子\",\"左に自転車\",\"右手に観葉植物\",\"男性の手にスマートフォン\"]"
    " 括弧()は使わず、自然な日本語の短いフレーズで書くこと。"
)

PROMPT_TEXT = (
    "ロボットの目として画像を見て。日本語で1-2文で何が見えるか教えて。"
    "障害物と人の有無も含めて。前回との変化があれば教えて。短く。"
)


def build_prompt(output_json, prev_summary=""):
    """前回コンテキスト付きプロンプトを生成"""
    base = PROMPT_JSON if output_json else PROMPT_TEXT
    if prev_summary:
        context = "前回の観察:「{}」。今回の画像と比較して。".format(prev_summary[:100])
        return context + base
    return base

# ─── Helpers ──────────────────────────────────────────────

def get_api_key():
    """GEMINI_API_KEY を環境変数 or OpenClaw configから取得"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    # OpenClaw config fallback
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            import json as _json
            with open(config_path) as f:
                cfg = _json.load(f)
            key = cfg.get("skills", {}).get("entries", {}).get(
                "nano-banana-pro", {}).get("env", {}).get("GEMINI_API_KEY", "")
            if key:
                print("[VLM] API key loaded from openclaw.json")
                return key
        except Exception as e:
            print("[VLM] Config read failed: {}".format(e))
    print("[VLM] ERROR: GEMINI_API_KEY not set", file=sys.stderr)
    sys.exit(1)


def snap_image(url, timeout=5):
    """MJPEGサーバーからスナップショットを取得 → bytes"""
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = resp.read()
        if len(data) < 1000:
            print("[VLM] WARNING: snap too small ({}B), might be error".format(len(data)))
            return None
        return data
    except Exception as e:
        print("[VLM] Snap failed ({}): {}".format(url, e))
        return None


def gemini_analyze(image_bytes, api_key, output_json=True, prev_summary=""):
    """Gemini Flash Lite で画像解析 → dict or str"""
    url = GEMINI_URL.format(model=GEMINI_MODEL, key=api_key)
    b64 = base64.b64encode(image_bytes).decode("ascii")

    prompt = build_prompt(output_json, prev_summary)

    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                {"text": prompt},
            ]
        }],
    }
    if output_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, payload, {
        "Content-Type": "application/json",
    })

    try:
        t0 = time.time()
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read().decode("utf-8")
        elapsed = time.time() - t0

        # Geminiが複数JSONオブジェクトを返すことがある → 最初の行だけ使う
        first_line = raw.split("\n")[0].strip()
        try:
            data = json.loads(first_line)
        except json.JSONDecodeError:
            data = json.loads(raw)
        if "candidates" not in data:
            err = data.get("error", {}).get("message", "unknown")
            print("[VLM] API error: {}".format(err))
            return None, elapsed

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        if output_json:
            # JSON parse（Geminiが余計なテキストを返すことがある）
            try:
                result = json.loads(text)
                return result, elapsed
            except json.JSONDecodeError:
                # JSONっぽい部分を抽出
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    result = json.loads(text[start:end])
                    return result, elapsed
                print("[VLM] JSON parse failed: {}".format(text[:200]))
                return {"raw": text, "summary": text[:100]}, elapsed
        else:
            return {"summary": text.strip()}, elapsed

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print("[VLM] HTTP {}: {}".format(e.code, body))
        return None, 0
    except Exception as e:
        print("[VLM] Request failed: {}".format(e))
        return None, 0


# ─── MQTT ─────────────────────────────────────────────────

class MQTTPublisher:
    def __init__(self, broker, port):
        if not HAS_MQTT:
            self.client = None
            return
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "vlm_watcher")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("vlm_watcher")
        self.connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        try:
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            print("[VLM] MQTT connecting to {}:{}...".format(broker, port))
        except Exception as e:
            print("[VLM] MQTT connect failed: {}".format(e))
            self.client = None

    def _on_connect(self, *args):
        self.connected = True
        print("[VLM] MQTT connected!")

    def _on_disconnect(self, *args):
        self.connected = False
        print("[VLM] MQTT disconnected")

    def publish(self, topic, data):
        if self.client and self.connected:
            payload = json.dumps(data, ensure_ascii=False)
            self.client.publish(topic, payload)
            return True
        return False

    def stop(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# ─── Main Loop ────────────────────────────────────────────

def run(args):
    api_key = get_api_key()
    snap_url = args.snap_url
    interval = args.interval
    output_json = not args.text_mode

    print("[VLM] === Vision PAL VLM Watcher ===")
    print("[VLM] Model: {}".format(GEMINI_MODEL))
    print("[VLM] Snap:  {}".format(snap_url))
    print("[VLM] MQTT:  {}:{} -> {}".format(MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_SCENE))
    print("[VLM] Interval: {}s | JSON: {}".format(interval, output_json))

    # MQTT
    mqtt_pub = MQTTPublisher(MQTT_BROKER, MQTT_PORT) if not args.no_mqtt else None

    # Graceful shutdown
    running = [True]
    def _signal(sig, frame):
        print("\n[VLM] Shutting down...")
        running[0] = False
    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    cycle = 0
    errors = 0
    max_consecutive_errors = 10
    prev_summary = ""  # 前回の観察結果

    while running[0]:
        cycle += 1

        # 1. スナップショット取得
        img = snap_image(snap_url, timeout=args.snap_timeout)
        if img is None:
            errors += 1
            if errors >= max_consecutive_errors:
                print("[VLM] {} consecutive errors, backing off 30s".format(errors))
                time.sleep(30)
                errors = 0
            else:
                time.sleep(interval)
            continue

        # 2. Gemini解析（前回コンテキスト付き）
        result, elapsed = gemini_analyze(img, api_key, output_json, prev_summary)
        if result is None:
            errors += 1
            time.sleep(interval)
            continue

        errors = 0  # リセット

        # 前回サマリー更新
        new_summary = result.get("summary", "")
        if new_summary:
            prev_summary = new_summary

        # 3. MQTT publish
        scene_data = {
            "timestamp": time.time(),
            "model": GEMINI_MODEL,
            "latency_ms": int(elapsed * 1000),
            "cycle": cycle,
        }
        scene_data.update(result)
        scene_data["prev_summary"] = prev_summary

        published = False
        if mqtt_pub:
            published = mqtt_pub.publish(MQTT_TOPIC_SCENE, scene_data)

        # ログ
        summary = result.get("summary", str(result)[:60])
        people = result.get("people", "?")
        obstacles = result.get("obstacles", [])
        mqtt_tag = "MQTT" if published else "LOCAL"
        print("[VLM #{:>4d}] {:.1f}s | people:{} | obstacles:{} | {} | {}".format(
            cycle, elapsed, people, len(obstacles), mqtt_tag, summary[:50],
        ))

        if args.once:
            print("\n" + json.dumps(scene_data, indent=2, ensure_ascii=False))
            break

        # 待機（APIレイテンシ分を差し引き）
        wait = max(0.1, interval - elapsed)
        time.sleep(wait)

    # Cleanup
    if mqtt_pub:
        mqtt_pub.stop()
    print("[VLM] Done. {} cycles.".format(cycle))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vision PAL VLM Watcher")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Seconds between scans (default: 5)")
    parser.add_argument("--snap-url", default=SNAP_URL,
                        help="MJPEG snapshot URL")
    parser.add_argument("--snap-timeout", type=float, default=5.0,
                        help="Snapshot HTTP timeout (seconds)")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit")
    parser.add_argument("--text-mode", action="store_true",
                        help="Get text summary instead of JSON")
    parser.add_argument("--no-mqtt", action="store_true",
                        help="Disable MQTT, stdout only")
    args = parser.parse_args()
    run(args)
