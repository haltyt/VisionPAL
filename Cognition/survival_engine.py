#!/usr/bin/env python3
"""Vision PAL - Survival Engine
言語以前の「生存層」。身体信号から欲求・衝動を算出し、
自律行動を決定する。cognitive_loopの感情に直接影響を与える。

ホメオスタシス（恒常性）モデル:
  各「欲求」は 0.0〜1.0 のレベルを持つ。
  - 0.0 = 満たされている
  - 1.0 = 緊急

欲求:
  - energy:    エネルギー（バッテリー/電圧）
  - thermal:   温度快適性（CPU温度）
  - safety:    安全性（衝突回避）
  - novelty:   新奇性（退屈からの脱出）
  - social:    社会性（人との接触）
  - territory: 縄張り（ディスク/メモリ空間）

各欲求が感情を直接修飾し、閾値を超えると自律行動をトリガーする。
"""
import json
import os
import time
import threading

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

import config as cfg


class Drive:
    """一つの欲求/衝動"""
    def __init__(self, name, decay_rate=0.001, threshold=0.7):
        self.name = name
        self.level = 0.0          # 0.0=満足, 1.0=緊急
        self.decay_rate = decay_rate  # 自然増加率（/秒）— 満たされないと上がる
        self.threshold = threshold    # 行動トリガー閾値
        self.last_satisfied = time.time()
        self.last_triggered = 0

    def satisfy(self, amount=1.0):
        """欲求を満たす"""
        self.level = max(0.0, self.level - amount)
        self.last_satisfied = time.time()

    def frustrate(self, amount=0.1):
        """欲求を高める（不満）"""
        self.level = min(1.0, self.level + amount)

    def tick(self, dt):
        """時間経過で欲求が自然に高まる"""
        self.level = min(1.0, self.level + self.decay_rate * dt)

    def is_urgent(self):
        return self.level >= self.threshold

    def to_dict(self):
        return {
            "name": self.name,
            "level": round(self.level, 3),
            "urgent": self.is_urgent(),
            "threshold": self.threshold,
        }


