"""Vision PAL - Perception Module (MQTT版)
JetBot側のmjpeg_perception.pyが物体認識してMQTTに配信。
このモジュールはMQTTから受信した知覚データを保持・提供する。
"""
import json
import time
import threading

from config import TOPIC_PERCEPTION


class Perception:
    """パルの知覚モジュール（MQTT受信版）"""

    def __init__(self):
        self.last_data = {
            "timestamp": 0,
            "objects": [],
            "scene": "waiting for perception data",
            "object_count": 0,
            "has_person": False,
        }
        self._lock = threading.Lock()
        self._last_update = 0

    def on_mqtt_message(self, payload):
        """MQTTメッセージ受信時のコールバック"""
        try:
            data = json.loads(payload)
            with self._lock:
                self.last_data = data
                self._last_update = time.time()
        except (json.JSONDecodeError, TypeError) as e:
            print("[Perception] Parse error: {}".format(e))

    def get_perception_data(self):
        """最新の知覚データを返す"""
        with self._lock:
            data = dict(self.last_data)

        # データが古すぎたら（10秒以上）警告付き
        age = time.time() - self._last_update
        if self._last_update > 0 and age > 10:
            data["stale"] = True
            data["age"] = round(age, 1)

        # まだ一度も受信してない
        if self._last_update == 0:
            data["scene"] = "no perception yet, eyes closed"

        return data

    @property
    def is_active(self):
        """知覚データが新鮮かどうか"""
        return self._last_update > 0 and (time.time() - self._last_update) < 10

    @property
    def topic(self):
        """購読すべきMQTTトピック"""
        return TOPIC_PERCEPTION


if __name__ == "__main__":
    # テスト
    p = Perception()
    print("Initial:", json.dumps(p.get_perception_data(), indent=2))

    # 模擬受信
    p.on_mqtt_message(json.dumps({
        "timestamp": time.time(),
        "objects": [{"label": "person", "confidence": 0.85, "bbox": [10, 20, 200, 400]}],
        "scene": "a person nearby, clear sharp perception",
        "object_count": 1,
        "has_person": True,
    }))
    print("\nAfter update:", json.dumps(p.get_perception_data(), indent=2))
