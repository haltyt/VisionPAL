#!/usr/bin/env python3
"""Vision PAL - Explore Behavior
survival_engineのexploreアクション → 実際のモーター探索行動

探索ロジック:
  1. scene_memoryの既知シーン数＆最後のシーン繰り返し回数を参考に方向を決定
  2. collision_detect連携で安全確認
  3. 一定時間前進→ランダム旋回→前進のパターンで探索
  4. 新しいシーンを見つけたら（novelty satisfied）探索終了

MQTTトピック:
  Subscribe: vision_pal/survival/action    ← explore指示受信
             vision_pal/perception/collision ← 衝突検知
             vision_pal/perception/scene     ← シーン変化検知
  Publish:   vision_pal/move               ← モーター制御
             vision_pal/explore/state       ← 探索状態

JetBotで実行: python3 explore_behavior.py
（mqtt_robot.pyと同時に動かす。explore_behaviorがvision_pal/moveにpublish→mqtt_robot.pyがモーター制御）
"""
import json
import time
import random
import threading
import paho.mqtt.client as mqtt

# === 設定 ===
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883

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
FORWARD_DURATION = (1.0, 3.0)  # 前進時間の範囲（秒）
TURN_DURATION = (0.3, 1.2)     # 旋回時間の範囲（秒）
MAX_EXPLORE_TIME = 60          # 最大探索時間（秒）
COOLDOWN = 30                  # 探索後のクールダウン（秒）
COLLISION_RETREAT_TIME = 0.8   # 衝突時の後退時間
COLLISION_TURN_TIME = 0.8      # 衝突後の旋回時間


class ExploreBehavior:
    """自律探索行動モジュール"""

    def __init__(self):
        self.exploring = False
        self.collision_detected = False
        self.scene_changed = False
        self.last_explore_end = 0
        self.explore_start = 0
        self.steps_taken = 0
        self.new_scenes_found = 0
        self.last_direction = "forward"  # 最後の移動方向（同じ方向を避ける）
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # MQTT
        self.client = None
        self._setup_mqtt()

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
        self._publish_state("idle", "待機中")

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

    def _handle_collision(self, data):
        """衝突検知"""
        if data.get("collision"):
            with self._lock:
                self.collision_detected = True
            print("[Explore] 💥 Collision detected!")

    def _handle_scene(self, data):
        """シーン変化検知"""
        changes = data.get("changes", "")
        if changes and "変化なし" not in changes and "ありません" not in changes:
            with self._lock:
                self.scene_changed = True
                self.new_scenes_found += 1
            print("[Explore] 🆕 New scene detected!")

    def _handle_survival_state(self, data):
        """survival stateを監視。noveltyが十分下がったら探索終了"""
        if not self.exploring:
            return
        drives = data.get("drives", {})
        novelty = drives.get("novelty", {})
        level = novelty.get("level", 1.0)
        # noveltyが0.4以下に下がったら探索成功
        if level < 0.4:
            print("[Explore] ✅ Novelty satisfied ({:.2f})! Stopping explore.".format(level))
            self._stop_explore("novelty satisfied")

    def _start_explore(self, urgency):
        """探索開始"""
        now = time.time()

        # クールダウンチェック
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
            self._stop_event.clear()

        # 探索時間をurgencyに応じて調整
        max_time = int(MAX_EXPLORE_TIME * min(urgency, 1.0))
        max_time = max(15, max_time)  # 最低15秒

        print("[Explore] 🚀 Starting explore! max_time={}s urgency={:.2f}".format(
            max_time, urgency))
        self._publish_state("exploring", "探索開始！(max {}s)".format(max_time))

        # 探索を別スレッドで実行
        t = threading.Thread(target=self._explore_loop, args=(max_time,), daemon=True)
        t.start()

    def _explore_loop(self, max_time):
        """探索のメインループ"""
        start = time.time()

        try:
            while not self._stop_event.is_set():
                elapsed = time.time() - start

                # タイムアウト
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

                # 前進
                forward_time = random.uniform(*FORWARD_DURATION)
                self._send_move("forward", EXPLORE_SPEED)
                self.steps_taken += 1
                self._publish_state("moving", "前進中 (step {})".format(self.steps_taken))

                # 前進中も衝突チェック（0.1秒刻み）
                step_start = time.time()
                while time.time() - step_start < forward_time:
                    if self._stop_event.is_set():
                        break
                    with self._lock:
                        if self.collision_detected:
                            self.collision_detected = False
                            self._send_move("stop", 0)
                            self._handle_collision_avoidance()
                            break
                    time.sleep(0.1)
                else:
                    # 正常に前進完了 → 旋回
                    self._send_move("stop", 0)
                    time.sleep(0.3)

                    # ランダム旋回（前回と違う方向を優先）
                    if self.last_direction == "left":
                        direction = random.choice(["right", "right", "left"])
                    elif self.last_direction == "right":
                        direction = random.choice(["left", "left", "right"])
                    else:
                        direction = random.choice(["left", "right"])

                    turn_time = random.uniform(*TURN_DURATION)
                    self._send_move(direction, TURN_SPEED)
                    self.last_direction = direction
                    self._publish_state("turning", "旋回中 ({})".format(direction))

                    # 旋回待機
                    turn_start = time.time()
                    while time.time() - turn_start < turn_time:
                        if self._stop_event.is_set():
                            break
                        time.sleep(0.1)

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

    def _handle_collision_avoidance(self):
        """衝突回避: 後退→旋回"""
        print("[Explore] 🔄 Collision avoidance!")
        self._publish_state("avoiding", "衝突回避中")

        # 後退
        self._send_move("backward", EXPLORE_SPEED)
        time.sleep(COLLISION_RETREAT_TIME)

        # ランダム旋回（少し長めに）
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
            msg = "探索終了: {} ({:.0f}s, {}ステップ, {}シーン発見)".format(
                reason, elapsed, self.steps_taken, self.new_scenes_found)
            print("[Explore] 🏁 {}".format(msg))
            self._publish_state("idle", msg)

    def _send_move(self, direction, speed):
        """モーター制御をMQTTで送信"""
        if self.client:
            self.client.publish(TOPIC_MOVE, json.dumps({
                "direction": direction,
                "speed": speed,
                "source": "explore",
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
                "timestamp": time.time(),
            }, ensure_ascii=False))

    def run(self):
        """メインループ（ブロッキング）"""
        print("=" * 40)
        print("  Vision PAL - Explore Behavior")
        print("  Waiting for explore actions...")
        print("=" * 40)

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
