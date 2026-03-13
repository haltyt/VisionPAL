#!/usr/bin/env python3
"""Vision PAL - Explore Behavior (VLA Phase 1)
survival_engineのexploreアクション → VLMシーン + LLM行動プランニング → モーター探索行動

Phase 1 VLA: VLMが見たシーン + Survival Engineの欲求状態をLLMに渡し、
「次にどこに行くべきか」を言語で推論させて行動に変換する。

探索ロジック:
  1. VLMシーン情報 + 欲求状態からLLMが行動プランを生成
  2. LLMの判断: forward/left/right/backward + 理由
  3. collision_detect連携で安全確認
  4. 新しいシーンを見つけたら（novelty satisfied）探索終了

MQTTトピック:
  Subscribe: vision_pal/survival/action    ← explore指示受信
             vision_pal/perception/collision ← 衝突検知
             vision_pal/perception/scene     ← VLMシーン情報
             vision_pal/survival/state       ← 欲求状態
  Publish:   vision_pal/move               ← モーター制御
             vision_pal/explore/state       ← 探索状態

JetBotで実行: python3 explore_behavior.py
（mqtt_robot.pyと同時に動かす）
"""
import json
import os
import time
import random
import threading
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# === 設定 ===
MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.3.5")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# OpenClaw API（LLM呼び出し用）
OPENCLAW_API_URL = os.environ.get("OPENCLAW_API_URL", "http://172.19.0.2:18789")
OPENCLAW_GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

# トピック
TOPIC_SURVIVAL_ACTION = "vision_pal/survival/action"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_SCENE = "vision_pal/perception/scene"
TOPIC_MOVE = "vision_pal/move"
TOPIC_EXPLORE_STATE = "vision_pal/explore/state"
TOPIC_SURVIVAL = "vision_pal/survival/state"

# 探索パラメータ
EXPLORE_SPEED = 0.35           # 探索時の速度（安全のため低め）
TURN_SPEED = 0.4               # 旋回時の速度
MAX_EXPLORE_TIME = 90          # 最大探索時間（秒）
COOLDOWN = 30                  # 探索後のクールダウン（秒）
COLLISION_RETREAT_TIME = 0.8   # 衝突時の後退時間
COLLISION_TURN_TIME = 0.8      # 衝突後の旋回時間
PLAN_INTERVAL = 4.0            # LLMプランニング間隔（秒）
FALLBACK_FORWARD = (1.0, 3.0)  # LLM使えない時のフォールバック前進時間
FALLBACK_TURN = (0.3, 1.2)     # フォールバック旋回時間

# LLM行動プランニング用プロンプト
PLAN_SYSTEM = """あなたはJetBotロボットの探索行動プランナーです。
カメラが見ているシーンと内部欲求の状態から、次の1アクションを決定してください。

ルール:
- 応答はJSON形式のみ: {"action": "forward|left|right|backward", "duration": 0.5-3.0, "reason": "理由"}
- 新しいものが見える方向に向かう
- 壁や障害物が見えたら避ける方向に
- 同じ景色が続いていたら方向転換
- 人が見えたらそちらに向かう（social欲求が高い場合）
- 安全第一: 障害物が近い場合はbackwardかturn
"""