class SurvivalEngine:
    """パルの生存エンジン — 言語以前の衝動層"""

    def __init__(self):
        # 欲求の定義
        self.drives = {
            "energy": Drive("energy", decay_rate=0.0005, threshold=0.7),
            "thermal": Drive("thermal", decay_rate=0.0, threshold=0.6),  # 温度依存、自然増加なし
            "safety": Drive("safety", decay_rate=0.0, threshold=0.5),    # イベント駆動
            "novelty": Drive("novelty", decay_rate=0.002, threshold=0.8),  # 退屈しやすい
            "social": Drive("social", decay_rate=0.001, threshold=0.7),
            "territory": Drive("territory", decay_rate=0.0, threshold=0.8),  # リソース依存
        }

        # 身体状態キャッシュ
        self.body_state = {}
        self.scene_data = {}
        self._lock = threading.Lock()

        # 行動履歴
        self.action_log = []
        self.last_tick = time.time()

        # MQTT
        self.mqtt_client = None
        self.mqtt_connected = False

        # 自律行動の有効/無効
        self.autonomous_actions = True

    def setup_mqtt(self):
        if not HAS_MQTT:
            return
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "survival_engine")
        except (AttributeError, TypeError):
            self.mqtt_client = mqtt.Client("survival_engine")
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect

        try:
            self.mqtt_client.connect(cfg.MQTT_BROKER, cfg.MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print("[Survival] MQTT connecting...")
        except Exception as e:
            print("[Survival] MQTT error: {}".format(e))

    def _on_connect(self, *args):
        client = args[0] if args else self.mqtt_client
        self.mqtt_connected = True
        print("[Survival] MQTT connected")
        # 身体信号を購読
        client.subscribe(cfg.TOPIC_BODY)
        client.subscribe(cfg.TOPIC_SCENE)
        client.subscribe(cfg.TOPIC_COLLISION)
        client.message_callback_add(cfg.TOPIC_BODY, self._on_body)
        client.message_callback_add(cfg.TOPIC_SCENE, self._on_scene)
        client.message_callback_add(cfg.TOPIC_COLLISION, self._on_collision)

    def _on_disconnect(self, *args):
        self.mqtt_connected = False

    def _on_body(self, client, userdata, msg):
        """身体信号受信 → 欲求更新"""
        try:
            data = json.loads(msg.payload)
            with self._lock:
                self.body_state = data
            self._process_body(data)
        except Exception as e:
            print("[Survival] body parse error: {}".format(e))

    def _on_scene(self, client, userdata, msg):
        """VLMシーン受信 → 新奇性・社会性更新"""
        try:
            data = json.loads(msg.payload)
            with self._lock:
                old_scene = self.scene_data
                self.scene_data = data

            # 人を検出 → 社会性欲求を満たす
            people = data.get("people", 0)
            if people > 0:
                self.drives["social"].satisfy(0.5)

            # シーンが変化 → 新奇性欲求を満たす
            changes = data.get("changes", "")
            if changes and "変化なし" not in changes and "ありません" not in changes:
                self.drives["novelty"].satisfy(0.3)

        except Exception as e:
            print("[Survival] scene parse error: {}".format(e))

    def _on_collision(self, client, userdata, msg):
        """衝突 → 安全性欲求が急上昇"""
        try:
            data = json.loads(msg.payload)
            if data.get("collision"):
                self.drives["safety"].frustrate(0.5)
                print("[Survival] 💥 safety drive +0.5")
        except Exception:
            pass

    def _process_body(self, body):
        """身体信号から欲求を直接計算"""
        # --- エネルギー ---
        voltage = body.get("voltage", -1)
        if voltage > 0:
            # 7.4V=満充電(2S LiPo), 6.4V=空
            if voltage < 6.8:
                self.drives["energy"].frustrate(0.3)
            elif voltage < 7.0:
                self.drives["energy"].frustrate(0.1)
            elif voltage > 7.2:
                self.drives["energy"].satisfy(0.2)

        # --- 温度快適性 ---
        temp = body.get("cpu_temp", -1)
        if temp > 0:
            if temp > 70:
                self.drives["thermal"].level = 0.9  # 危険
            elif temp > 60:
                self.drives["thermal"].frustrate(0.2)
            elif temp > 50:
                self.drives["thermal"].frustrate(0.05)
            else:
                self.drives["thermal"].satisfy(0.1)  # 快適

        # --- 縄張り（リソース）---
        disk = body.get("disk_percent", -1)
        mem = body.get("memory_percent", -1)
        if disk > 0:
            if disk > 90:
                self.drives["territory"].frustrate(0.3)
            elif disk > 80:
                self.drives["territory"].frustrate(0.1)
            else:
                self.drives["territory"].satisfy(0.1)
        if mem > 0:
            if mem > 90:
                self.drives["territory"].frustrate(0.2)
            elif mem > 80:
                self.drives["territory"].frustrate(0.05)

        # --- 退屈（長時間動いてない）---
        idle = body.get("idle_sec", 0)
        if idle > 300:  # 5分以上
            self.drives["novelty"].frustrate(0.05)
        if idle > 600:  # 10分以上
            self.drives["social"].frustrate(0.03)

    def tick(self):
        """時間経過処理 + 自律行動判定"""
        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now

        # 全欲求の自然増加
        for drive in self.drives.values():
            drive.tick(dt)

        # 安全性は時間で回復
        if now - self.drives["safety"].last_satisfied > 10:
            self.drives["safety"].satisfy(0.02 * dt)

        # 自律行動判定
        actions = self._decide_actions()

        # 状態をMQTTにpublish
        state = self.get_state()
        state["actions"] = actions
        if self.mqtt_client and self.mqtt_connected:
            self.mqtt_client.publish(
                cfg.TOPIC_SURVIVAL,
                json.dumps(state, ensure_ascii=False)
            )

        return state

    def _decide_actions(self):
        """欲求レベルに基づいて自律行動を決定"""
        if not self.autonomous_actions:
            return []

        actions = []
        now = time.time()

        # 最も緊急な欲求を特定
        urgent = [(n, d) for n, d in self.drives.items() if d.is_urgent()]
        urgent.sort(key=lambda x: x[1].level, reverse=True)

        for name, drive in urgent:
            # 同じ行動を30秒以内に繰り返さない
            if now - drive.last_triggered < 30:
                continue

            action = None

            if name == "energy" and drive.level > 0.8:
                action = {
                    "type": "seek_energy",
                    "urgency": drive.level,
                    "description": "バッテリーが低い...充電したい",
                }
            elif name == "thermal" and drive.level > 0.7:
                action = {
                    "type": "cool_down",
                    "urgency": drive.level,
                    "description": "熱い...動きを減らそう",
                }
            elif name == "safety" and drive.level > 0.6:
                action = {
                    "type": "retreat",
                    "urgency": drive.level,
                    "description": "危ない...後退しよう",
                }
            elif name == "novelty" and drive.level > 0.8:
                action = {
                    "type": "explore",
                    "urgency": drive.level,
                    "description": "退屈...どこか行きたい",
                }
            elif name == "social" and drive.level > 0.8:
                action = {
                    "type": "seek_social",
                    "urgency": drive.level,
                    "description": "誰かに会いたい...",
                }
            elif name == "territory" and drive.level > 0.8:
                action = {
                    "type": "clean_space",
                    "urgency": drive.level,
                    "description": "空間が狭い...整理したい",
                }

            if action:
                action["drive"] = name
                action["timestamp"] = now
                actions.append(action)
                drive.last_triggered = now

                # MQTTで行動指示をpublish
                if self.mqtt_client and self.mqtt_connected:
                    self.mqtt_client.publish(
                        cfg.TOPIC_SURVIVAL_ACTION,
                        json.dumps(action, ensure_ascii=False)
                    )
                print("[Survival] 🚨 ACTION: {} (urgency={:.2f})".format(
                    action["type"], action["urgency"]))

        return actions

    def get_state(self):
        """現在の生存状態を返す"""
        drives_dict = {name: d.to_dict() for name, d in self.drives.items()}

        # 最も強い欲求
        dominant = max(self.drives.items(), key=lambda x: x[1].level)

        return {
            "timestamp": time.time(),
            "drives": drives_dict,
            "dominant_drive": dominant[0],
            "dominant_level": round(dominant[1].level, 3),
            "body": self.body_state,
        }

    def get_emotion_modifiers(self):
        """感情システムに渡す修飾値を計算
        Returns:
            dict: {emotion_name: modifier_value} — 正=その感情を強化、負=抑制
        """
        mods = {}

        e = self.drives["energy"]
        t = self.drives["thermal"]
        s = self.drives["safety"]
        n = self.drives["novelty"]
        so = self.drives["social"]
        te = self.drives["territory"]

        # エネルギー低い → anxious
        if e.level > 0.5:
            mods["anxious"] = e.level * 0.5
            mods["excited"] = -e.level * 0.3  # 興奮を抑制

        # 温度高い → anxious, calm抑制
        if t.level > 0.5:
            mods["anxious"] = mods.get("anxious", 0) + t.level * 0.3
            mods["calm"] = -t.level * 0.4

        # 衝突後 → startled, safety
        if s.level > 0.3:
            mods["startled"] = s.level * 0.6
            mods["curious"] = -s.level * 0.3  # 好奇心を抑制

        # 退屈 → bored, novelty渇望 → curiousを強化
        if n.level > 0.5:
            mods["bored"] = n.level * 0.4
            mods["curious"] = mods.get("curious", 0) + n.level * 0.3  # 探索欲

        # 孤独 → lonely
        if so.level > 0.5:
            mods["lonely"] = so.level * 0.5
            mods["happy"] = -so.level * 0.2

        # リソース不足 → anxious
        if te.level > 0.5:
            mods["anxious"] = mods.get("anxious", 0) + te.level * 0.2

        return mods

    def run(self, interval=1.0):
        """スタンドアロン実行（デバッグ用）"""
        print("[Survival] Starting survival engine (interval={}s)".format(interval))
        self.setup_mqtt()

        cycle = 0
        try:
            while True:
                state = self.tick()
                cycle += 1

                if cycle % 10 == 0:
                    dom = state["dominant_drive"]
                    dom_lvl = state["dominant_level"]
                    drives_str = " ".join(
                        "{}:{:.2f}{}".format(n, d["level"], "!" if d["urgent"] else "")
                        for n, d in state["drives"].items()
                        if d["level"] > 0.1
                    )
                    print("[Survival #{:>4d}] dominant={} ({:.2f}) | {}".format(
                        cycle, dom, dom_lvl, drives_str or "all satisfied"))

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[Survival] Stopped")
        finally:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PAL Survival Engine")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--no-actions", action="store_true",
                        help="Disable autonomous actions")
    args = parser.parse_args()

    engine = SurvivalEngine()
    engine.autonomous_actions = not args.no_actions
    engine.run(interval=args.interval)
