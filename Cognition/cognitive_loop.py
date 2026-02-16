"""Vision PAL - Cognitive Loop
知覚→感情→記憶→プロンプト→出力のメインループ。
MQTT経由でJetsonの知覚データを受信し、SDプロンプト+独白をpublish。
"""
import json
import os
import subprocess
import sys
import time
import threading

# MQTT (optional, graceful fallback)
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[CogLoop] paho-mqtt not found, running in standalone mode")

from perception import Perception
from affect import Affect
from memory_recall import MemoryRecall
from prompt_builder import PromptBuilder
import config as cfg


class CognitiveLoop:
    """パルの認知ループ — 1-2秒サイクルで世界を理解する"""

    def __init__(self):
        # モジュール初期化
        self.perception = Perception()
        self.affect = Affect()
        self.memory = MemoryRecall()
        self.prompt_builder = PromptBuilder()

        # MQTT
        self.mqtt_client = None
        self.mqtt_connected = False

        # 状態
        self.running = False
        self.cycle_count = 0
        self.last_monologue = ""
        self.last_monologue_time = 0
        self.monologue_cooldown = 30  # 独白の最小間隔（秒）
        self.last_emotion = ""
        self.tts_lock = threading.Lock()

        # TTS設定
        self.tts_enabled = True
        self.tts_method = os.environ.get("PAL_TTS_METHOD", "openclaw")
        # "openclaw" = OpenClaw TTS API (ElevenLabs)
        # "local" = pal_speak.sh on Jetson host

        # Jetson SSH設定（pal_speak.sh用）
        self.jetson_host = os.environ.get("JETSON_HOST", "192.168.3.5")
        self.jetson_user = os.environ.get("JETSON_USER", "haltyt")

    def setup_mqtt(self):
        """MQTT接続セットアップ"""
        if not HAS_MQTT:
            print("[CogLoop] MQTT disabled (no paho-mqtt)")
            return

        broker = self.config.MQTT_BROKER
        port = self.config.MQTT_PORT

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "cognition_engine")
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect

        try:
            self.mqtt_client.connect(broker, port, 60)
            self.mqtt_client.loop_start()
            print("[CogLoop] MQTT connecting to {}:{}".format(broker, port))
        except Exception as e:
            print("[CogLoop] MQTT connection failed: {}".format(e))

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0 or str(reason_code) == "Success":
            self.mqtt_connected = True
            print("[CogLoop] MQTT connected!")
        else:
            print("[CogLoop] MQTT connect failed, rc={}".format(reason_code))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.mqtt_connected = False
        print("[CogLoop] MQTT disconnected, rc={}".format(reason_code))

    def publish(self, topic, data):
        """MQTTでデータをpublish"""
        if self.mqtt_client and self.mqtt_connected:
            payload = json.dumps(data, ensure_ascii=False)
            self.mqtt_client.publish(topic, payload)
        else:
            # MQTT未接続時はログ出力のみ
            pass

    def speak(self, text):
        """パルの独白をTTSで喋る（非同期）"""
        if not self.tts_enabled or not text:
            return

        # クールダウンチェック
        now = time.time()
        if now - self.last_monologue_time < self.monologue_cooldown:
            return
        # 同じセリフは繰り返さない
        if text == self.last_monologue:
            return

        self.last_monologue = text
        self.last_monologue_time = now

        # 非同期でTTS実行
        t = threading.Thread(target=self._speak_impl, args=(text,), daemon=True)
        t.start()

    def _speak_impl(self, text):
        """TTS実行（スレッド内）"""
        with self.tts_lock:
            try:
                if self.tts_method == "local":
                    self._speak_local(text)
                else:
                    self._speak_openclaw(text)
            except Exception as e:
                print("[CogLoop] TTS error: {}".format(e))

    def _speak_openclaw(self, text):
        """OpenClaw TTS API → Jetsonスピーカー再生"""
        api_url = self.memory.api_url
        api_token = self.memory.api_token

        # OpenClaw TTS APIでmp3生成
        url = "{}/tools/invoke".format(api_url)
        body = json.dumps({
            "tool": "tts",
            "args": {"text": text},
            "sessionKey": "main",
        }).encode("utf-8")

        import urllib.request
        req = urllib.request.Request(url, body, {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(api_token),
        })

        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))

        if not data.get("ok"):
            print("[TTS] API error: {}".format(data))
            return

        # レスポンスからファイルパスを取得
        result = data.get("result", {})
        content = result.get("content", [])
        if not content:
            return

        result_text = content[0].get("text", "")
        # "MEDIA: /path/to/file.mp3" 形式を期待
        if "MEDIA:" in result_text:
            media_path = result_text.split("MEDIA:")[1].strip()
            self._play_on_jetson(media_path)
        else:
            print("[TTS] No MEDIA path in response")

    def _speak_local(self, text):
        """Jetsonのpal_speak.shで直接再生"""
        try:
            subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no",
                 "{}@{}".format(self.jetson_user, self.jetson_host),
                 "bash ~/pal_speak.sh '{}'".format(text.replace("'", "'\\''"))],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            print("[TTS] Local speak failed: {}".format(e))

    def _play_on_jetson(self, media_path):
        """生成された音声ファイルをJetsonスピーカーで再生"""
        try:
            # コンテナ内のファイルをJetsonにscpして再生
            remote_path = "/tmp/pal_cognitive_tts.mp3"
            subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no",
                 media_path,
                 "{}@{}:{}".format(self.jetson_user, self.jetson_host, remote_path)],
                timeout=15,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Jetsonで再生
            subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no",
                 "{}@{}".format(self.jetson_user, self.jetson_host),
                 "bash ~/pal_speak.sh --file '{}'".format(remote_path)],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            print("[TTS] Play on Jetson failed: {}".format(e))

    def run_cycle(self):
        """1サイクル実行: 知覚→感情→記憶→プロンプト→出力"""
        t0 = time.time()

        # 1. 知覚: カメラから物体検出
        perception_data = self.perception.get_perception_data()

        # 2. 感情: 知覚データから感情を計算
        motor_state = {"moving": False, "direction": "stop"}  # TODO: MQTT経由で取得
        collision = False  # TODO: collision_detect連携
        affect_data = self.affect.update(perception_data, motor_state, collision)

        # 3. 記憶: セマンティック検索
        memory_data = self.memory.recall(perception_data, affect_data)

        # 4. プロンプト生成
        prompt_data = self.prompt_builder.build(
            perception_data, affect_data, memory_data
        )

        # 5. 出力
        # MQTT publish
        self.publish("vision_pal/prompt/current", {
            "sd_prompt": prompt_data["sd_prompt"],
            "negative_prompt": prompt_data["negative_prompt"],
            "emotion": prompt_data["emotion"],
            "arousal": prompt_data["arousal"],
            "memory_strength": prompt_data["memory_strength"],
            "timestamp": prompt_data["timestamp"],
        })

        self.publish("vision_pal/affect/state", {
            "emotion": affect_data.get("emotion"),
            "valence": affect_data.get("valence"),
            "arousal": affect_data.get("arousal"),
            "emotions": affect_data.get("emotions", {}),
        })

        self.publish("vision_pal/perception/objects", {
            "scene": perception_data.get("scene"),
            "objects": perception_data.get("objects", []),
            "has_person": perception_data.get("has_person"),
        })

        # 6. 独白（感情が変わった時 or 一定間隔）
        monologue = prompt_data.get("monologue", "")
        emotion_changed = affect_data.get("emotion") != self.last_emotion
        self.last_emotion = affect_data.get("emotion", "")

        if monologue and (emotion_changed or
                          time.time() - self.last_monologue_time > 60):
            self.speak(monologue)
            # MQTTにも独白をpublish
            self.publish("vision_pal/monologue", {
                "text": monologue,
                "emotion": affect_data.get("emotion"),
                "timestamp": time.time(),
            })

        elapsed = time.time() - t0
        self.cycle_count += 1

        # ログ（最初5回 + 以後10回ごと）
        if self.cycle_count <= 5 or self.cycle_count % 10 == 0:
            print("[Cycle {:>4d}] {:.1f}s | {} | mem:{:.2f} | {}".format(
                self.cycle_count,
                elapsed,
                affect_data.get("emotion", "?"),
                memory_data.get("memory_strength", 0),
                monologue[:40] if monologue else "-",
            ))

        return {
            "perception": perception_data,
            "affect": affect_data,
            "memory": memory_data,
            "prompt": prompt_data,
            "elapsed": elapsed,
        }

    def run(self, interval=2.0):
        """メインループ開始"""
        print("[CogLoop] Starting cognitive loop (interval={:.1f}s)".format(interval))
        print("[CogLoop] TTS: {} | MQTT: {}".format(
            self.tts_method, "enabled" if HAS_MQTT else "disabled"))

        self.setup_mqtt()
        self.running = True

        try:
            while self.running:
                try:
                    self.run_cycle()
                except Exception as e:
                    print("[CogLoop] Cycle error: {}".format(e))
                    import traceback
                    traceback.print_exc()

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[CogLoop] Stopped by user")
        finally:
            self.running = False
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            print("[CogLoop] Shutdown complete. {} cycles run.".format(
                self.cycle_count))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PAL Cognitive Loop")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Cycle interval in seconds (default: 2.0)")
    parser.add_argument("--no-tts", action="store_true",
                        help="Disable TTS output")
    parser.add_argument("--tts-method", choices=["openclaw", "local"],
                        default="openclaw", help="TTS method")
    parser.add_argument("--once", action="store_true",
                        help="Run single cycle and exit")
    parser.add_argument("--monologue-cooldown", type=int, default=30,
                        help="Minimum seconds between monologues")
    args = parser.parse_args()

    loop = CognitiveLoop()
    loop.tts_enabled = not args.no_tts
    loop.tts_method = args.tts_method
    loop.monologue_cooldown = args.monologue_cooldown

    if args.once:
        result = loop.run_cycle()
        print("\n" + "=" * 60)
        print("[SD Prompt]")
        print(result["prompt"]["sd_prompt"])
        print("\n[独白]", result["prompt"]["monologue"])
        print("[感情]", result["affect"]["emotion"])
    else:
        loop.run(interval=args.interval)