class VLAPlanner:
    """Phase 1 VLA: LLMベースの行動プランナー"""

    def __init__(self, api_url, token):
        self.api_url = api_url
        self.token = token
        self.available = bool(HAS_REQUESTS and api_url and token)
        if self.available:
            print("[VLA] LLM planner enabled: {}".format(api_url))
        else:
            reasons = []
            if not HAS_REQUESTS:
                reasons.append("requests not installed")
            if not api_url:
                reasons.append("no API URL")
            if not token:
                reasons.append("no token")
            print("[VLA] LLM planner disabled ({}). Using fallback random walk.".format(
                ", ".join(reasons)))

    def plan(self, scene_data, survival_state, explore_history):
        """シーン + 欲求状態からLLMに次のアクションを計画させる

        Args:
            scene_data: dict — VLMからのシーン情報
            survival_state: dict — survival engineの欲求状態
            explore_history: list — 直近のアクション履歴

        Returns:
            dict: {"action": str, "duration": float, "reason": str}
            or None on failure
        """
        if not self.available:
            return None

        # 欲求の要約
        drives_summary = ""
        drives = survival_state.get("drives", {})
        for name, drive in drives.items():
            level = drive.get("level", 0)
            if level > 0.3:
                urgent = "⚠️" if drive.get("urgent") else ""
                drives_summary += "  {}: {:.2f}{}\n".format(name, level, urgent)

        # シーン情報の要約
        scene_summary = scene_data.get("summary", "不明")
        obstacles = scene_data.get("obstacles", [])
        people = scene_data.get("people", 0)
        changes = scene_data.get("changes", "")

        # 直近のアクション履歴
        recent = ""
        if explore_history:
            recent = "直近のアクション: " + ", ".join(
                "{}({:.1f}s)".format(h["action"], h["duration"])
                for h in explore_history[-5:]
            )

        user_prompt = """## 現在のカメラ映像
シーン: {scene}
障害物: {obs}
人の数: {people}
変化: {changes}

## 内部欲求
{drives}

## 履歴
{recent}

次の1アクションをJSONで返してください。""".format(
            scene=scene_summary[:200],
            obs=", ".join(obstacles[:5]) if obstacles else "なし",
            people=people,
            changes=changes[:100] if changes else "なし",
            drives=drives_summary or "  すべて正常",
            recent=recent or "なし（探索開始直後）",
        )

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.token),
            }
            payload = {
                "model": "flash",  # 軽量モデルで十分
                "messages": [
                    {"role": "system", "content": PLAN_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 150,
                "temperature": 0.3,
            }

            resp = requests.post(
                "{}/v1/chat/completions".format(self.api_url),
                json=payload,
                headers=headers,
                timeout=8,
            )

            if resp.status_code != 200:
                print("[VLA] API error: {} {}".format(resp.status_code, resp.text[:100]))
                return None

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # JSONを抽出（コードブロックにラップされてる場合も対応）
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            plan = json.loads(content)

            # バリデーション
            action = plan.get("action", "forward")
            if action not in ("forward", "left", "right", "backward"):
                action = "forward"
            duration = float(plan.get("duration", 1.5))
            duration = max(0.3, min(3.0, duration))
            reason = plan.get("reason", "")

            print("[VLA] Plan: {} {:.1f}s — {}".format(action, duration, reason[:60]))
            return {"action": action, "duration": duration, "reason": reason}

        except json.JSONDecodeError as e:
            print("[VLA] JSON parse error: {}".format(e))
            return None
        except Exception as e:
            print("[VLA] Plan error: {}".format(e))
            return None


class ExploreBehavior:
    """自律探索行動モジュール（VLA Phase 1対応）"""

    def __init__(self):
        self.exploring = False
        self.collision_detected = False
        self.scene_changed = False
        self.last_explore_end = 0
        self.explore_start = 0
        self.steps_taken = 0
        self.new_scenes_found = 0
        self.last_direction = "forward"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # 最新のシーン＆欲求データ
        self.current_scene = {}
        self.current_survival = {}
        self.explore_history = []  # 探索中のアクション履歴

        # VLAプランナー
        self.planner = VLAPlanner(OPENCLAW_API_URL, OPENCLAW_GATEWAY_TOKEN)

        # MQTT
        self.client = None
        if HAS_MQTT:
            self._setup_mqtt()
        else:
            print("[Explore] paho-mqtt not found!")

    def _setup_mqtt(self):
        """MQTT接続"""
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "explore_behavior")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("explore_behavior")

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            print("[Explore] MQTT connecting...")
        except Exception as e:
            print("[Explore] MQTT error: {}".format(e))

    def _on_connect(self, *args):
        print("[Explore] MQTT connected!")
        client = args[0] if args else self.client
        client.subscribe(TOPIC_SURVIVAL_ACTION)
        client.subscribe(TOPIC_COLLISION)
        client.subscribe(TOPIC_SCENE)
        client.subscribe(TOPIC_SURVIVAL)
        print("[Explore] Subscribed to action/collision/scene/survival topics")
        self._publish_state("idle", "待機中 (VLA Phase 1)")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, ValueError):
            return

        topic = msg.topic

        if topic == TOPIC_SURVIVAL_ACTION:
            self._handle_action(data)
        elif topic == TOPIC_COLLISION:
            self._handle_collision(data)
        elif topic == TOPIC_SCENE:
            self._handle_scene(data)
        elif topic == TOPIC_SURVIVAL:
            self._handle_survival_state(data)

    def _handle_action(self, data):
        """survival_engineからのアクション指示"""
        action_type = data.get("type", "")
        if action_type == "explore":
            urgency = data.get("urgency", 0.5)
            print("[Explore] 🔍 Explore action received! urgency={:.2f}".format(urgency))
            self._start_explore(urgency)
        elif action_type == "retreat":
            print("[Explore] 🛑 Retreat action — stopping explore")
            self._stop_explore("retreat指示")
        elif action_type == "seek_social":
            # 人を探すアクションも探索として処理（目的が違うだけ）
            print("[Explore] 👤 Seek social action received!")
            self._start_explore(data.get("urgency", 0.5))

    def _handle_collision(self, data):
        """衝突検知"""
        if data.get("collision"):
            with self._lock:
                self.collision_detected = True
            print("[Explore] 💥 Collision detected!")

    def _handle_scene(self, data):
        """VLMシーン情報を保存 + 新シーン検知"""
        with self._lock:
            self.current_scene = data
        changes = data.get("changes", "")
        if changes and "変化なし" not in changes and "ありません" not in changes:
            with self._lock:
                self.scene_changed = True
                self.new_scenes_found += 1
            print("[Explore] 🆕 New scene detected!")

    def _handle_survival_state(self, data):
        """survival stateを保存 + novelty回復チェック"""
        with self._lock:
            self.current_survival = data
        if not self.exploring:
            return
        drives = data.get("drives", {})
        novelty = drives.get("novelty", {})
        level = novelty.get("level", 1.0)
        if level < 0.4:
            print("[Explore] ✅ Novelty satisfied ({:.2f})! Stopping explore.".format(level))
            self._stop_explore("novelty satisfied")

    def _start_explore(self, urgency):
        """探索開始"""
        now = time.time()
        if now - self.last_explore_end < COOLDOWN:
            remaining = COOLDOWN - (now - self.last_explore_end)
            print("[Explore] ⏳ Cooldown: {:.0f}s remaining".format(remaining))
            return
        if self.exploring:
            print("[Explore] Already exploring!")
            return

        with self._lock:
            self.exploring = True
            self.explore_start = now
            self.collision_detected = False
            self.scene_changed = False
            self.steps_taken = 0
            self.new_scenes_found = 0
            self.explore_history = []
            self._stop_event.clear()

        max_time = int(MAX_EXPLORE_TIME * min(urgency, 1.0))
        max_time = max(20, max_time)

        mode = "VLA" if self.planner.available else "random"
        print("[Explore] 🚀 Starting explore! max_time={}s urgency={:.2f} mode={}".format(
            max_time, urgency, mode))
        self._publish_state("exploring", "探索開始！({} mode, max {}s)".format(mode, max_time))

        t = threading.Thread(target=self._explore_loop, args=(max_time,), daemon=True)
        t.start()

    def _explore_loop(self, max_time):
        """探索のメインループ（VLAプランナー統合）"""
        start = time.time()
        last_plan_time = 0

        try:
            while not self._stop_event.is_set():
                elapsed = time.time() - start
                if elapsed > max_time:
                    print("[Explore] ⏰ Time's up ({:.0f}s)".format(elapsed))
                    break

                # 衝突チェック
                with self._lock:
                    collision = self.collision_detected
                    self.collision_detected = False
                if collision:
                    self._handle_collision_avoidance()
                    continue

                # VLAプランニング or フォールバック
                now = time.time()
                plan = None

                if self.planner.available and (now - last_plan_time >= PLAN_INTERVAL):
                    with self._lock:
                        scene = dict(self.current_scene)
                        survival = dict(self.current_survival)
                    plan = self.planner.plan(scene, survival, self.explore_history)
                    last_plan_time = now

                if plan:
                    # VLAプランに従って行動
                    action = plan["action"]
                    duration = plan["duration"]
                    reason = plan.get("reason", "")

                    if action in ("left", "right"):
                        speed = TURN_SPEED
                    else:
                        speed = EXPLORE_SPEED

                    self._send_move(action, speed)
                    self.steps_taken += 1
                    self.explore_history.append({
                        "action": action, "duration": duration,
                        "reason": reason, "time": time.time()
                    })
                    self._publish_state("vla_action",
                        "VLA: {} {:.1f}s — {}".format(action, duration, reason[:40]))

                    # 行動実行（衝突チェック付き）
                    if not self._execute_with_collision_check(duration):
                        continue  # 衝突で中断された

                    self._send_move("stop", 0)
                    time.sleep(0.2)

                else:
                    # フォールバック: ランダムウォーク
                    forward_time = random.uniform(*FALLBACK_FORWARD)
                    self._send_move("forward", EXPLORE_SPEED)
                    self.steps_taken += 1
                    self.explore_history.append({
                        "action": "forward", "duration": forward_time,
                        "reason": "fallback random", "time": time.time()
                    })
                    self._publish_state("moving", "前進中 (fallback step {})".format(self.steps_taken))

                    if not self._execute_with_collision_check(forward_time):
                        continue

                    self._send_move("stop", 0)
                    time.sleep(0.3)

                    # ランダム旋回
                    if self.last_direction == "left":
                        direction = random.choice(["right", "right", "left"])
                    elif self.last_direction == "right":
                        direction = random.choice(["left", "left", "right"])
                    else:
                        direction = random.choice(["left", "right"])

                    turn_time = random.uniform(*FALLBACK_TURN)
                    self._send_move(direction, TURN_SPEED)
                    self.last_direction = direction

                    if not self._execute_with_collision_check(turn_time):
                        continue

                    self._send_move("stop", 0)
                    time.sleep(0.2)

                # シーン変化チェック
                with self._lock:
                    if self.scene_changed and self.new_scenes_found >= 2:
                        print("[Explore] 🎉 Found {} new scenes!".format(self.new_scenes_found))
                        break
                    self.scene_changed = False

        finally:
            self._send_move("stop", 0)
            self._stop_explore("探索完了")

    def _execute_with_collision_check(self, duration):
        """指定時間のアクション実行中、衝突をチェック。
        Returns: True=正常完了, False=衝突で中断"""
        step_start = time.time()
        while time.time() - step_start < duration:
            if self._stop_event.is_set():
                return False
            with self._lock:
                if self.collision_detected:
                    self.collision_detected = False
                    self._send_move("stop", 0)
                    self._handle_collision_avoidance()
                    return False
            time.sleep(0.1)
        return True

    def _handle_collision_avoidance(self):
        """衝突回避: 後退→旋回"""
        print("[Explore] 🔄 Collision avoidance!")
        self._publish_state("avoiding", "衝突回避中")

        self._send_move("backward", EXPLORE_SPEED)
        time.sleep(COLLISION_RETREAT_TIME)

        direction = random.choice(["left", "right"])
        turn_time = COLLISION_TURN_TIME + random.uniform(0, 0.5)
        self._send_move(direction, TURN_SPEED)
        self.last_direction = direction
        time.sleep(turn_time)

        self._send_move("stop", 0)
        time.sleep(0.2)

    def _stop_explore(self, reason=""):
        """探索終了"""
        was_exploring = False
        with self._lock:
            if self.exploring:
                was_exploring = True
                self.exploring = False
                self.last_explore_end = time.time()
                self._stop_event.set()

        if was_exploring:
            elapsed = time.time() - self.explore_start
            vla_steps = sum(1 for h in self.explore_history if h.get("reason") != "fallback random")
            total_steps = self.steps_taken
            msg = "探索終了: {} ({:.0f}s, {}ステップ[VLA:{}], {}シーン発見)".format(
                reason, elapsed, total_steps, vla_steps, self.new_scenes_found)
            print("[Explore] 🏁 {}".format(msg))
            self._publish_state("idle", msg)

            # 探索ログをMQTTで共有
            if self.client and self.explore_history:
                self.client.publish("vision_pal/explore/log", json.dumps({
                    "duration": elapsed,
                    "steps": total_steps,
                    "vla_steps": vla_steps,
                    "new_scenes": self.new_scenes_found,
                    "reason": reason,
                    "history": self.explore_history[-10:],  # 直近10アクション
                    "timestamp": time.time(),
                }, ensure_ascii=False))

    def _send_move(self, direction, speed):
        """モーター制御をMQTTで送信"""
        if self.client:
            self.client.publish(TOPIC_MOVE, json.dumps({
                "direction": direction,
                "speed": speed,
                "source": "explore_vla",
            }))

    def _publish_state(self, status, description=""):
        """探索状態をMQTTでpublish"""
        if self.client:
            self.client.publish(TOPIC_EXPLORE_STATE, json.dumps({
                "status": status,
                "description": description,
                "exploring": self.exploring,
                "steps": self.steps_taken,
                "new_scenes": self.new_scenes_found,
                "vla_enabled": self.planner.available,
                "timestamp": time.time(),
            }, ensure_ascii=False))

    def run(self):
        """メインループ（ブロッキング）"""
        print("=" * 50)
        print("  Vision PAL - Explore Behavior (VLA Phase 1)")
        print("  VLA Planner: {}".format(
            "ENABLED" if self.planner.available else "DISABLED (fallback mode)"))
        print("  Waiting for explore actions...")
        print("=" * 50)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Explore] Shutting down...")
            if self.exploring:
                self._stop_explore("shutdown")
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()


if __name__ == "__main__":
    explorer = ExploreBehavior()
    explorer.run()
