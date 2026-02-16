"""Vision PAL - Affect Module
パルの感情状態を算出する。知覚・行動・衝突情報から内部感情を決定。
"""
import time
import json
from config import EMOTIONS


class Affect:
    """パルの感情モジュール"""

    def __init__(self):
        self.current_emotion = "calm"
        self.valence = 0.5       # 快-不快 (0=不快, 1=快)
        self.arousal = 0.2       # 覚醒度 (0=低, 1=高)
        self.history = []        # 感情履歴（最新10件）
        self.person_seen_at = 0  # 最後に人を見た時刻
        self.collision_at = 0    # 最後に衝突した時刻
        self.moving_since = 0    # 移動開始時刻
        self.idle_since = time.time()  # 静止開始時刻

    def update(self, perception_data, motor_state="stopped", collision=False):
        """知覚データとモーター状態から感情を更新"""
        now = time.time()

        has_person = perception_data.get("has_person", False)
        object_count = perception_data.get("object_count", 0)

        # --- イベント検知 ---
        if has_person:
            self.person_seen_at = now

        if collision:
            self.collision_at = now

        if motor_state == "running":
            if self.moving_since == 0:
                self.moving_since = now
            self.idle_since = 0
        else:
            if self.idle_since == 0:
                self.idle_since = now
            self.moving_since = 0

        # --- 感情決定ロジック ---
        # 衝突直後 → startled
        if now - self.collision_at < 3:
            emotion = "startled"

        # 人を見つけた → happy
        elif has_person:
            emotion = "happy"

        # 人を見たのが最近（30秒以内）→ excited
        elif now - self.person_seen_at < 30 and self.person_seen_at > 0:
            emotion = "excited"

        # 移動中 → curious
        elif motor_state == "running":
            moving_duration = now - self.moving_since
            if moving_duration > 10:
                emotion = "excited"  # 長時間移動→興奮
            else:
                emotion = "curious"

        # 長時間静止 → lonely/bored
        elif self.idle_since > 0:
            idle_duration = now - self.idle_since
            if idle_duration > 120:
                emotion = "lonely"
            elif idle_duration > 60:
                emotion = "bored"
            else:
                emotion = "calm"
        else:
            emotion = "calm"

        # --- 感情遷移のスムージング ---
        # 急激な変化を避ける（startled以外）
        if emotion != "startled" and emotion != self.current_emotion:
            # 同じ感情が2回連続で算出されたら遷移
            if self.history and self.history[-1] == emotion:
                self.current_emotion = emotion
            # 初回は記録だけ
        else:
            self.current_emotion = emotion

        # 履歴更新
        self.history.append(emotion)
        if len(self.history) > 10:
            self.history.pop(0)

        # valence/arousal更新
        emotion_data = EMOTIONS.get(self.current_emotion, EMOTIONS["calm"])
        # 緩やかに目標値に近づける
        self.valence += (emotion_data["valence"] - self.valence) * 0.3
        self.arousal += (emotion_data["arousal"] - self.arousal) * 0.3

        return self.get_state()

    def get_state(self):
        """現在の感情状態を返す"""
        emotion_data = EMOTIONS.get(self.current_emotion, EMOTIONS["calm"])
        return {
            "timestamp": time.time(),
            "emotion": self.current_emotion,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "color": emotion_data["color"],
            "description": self._describe(),
        }

    def _describe(self):
        """感情を自然言語で記述（プロンプト素材用）"""
        descriptions = {
            "curious": "curious and alert, warm golden light, gentle movement",
            "excited": "excited and energetic, bright sparkling particles, vivid colors",
            "calm": "calm and peaceful, soft blue ambient, gentle breathing",
            "anxious": "uncertain and wary, purple shadows, flickering edges",
            "happy": "joyful and warm, golden glow, soft radiance spreading",
            "lonely": "quiet solitude, deep indigo, distant echoes",
            "startled": "sharp surprise, red flash, distorted ripples",
            "bored": "drifting attention, grey mist, slow fading",
        }
        return descriptions.get(self.current_emotion, "neutral state")


if __name__ == "__main__":
    a = Affect()
    # テスト: 静止→移動→人発見→衝突
    print("=== Calm (idle) ===")
    print(json.dumps(a.update({"has_person": False, "object_count": 0}), indent=2))

    print("\n=== Curious (moving) ===")
    print(json.dumps(a.update({"has_person": False, "object_count": 2}, "running"), indent=2))

    print("\n=== Happy (person found) ===")
    print(json.dumps(a.update({"has_person": True, "object_count": 1}), indent=2))

    print("\n=== Startled (collision) ===")
    print(json.dumps(a.update({"has_person": False, "object_count": 0}, collision=True), indent=2))
