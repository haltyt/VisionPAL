#!/usr/bin/env python3
"""Vision PAL - Body Sensor (JetBot側)
JetBotの「身体」信号をMQTTにpublishする。
Python 3.6互換（Jetson Nano / JetBot）。

身体信号:
  - cpu_temp: CPU温度 (℃)
  - disk_percent: ディスク使用率 (%)
  - memory_percent: メモリ使用率 (%)
  - uptime_sec: 起動からの秒数
  - voltage: INA219電圧 (V) ※ハードウェアがあれば
  - motor_active: モーターが動いているか
  - last_collision: 最後の衝突からの秒数
  - idle_sec: 最後にモーター動かしてからの秒数
"""
import json
import os
import subprocess
import time
import threading

# paho-mqtt v1/v2 互換
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[BodySensor] paho-mqtt not found! pip3 install --user paho-mqtt")
    raise

# --- 設定 ---
MQTT_BROKER = os.environ.get("MQTT_BROKER", "192.168.3.5")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
TOPIC_BODY = "vision_pal/body/state"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_MOVE = "vision_pal/move"
PUBLISH_INTERVAL = 3.0  # 秒


class BodySensor:
    def __init__(self):
        self.motor_active = False
        self.motor_last_active = 0
        self.last_collision_time = 0
        self.boot_time = time.time()

        # MQTT
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "body_sensor")
        except (AttributeError, TypeError):
            self.client = mqtt.Client("body_sensor")
        self.client.on_connect = self._on_connect
        self.connected = False

    def _on_connect(self, *args):
        self.connected = True
        print("[BodySensor] MQTT connected")
        # モーター・衝突トピックを購読して状態追跡
        client = args[0] if args else self.client
        client.subscribe(TOPIC_COLLISION)
        client.subscribe(TOPIC_MOVE)
        client.message_callback_add(TOPIC_COLLISION, self._on_collision)
        client.message_callback_add(TOPIC_MOVE, self._on_move)

    def _on_collision(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            if data.get("collision"):
                self.last_collision_time = time.time()
                print("[BodySensor] 💥 collision detected")
        except Exception:
            pass

    def _on_move(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            direction = data.get("direction", "stop")
            if direction != "stop":
                self.motor_active = True
                self.motor_last_active = time.time()
            else:
                self.motor_active = False
        except Exception:
            pass

    def get_cpu_temp(self):
        """CPU温度を取得 (Jetson/JetBot)"""
        try:
            # Jetson thermal zone
            for zone in ["/sys/devices/virtual/thermal/thermal_zone0/temp",
                         "/sys/class/thermal/thermal_zone0/temp"]:
                if os.path.exists(zone):
                    with open(zone) as f:
                        return int(f.read().strip()) / 1000.0
        except Exception:
            pass
        return -1

    def get_disk_percent(self):
        try:
            st = os.statvfs("/")
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            total = st.f_blocks * st.f_frsize
            return round(used / total * 100, 1) if total > 0 else -1
        except Exception:
            return -1

    def get_memory_percent(self):
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 1)
            avail = info.get("MemAvailable", info.get("MemFree", 0))
            return round((1 - avail / total) * 100, 1)
        except Exception:
            return -1

    def get_voltage(self):
        """INA219バス電圧 (V) — ハードウェアがあれば"""
        try:
            from ina219 import INA219
            ina = INA219(0.1)
            ina.configure()
            return round(ina.voltage(), 2)
        except Exception:
            return -1

    def read_body(self):
        """身体状態を読み取る"""
        now = time.time()
        idle_sec = now - self.motor_last_active if self.motor_last_active > 0 else now - self.boot_time
        collision_ago = now - self.last_collision_time if self.last_collision_time > 0 else -1

        return {
            "timestamp": now,
            "cpu_temp": self.get_cpu_temp(),
            "disk_percent": self.get_disk_percent(),
            "memory_percent": self.get_memory_percent(),
            "voltage": self.get_voltage(),
            "motor_active": self.motor_active,
            "idle_sec": round(idle_sec, 1),
            "collision_ago_sec": round(collision_ago, 1),
            "uptime_sec": round(now - self.boot_time, 1),
        }

    def run(self, interval=None):
        interval = interval or PUBLISH_INTERVAL
        print("[BodySensor] Starting (broker={}:{}, interval={}s)".format(
            MQTT_BROKER, MQTT_PORT, interval))

        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

        # 接続待ち
        for _ in range(10):
            if self.connected:
                break
            time.sleep(0.5)

        try:
            while True:
                body = self.read_body()
                if self.connected:
                    payload = json.dumps(body, ensure_ascii=False)
                    self.client.publish(TOPIC_BODY, payload)

                # ログ（30秒ごと）
                if int(body["uptime_sec"]) % 30 < interval:
                    print("[BodySensor] temp={:.1f}℃ disk={:.0f}% mem={:.0f}% idle={:.0f}s motor={}".format(
                        body["cpu_temp"], body["disk_percent"], body["memory_percent"],
                        body["idle_sec"], body["motor_active"]))

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[BodySensor] Stopped")
        finally:
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PAL Body Sensor")
    parser.add_argument("--interval", type=float, default=PUBLISH_INTERVAL,
                        help="Publish interval (seconds)")
    args = parser.parse_args()
    BodySensor().run(interval=args.interval)
