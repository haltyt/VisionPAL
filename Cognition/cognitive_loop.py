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
from effect_generator import EffectGenerator
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

        # VLMシーンデータ（vlm_watcher.pyから受信）
        self.scene_data = {}
        self._scene_lock = threading.Lock()

        # 状態
        self.running = False
        self.cycle_count = 0
        self.last_monologue = ""
        self.last_monologue_time = 0
        self.monologue_cooldown = 30  # 独白の最小間隔（秒）
        self.monologue_history = []  # 直近の独白履歴（重複防止）
        self.last_emotion = ""
        self.tts_lock = threading.Lock()

        # エフェクト生成
        self.effect_gen = EffectGenerator(use_llm=True)
        self.last_effect_emotion = ""

        # Discord通知
        self.discord_enabled = True
        self.discord_target = "user:390759448148443136"  # haltyt

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

        broker = cfg.MQTT_BROKER
        port = cfg.MQTT_PORT

        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "cognition_engine")
        except (AttributeError, TypeError):
            self.mqtt_client = mqtt.Client("cognition_engine")
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect

        try:
            self.mqtt_client.connect(broker, port, 60)
            self.mqtt_client.loop_start()
            print("[CogLoop] MQTT connecting to {}:{}".format(broker, port))
        except Exception as e:
            print("[CogLoop] MQTT connection failed: {}".format(e))

    def _on_connect(self, *args):
        # paho v1: (client, userdata, flags, rc) / v2: (client, userdata, flags, rc, properties)
        client = args[0] if args else self.mqtt_client
        self.mqtt_connected = True
        print("[CogLoop] MQTT connected!")
        client.subscribe(self.perception.topic)
        client.subscribe(cfg.TOPIC_COLLISION)
        client.subscribe(cfg.TOPIC_SCENE)
        client.message_callback_add(self.perception.topic, self._on_perception)
        client.message_callback_add(cfg.TOPIC_COLLISION, self._on_collision)
        client.message_callback_add(cfg.TOPIC_SCENE, self._on_scene)
        print("[CogLoop] Subscribed: {}, {}, {}".format(
            self.perception.topic, cfg.TOPIC_COLLISION, cfg.TOPIC_SCENE))

    def _on_perception(self, client, userdata, msg):
        """知覚データ受信"""
        self.perception.on_mqtt_message(msg.payload)

    def _on_scene(self, client, userdata, msg):
        """VLMシーンデータ受信（vlm_watcher.pyから）"""
        try:
            data = json.loads(msg.payload)
            prev_people = self.scene_data.get("people", 0) if self.scene_data else 0
            with self._scene_lock:
                self.scene_data = data
            summary = data.get("summary", "")[:50]
            people = data.get("people", 0)
            latency = data.get("latency_ms", 0)
            print("[CogLoop] 👁️ Scene: people={} | {}".format(people, summary))
            # 人の出入りがあった時だけDiscord通知
            if people != prev_people:
                if people > prev_people:
                    self.notify_discord("👁️ **人を検出！** ({}名) | {} | VLM: {}ms".format(
                        people, summary, latency))
                else:
                    self.notify_discord("👁️ **人がいなくなった** | {} | VLM: {}ms".format(
                        summary, latency))
        except Exception as e:
            print("[CogLoop] Scene parse error: {}".format(e))

    def _on_collision(self, client, userdata, msg):
        """衝突データ受信"""
        try:
            data = json.loads(msg.payload)
            if data.get("collision"):
                self.affect.collision_event()
                print("[CogLoop] 💥 Collision received!")
        except Exception:
            pass

    def _on_disconnect(self, *args):
        self.mqtt_connected = False
        print("[CogLoop] MQTT disconnected")

    def publish(self, topic, data):
        """MQTTでデータをpublish"""
        if self.mqtt_client and self.mqtt_connected:
            payload = json.dumps(data, ensure_ascii=False)
            self.mqtt_client.publish(topic, payload)
        else:
            # MQTT未接続時はログ出力のみ
            pass

    def notify_discord(self, text):
        """Discordにデバッグ情報を送信"""
        if not self.discord_enabled:
            return
        try:
            import urllib.request as _urlreq
            url = "{}/tools/invoke".format(self.memory.api_url)
            body = json.dumps({
                "tool": "message",
                "args": {
                    "action": "send",
                    "channel": "discord",
                    "target": self.discord_target,
                    "message": text,
                },
                "sessionKey": "main",
            }).encode("utf-8")
            req = _urlreq.Request(url, body, {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.memory.api_token),
            })
            _urlreq.urlopen(req, timeout=10)
        except Exception as e:
            print("[Discord] Send failed: {}".format(e))

    def speak(self, text):
        """パルの独白をTTSで喋る（非同期）"""
        if not self.tts_enabled or not text:
            print("[TTS] skip: enabled={} text={}".format(self.tts_enabled, bool(text)))
            return

        # クールダウンチェック
        now = time.time()
        elapsed = now - self.last_monologue_time
        if elapsed < self.monologue_cooldown:
            print("[TTS] cooldown ({:.0f}s < {:.0f}s)".format(elapsed, self.monologue_cooldown))
            return
        # 最近のセリフと似すぎたらスキップ（先頭20文字で比較）
        text_key = text[:20]
        for prev in self.monologue_history[-5:]:
            if prev[:20] == text_key:
                print("[TTS] similar to recent, skip")
                return

        self.last_monologue = text
        self.last_monologue_time = now
        self.monologue_history.append(text)
        if len(self.monologue_history) > 10:
            self.monologue_history.pop(0)

        print("[TTS] speaking: {}".format(text[:50]))
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
                print("[TTS] done OK", flush=True)
            except Exception as e:
                import traceback
                print("[TTS] error: {}".format(e), flush=True)
                traceback.print_exc()

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
                 "bash ~/PAL/scripts/pal_speak.sh '{}'".format(text.replace("'", "'\\''"))],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            print("[TTS] Local speak failed: {}".format(e))

    def _play_on_jetson(self, media_path):
        """生成された音声ファイルをスピーカーで再生（JetBot USBスピーカー優先、Jetson BTフォールバック）"""
        try:
            # JetBot USBスピーカーで再生を試みる
            jetbot_host = "192.168.3.8"
            jetbot_user = "jetbot"
            remote_path = "/tmp/pal_cognitive_tts.mp3"

            print("[TTS] scp {} -> jetbot".format(media_path), flush=True)
            r1 = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
                 media_path,
                 "{}@{}:{}".format(jetbot_user, jetbot_host, remote_path)],
                timeout=10,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if r1.returncode == 0:
                print("[TTS] playing on jetbot USB speaker...", flush=True)
                play_cmd = (
                    "amixer -c 3 set PCM 50% 2>/dev/null; "
                    "ffmpeg -y -i '{}' -ar 44100 -ac 1 /tmp/pal_tts.wav 2>/dev/null && "
                    "aplay -D plughw:3,0 /tmp/pal_tts.wav"
                ).format(remote_path)
                r2 = subprocess.run(
                    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
                     "{}@{}".format(jetbot_user, jetbot_host),
                     play_cmd],
                    timeout=30,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                print("[TTS] jetbot play rc={}".format(r2.returncode), flush=True)
                if r2.returncode == 0:
                    return  # 成功

            # フォールバック: Jetson BTスピーカー
            print("[TTS] jetbot failed, trying jetson BT...", flush=True)
            r1 = subprocess.run(
                ["scp", "-o", "StrictHostKeyChecking=no",
                 media_path,
                 "{}@{}:{}".format(self.jetson_user, self.jetson_host, remote_path)],
                timeout=15,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if r1.returncode != 0:
                print("[TTS] scp to jetson failed", flush=True)
                return
            play_cmd = (
                "pactl set-default-sink bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink 2>/dev/null || "
                "(echo -e 'connect AC:9B:0A:AA:B8:F6\\nquit' | sudo bluetoothctl > /dev/null 2>&1 && sleep 3 && "
                "pactl set-default-sink bluez_sink.AC_9B_0A_AA:B8:F6.a2dp_sink 2>/dev/null); "
                "ffmpeg -y -i '{}' -f wav - 2>/dev/null | paplay --device=bluez_sink.AC_9B_0A_AA_B8_F6.a2dp_sink"
            ).format(remote_path)
            r2 = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no",
                 "{}@{}".format(self.jetson_user, self.jetson_host),
                 play_cmd],
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("[TTS] jetson play rc={}".format(r2.returncode), flush=True)
        except Exception as e:
            print("[TTS] Play failed: {}".format(e), flush=True)

    def run_cycle(self):
        """1サイクル実行: 知覚→感情→記憶→プロンプト→出力"""
        t0 = time.time()

        # 1. 知覚: カメラから物体検出 + VLMシーン
        perception_data = self.perception.get_perception_data()
        with self._scene_lock:
            if self.scene_data:
                perception_data["vlm_scene"] = self.scene_data.get("summary", "")
                perception_data["vlm_obstacles"] = self.scene_data.get("obstacles", [])
                perception_data["vlm_people"] = self.scene_data.get("people", 0)
                # VLMで人を検出したらhas_personを更新
                if self.scene_data.get("people", 0) > 0:
                    perception_data["has_person"] = True
                # sceneがあればobject_countを更新
                vlm_obs = self.scene_data.get("obstacles", [])
                if vlm_obs:
                    perception_data["object_count"] = max(
                        perception_data.get("object_count", 0), len(vlm_obs)
                    )

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
        current_emotion = affect_data.get("emotion", "")
        emotion_changed = current_emotion != self.last_emotion
        if emotion_changed:
            print("[Mono] emotion changed: {} -> {}".format(self.last_emotion, current_emotion))
        self.last_emotion = current_emotion

        # 6.5. エフェクト生成（感情変化時）
        if emotion_changed and current_emotion != self.last_effect_emotion:
            self.last_effect_emotion = current_emotion
            vlm_scene_for_effect = perception_data.get("vlm_scene", "")
            vlm_people_for_effect = perception_data.get("vlm_people", 0)
            # 非同期でエフェクト生成（メインループをブロックしない）
            def _gen_effect():
                try:
                    effect = self.effect_gen.generate(
                        current_emotion,
                        affect_data.get("valence", 0.5),
                        affect_data.get("arousal", 0.3),
                        vlm_scene_for_effect,
                        vlm_people_for_effect,
                    )
                    if effect:
                        self.publish(cfg.TOPIC_EFFECT, {
                            "effect": effect,
                            "emotion": current_emotion,
                            "timestamp": time.time(),
                        })
                        ptype = effect.get("particles", {}).get("type", "?")
                        pptype = effect.get("postProcess", {}).get("type", "?")
                        self.notify_discord(
                            "✨ **Effect** | {} → 🎆{} + 🌈{}".format(
                                current_emotion, ptype, pptype))
                except Exception as e:
                    print("[Effect] Error: {}".format(e))
            threading.Thread(target=_gen_effect, daemon=True).start()

        time_since = time.time() - self.last_monologue_time
        # VLMシーンに変化があるかチェック
        vlm_changed = False
        with self._scene_lock:
            new_changes = self.scene_data.get("changes", "")
            if new_changes and "変化なし" not in new_changes and "ありません" not in new_changes:
                vlm_changed = True
        should_speak = monologue and (emotion_changed or vlm_changed)

        # Discord通知用の共通データ
        vlm_scene = perception_data.get("vlm_scene", "")
        vlm_obs = perception_data.get("vlm_obstacles", [])
        vlm_ppl = perception_data.get("vlm_people", 0)
        mem_str = memory_data.get("memory_strength", 0)

        if should_speak:
            print("[Mono] trigger: emotion_changed={} time_since={:.0f}s".format(emotion_changed, time_since))
            self.speak(monologue)
            self.last_monologue_time = time.time()
            # MQTTにも独白をpublish
            self.publish("vision_pal/monologue", {
                "text": monologue,
                "emotion": affect_data.get("emotion"),
                "timestamp": time.time(),
            })
            # Discord通知
            debug_msg = (
                "🤖 **Cognition #{cycle}**\n"
                "👁️ VLM: {scene}\n"
                "🚧 障害物: {obs}\n"
                "👤 人: {ppl}\n"
                "💭 感情: **{emo}** (v:{val:.2f} a:{aro:.2f})\n"
                "📚 記憶強度: {mem:.3f}\n"
                "💬 独白: {mono}\n"
                "🔊 TTS: 再生中..."
            ).format(
                cycle=self.cycle_count,
                scene=vlm_scene[:60] if vlm_scene else "なし",
                obs=", ".join(vlm_obs[:4]) if vlm_obs else "なし",
                ppl=vlm_ppl,
                emo=current_emotion,
                val=affect_data.get("valence", 0),
                aro=affect_data.get("arousal", 0),
                mem=mem_str,
                mono=monologue[:80],
            )
            self.notify_discord(debug_msg)
        else:
            # スキップ理由を判定
            reasons = []
            if not monologue:
                reasons.append("独白なし")
            if not emotion_changed:
                reasons.append("感情変化なし")
            if not vlm_changed:
                reasons.append("シーン変化なし")
            skip_reason = ", ".join(reasons)

            # スキップもDiscord通知（10サイクルごと or 最初5回）
            if self.cycle_count <= 5 or self.cycle_count % 10 == 0:
                debug_msg = (
                    "⏭️ **Skip #{cycle}**\n"
                    "👁️ VLM: {scene}\n"
                    "👤 人: {ppl} | 💭 感情: **{emo}**\n"
                    "⏩ スキップ理由: {reason}"
                ).format(
                    cycle=self.cycle_count,
                    scene=vlm_scene[:60] if vlm_scene else "なし",
                    ppl=vlm_ppl,
                    emo=current_emotion,
                    reason=skip_reason,
                )
                self.notify_discord(debug_msg)

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
