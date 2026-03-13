#!/usr/bin/env python3
"""Vision PAL - AsyncVLA Orchestrator
二層非同期VLAアーキテクチャのオーケストレータ。

Edge層（5-50ms、JetBot側）:
  collision_detect_v2.py — CNN予測で即座に回避

Cloud層（5-10秒、Jetson/コンテナ側）:
  vlm_watcher.py → cognitive_loop.py → survival_engine.py → 戦略的行動

このモジュールは両層を統合し、行動の優先度を調停する。
Edge層の安全判断はCloud層を常にオーバーライドする。

アーキテクチャ（AsyncVLA論文 arXiv:2602.13476 に着想）:
  ┌─────────────────────────────────────────┐
  │           AsyncVLA Orchestrator          │
  │                                          │
  │  ┌──────────┐    ┌───────────────────┐  │
  │  │ Edge層    │    │ Cloud層            │  │
  │  │ CNN 5ms   │    │ VLM+LLM 5-10s    │  │
  │  │ 衝突予測  │    │ 戦略的判断        │  │
  │  │ 即座回避  │    │ 探索/社会行動     │  │
  │  └─────┬────┘    └──────┬────────────┘  │
  │        │  MQTT          │  MQTT          │
  │        ▼                ▼                │
  │  ┌──────────────────────────────────┐   │
  │  │ Action Arbiter (行動調停)        │   │
  │  │ safety > explore > social > idle │   │
  │  └──────────────┬───────────────────┘   │
  │                 │                        │
  │                 ▼ MQTT: vision_pal/move  │
  │           mqtt_robot.py                  │
  └─────────────────────────────────────────┘

MQTT Topics:
  Subscribe:
    vision_pal/edge/state          ← Edge層の連続状態
    vision_pal/perception/collision ← 衝突イベント
    vision_pal/survival/state      ← Survival Engine欲求
    vision_pal/survival/action     ← 自律行動指示
    vision_pal/perception/scene    ← VLMシーン
  Publish:
    vision_pal/vla/state           ← VLA統合状態
    vision_pal/move                ← 最終行動指示

Usage:
    python3 async_vla.py
    python3 async_vla.py --no-cloud   # Edge層のみ
"""

import json
import os
import sys
import time
import threading
import signal

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[VLA] paho-mqtt required!")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg


# ─── Action Priority ────────────────────────────────────
# 数値が大きいほど優先
PRIORITY = {
    "emergency_stop": 100,   # Edge: 衝突検知/予測
    "retreat": 90,           # Survival: safety urgent
    "cool_down": 80,         # Survival: thermal urgent
    "seek_energy": 70,       # Survival: energy urgent
    "avoid": 60,             # Edge: danger zone (blocked > 0.5)
    "explore": 40,           # Survival: novelty urgent
    "seek_social": 30,       # Survival: social urgent
    "clean_space": 20,       # Survival: territory urgent
    "cloud_action": 10,      # Cloud: VLM suggested action
    "idle": 0,               # 何もしない
}

# Edge→モーター変換
EDGE_ACTIONS = {
    "emergency_stop": {"action": "stop", "speed": 0, "duration": 0},
    "retreat": {"action": "backward", "speed": 150, "duration": 1.0},
    "avoid": {"action": "left", "speed": 120, "duration": 0.5},
}

running = True


def signal_handler(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class ActionArbiter:
    """行動調停 — 複数ソースからの行動指示を優先度で調停"""

    def __init__(self):
        self.pending_actions = {}  # source → action
        self._lock = threading.Lock()
        self.current_action = None
        self.action_until = 0      # アクション有効期限

    def propose(self, source, action_type, details=None, ttl=3.0):
        """行動を提案（sourceごとに1つ）"""
        priority = PRIORITY.get(action_type, 0)
        with self._lock:
            self.pending_actions[source] = {
                "type": action_type,
                "priority": priority,
                "details": details or {},
                "proposed_at": time.time(),
                "ttl": ttl,
            }

    def resolve(self):
        """最も優先度の高い行動を選択"""
        now = time.time()
        with self._lock:
            # 期限切れを除去
            expired = [k for k, v in self.pending_actions.items()
                       if now - v["proposed_at"] > v["ttl"]]
            for k in expired:
                del self.pending_actions[k]

            if not self.pending_actions:
                return {"type": "idle", "priority": 0, "source": "none"}

            # 最高優先度を選択
            best_source = max(self.pending_actions,
                              key=lambda k: self.pending_actions[k]["priority"])
            best = self.pending_actions[best_source].copy()
            best["source"] = best_source
            return best

    def clear(self, source=None):
        with self._lock:
            if source:
                self.pending_actions.pop(source, None)
            else:
                self.pending_actions.clear()


class AsyncVLAOrchestrator:
    """AsyncVLA二層統合オーケストレータ"""

    def __init__(self, cloud_enabled=True):
        self.cloud_enabled = cloud_enabled
        self.arbiter = ActionArbiter()

        # Edge層の状態
        self.edge_state = {
            "blocked_prob": 0.0,
            "danger_zone": False,
            "inference_ms": 0,
        }

        # Cloud層の状態
        self.cloud_state = {
            "scene": {},
            "drives": {},
            "dominant_drive": "none",
            "actions": [],
        }

        # VLA統合状態
        self.cycle = 0
        self.last_action = None
        self.action_log = []

        # MQTT
        self.mqtt = None
        self._setup_mqtt()

    def _setup_mqtt(self):
        try:
            self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "async_vla")
        except (AttributeError, TypeError):
            self.mqtt = mqtt.Client("async_vla")

        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_disconnect = self._on_disconnect
        self.mqtt.connect(cfg.MQTT_BROKER, cfg.MQTT_PORT, 60)
        self.mqtt.loop_start()

    def _on_connect(self, *args):
        client = args[0] if args else self.mqtt
        print("[VLA] MQTT connected")

        # Edge層
        client.subscribe("vision_pal/edge/state")
        client.subscribe(cfg.TOPIC_COLLISION)

        # Cloud層
        client.subscribe(cfg.TOPIC_SURVIVAL)
        client.subscribe(cfg.TOPIC_SURVIVAL_ACTION)
        client.subscribe(cfg.TOPIC_SCENE)

        client.message_callback_add("vision_pal/edge/state", self._on_edge)
        client.message_callback_add(cfg.TOPIC_COLLISION, self._on_collision)
        client.message_callback_add(cfg.TOPIC_SURVIVAL, self._on_survival)
        client.message_callback_add(cfg.TOPIC_SURVIVAL_ACTION, self._on_survival_action)
        client.message_callback_add(cfg.TOPIC_SCENE, self._on_scene)

    def _on_disconnect(self, *args):
        print("[VLA] MQTT disconnected")

    # ── Edge層イベント ──

    def _on_edge(self, client, userdata, msg):
        """Edge層の連続状態（10フレームごと）"""
        try:
            data = json.loads(msg.payload)
            self.edge_state = data

            blocked = data.get("blocked_prob", 0)
            if blocked > 0.5 and data.get("motor_running", False):
                # 危険ゾーン → 回避提案
                self.arbiter.propose("edge_avoid", "avoid", {
                    "blocked_prob": blocked,
                    "direction": "left",  # TODO: 方向推定
                }, ttl=1.0)

        except Exception as e:
            print("[VLA] edge parse error: {}".format(e))

    def _on_collision(self, client, userdata, msg):
        """衝突イベント（緊急）"""
        try:
            data = json.loads(msg.payload)
            if data.get("collision"):
                severity = data.get("severity", "detected")
                self.arbiter.propose("edge_collision", "emergency_stop", {
                    "severity": severity,
                    "blocked_prob": data.get("blocked_prob", 0),
                }, ttl=5.0)

                print("[VLA] 🚨 衝突{}: blocked={:.2f}".format(
                    "予測" if severity == "predicted" else "検知",
                    data.get("blocked_prob", 0),
                ))
        except Exception:
            pass

    # ── Cloud層イベント ──

    def _on_survival(self, client, userdata, msg):
        """Survival Engine状態"""
        try:
            data = json.loads(msg.payload)
            self.cloud_state["drives"] = data.get("drives", {})
            self.cloud_state["dominant_drive"] = data.get("dominant_drive", "none")
        except Exception:
            pass

    def _on_survival_action(self, client, userdata, msg):
        """Survival Engineの自律行動"""
        try:
            data = json.loads(msg.payload)
            action_type = data.get("type", "")
            if action_type in PRIORITY:
                self.arbiter.propose("survival_" + action_type, action_type, data, ttl=10.0)
                print("[VLA] Survival action: {} (urgency={:.2f})".format(
                    action_type, data.get("urgency", 0)))
        except Exception:
            pass

    def _on_scene(self, client, userdata, msg):
        """VLMシーン"""
        try:
            data = json.loads(msg.payload)
            self.cloud_state["scene"] = data

            # シーンからの行動提案
            action = data.get("suggested_action", "")
            if action and action != "forward":
                self.arbiter.propose("vlm_scene", "cloud_action", {
                    "vlm_action": action,
                    "summary": data.get("summary", ""),
                }, ttl=5.0)
        except Exception:
            pass

    # ── メインループ ──

    def _execute_action(self, action):
        """行動を実行（MQTT publish）"""
        action_type = action["type"]

        if action_type == "idle":
            return

        # Edge系アクション → 直接モーター制御
        if action_type in EDGE_ACTIONS:
            move_cmd = EDGE_ACTIONS[action_type].copy()
            move_cmd["source"] = "async_vla"
            move_cmd["reason"] = action_type
            self.mqtt.publish(cfg.TOPIC_MOVE, json.dumps(move_cmd, ensure_ascii=False))
            return

        # Survival系アクション → explore_behaviorに委譲
        if action_type in ("explore", "seek_social"):
            self.mqtt.publish(cfg.TOPIC_SURVIVAL_ACTION,
                              json.dumps(action.get("details", {}), ensure_ascii=False))
            return

        # Cloud系アクション → VLM提案をモーターに変換
        if action_type == "cloud_action":
            vlm_action = action.get("details", {}).get("vlm_action", "stop")
            move_map = {
                "forward": {"action": "forward", "speed": 100, "duration": 1.0},
                "stop": {"action": "stop", "speed": 0, "duration": 0},
                "turn_left": {"action": "left", "speed": 100, "duration": 0.5},
                "turn_right": {"action": "right", "speed": 100, "duration": 0.5},
                "reverse": {"action": "backward", "speed": 100, "duration": 0.5},
            }
            move_cmd = move_map.get(vlm_action, {"action": "stop", "speed": 0, "duration": 0})
            move_cmd["source"] = "async_vla_cloud"
            self.mqtt.publish(cfg.TOPIC_MOVE, json.dumps(move_cmd, ensure_ascii=False))

    def tick(self):
        """1サイクル処理"""
        self.cycle += 1

        # 行動調停
        action = self.arbiter.resolve()

        # 新しい行動 or 変化があれば実行
        if action["type"] != "idle":
            if (self.last_action is None or
                    self.last_action["type"] != action["type"]):
                self._execute_action(action)
                self.last_action = action

                self.action_log.append({
                    "cycle": self.cycle,
                    "action": action["type"],
                    "source": action.get("source", "?"),
                    "priority": action["priority"],
                    "time": time.time(),
                })
                # 直近20件のみ保持
                self.action_log = self.action_log[-20:]
        else:
            self.last_action = None

        # VLA統合状態をpublish（2秒ごと）
        if self.cycle % 4 == 0:
            vla_state = {
                "cycle": self.cycle,
                "edge": {
                    "blocked_prob": self.edge_state.get("blocked_prob", 0),
                    "danger_zone": self.edge_state.get("danger_zone", False),
                    "inference_ms": self.edge_state.get("avg_inference_ms", 0),
                },
                "cloud": {
                    "dominant_drive": self.cloud_state.get("dominant_drive", "none"),
                    "scene_summary": self.cloud_state.get("scene", {}).get("summary", ""),
                },
                "current_action": action["type"],
                "action_source": action.get("source", "none"),
                "action_priority": action["priority"],
                "timestamp": time.time(),
            }
            self.mqtt.publish("vision_pal/vla/state",
                              json.dumps(vla_state, ensure_ascii=False))

    def run(self, interval=0.5):
        """メインループ"""
        print("=" * 55)
        print("🧠 AsyncVLA Orchestrator")
        print("=" * 55)
        print("  Edge層: collision_detect_v2.py (CNN 5ms)")
        print("  Cloud層: vlm_watcher + survival_engine (5-10s)")
        print("  Arbiter: safety > explore > social > idle")
        print("  Interval: {}ms".format(int(interval * 1000)))
        print("=" * 55)

        global running
        last_log = 0

        try:
            while running:
                self.tick()

                # 5秒ごとにログ
                now = time.time()
                if now - last_log > 5:
                    edge_bp = self.edge_state.get("blocked_prob", 0)
                    dom = self.cloud_state.get("dominant_drive", "?")
                    act = self.last_action["type"] if self.last_action else "idle"
                    print("[VLA #{:>4d}] edge={:.2f}{} cloud={} action={}".format(
                        self.cycle,
                        edge_bp,
                        "⚠️" if self.edge_state.get("danger_zone") else "",
                        dom,
                        act,
                    ))
                    last_log = now

                time.sleep(interval)

        except Exception as e:
            print("[VLA] Error: {}".format(e))
            import traceback
            traceback.print_exc()
        finally:
            if self.mqtt:
                self.mqtt.loop_stop()
                self.mqtt.disconnect()
            print("[VLA] 終了")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AsyncVLA Orchestrator")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="tick間隔(秒)")
    parser.add_argument("--no-cloud", action="store_true",
                        help="Cloud層無効")
    args = parser.parse_args()

    vla = AsyncVLAOrchestrator(cloud_enabled=not args.no_cloud)
    vla.run(interval=args.interval)


if __name__ == "__main__":
    main()
