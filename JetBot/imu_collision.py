#!/usr/bin/env python3
"""IMU衝突検知 + 自動停止 (MPU-6050)
JetBot用。加速度の急変を検出してモーター停止＋MQTT通知。
I2Cバス排他制御付き。Python 3.6対応。
"""
import smbus2
import time
import math
import json
import sys
import threading

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[WARN] paho-mqtt not found, MQTT disabled")

# --- 設定 ---
I2C_BUS = 1
MPU_ADDR = 0x68
PCA9685_ADDR = 0x40
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
MQTT_TOPIC_COLLISION = "vision_pal/perception/collision"
MQTT_TOPIC_CONTROL = "vision_pal/control/jetbot"

# 衝突検知パラメータ
IMPACT_THRESHOLD = 1.2    # 加速度変化量(g) - 少し下げて感度UP
TILT_THRESHOLD = 45.0     # 傾き(度)
SAMPLE_RATE = 50          # Hz
COOLDOWN = 1.0            # 衝突検知後のクールダウン(秒)
AUTO_STOP = True          # 衝突時自動停止

# I2Cロック（モーターとIMUの排他制御）
i2c_lock = threading.Lock()


def init_mpu(bus):
    """MPU-6050を初期化"""
    with i2c_lock:
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00)
        time.sleep(0.1)
        bus.write_byte_data(MPU_ADDR, 0x1C, 0x08)  # +-4g
        bus.write_byte_data(MPU_ADDR, 0x1B, 0x08)  # +-500dps
        bus.write_byte_data(MPU_ADDR, 0x1A, 0x03)  # DLPF 44Hz


def read_word(bus, reg):
    h = bus.read_byte_data(MPU_ADDR, reg)
    l = bus.read_byte_data(MPU_ADDR, reg + 1)
    val = (h << 8) + l
    return val - 65536 if val >= 0x8000 else val


def read_accel(bus):
    with i2c_lock:
        ax = read_word(bus, 0x3B) / 8192.0
        ay = read_word(bus, 0x3D) / 8192.0
        az = read_word(bus, 0x3F) / 8192.0
    return ax, ay, az


def read_gyro(bus):
    with i2c_lock:
        gx = read_word(bus, 0x43) / 65.5
        gy = read_word(bus, 0x45) / 65.5
        gz = read_word(bus, 0x47) / 65.5
    return gx, gy, gz


def emergency_stop(bus):
    """モーター緊急停止（PCA9685の全チャンネルをOFF）"""
    try:
        with i2c_lock:
            # ALL_LED_OFF_H bit 4 = full off
            bus.write_byte_data(PCA9685_ADDR, 0xFD, 0x10)
        print("[STOP] Emergency motor stop!")
        return True
    except Exception as e:
        print("[STOP] Failed: %s" % e)
        return False


def accel_magnitude(ax, ay, az):
    return math.sqrt(ax * ax + ay * ay + az * az)


def tilt_angle(ax, ay, az):
    mag = accel_magnitude(ax, ay, az)
    if mag < 0.01:
        return 0.0
    cos_angle = abs(az) / mag
    cos_angle = min(1.0, max(-1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def on_mqtt_message(client, userdata, msg):
    """MQTT制御コマンド受信"""
    try:
        data = json.loads(msg.payload.decode())
        if data.get("command") == "stop":
            emergency_stop(userdata["bus"])
    except Exception:
        pass


def main():
    bus = smbus2.SMBus(I2C_BUS)
    init_mpu(bus)
    print("[IMU] MPU-6050 initialized (+-4g, +-500dps, DLPF 44Hz)")
    print("[IMU] Auto-stop: %s" % ("ON" if AUTO_STOP else "OFF"))

    # MQTT
    mqtt_client = None
    if HAS_MQTT:
        try:
            mqtt_client = mqtt.Client()
            mqtt_client.user_data_set({"bus": bus})
            mqtt_client.on_message = on_mqtt_message
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.subscribe(MQTT_TOPIC_CONTROL)
            mqtt_client.loop_start()
            print("[MQTT] Connected to %s:%d" % (MQTT_BROKER, MQTT_PORT))
        except Exception as e:
            print("[MQTT] Connection failed: %s" % e)
            mqtt_client = None

    # 初期読み取り（安定化）
    for _ in range(10):
        read_accel(bus)
        time.sleep(0.02)

    prev_ax, prev_ay, prev_az = read_accel(bus)
    prev_mag = accel_magnitude(prev_ax, prev_ay, prev_az)
    last_event_time = 0
    dt = 1.0 / SAMPLE_RATE
    collision_count = 0
    stopped = False

    print("[IMU] Monitoring... (impact=%.1fg, tilt=%d deg)" % (
        IMPACT_THRESHOLD, TILT_THRESHOLD))

    try:
        while True:
            try:
                ax, ay, az = read_accel(bus)
                gx, gy, gz = read_gyro(bus)
            except OSError:
                time.sleep(0.05)
                continue

            mag = accel_magnitude(ax, ay, az)
            now = time.time()
            delta = abs(mag - prev_mag)
            tilt = tilt_angle(ax, ay, az)

            event = None

            # 衝突検知
            if delta > IMPACT_THRESHOLD and (now - last_event_time) > COOLDOWN:
                collision_count += 1
                severity = "hard" if delta > 3.0 else "medium" if delta > 2.0 else "light"
                event = {
                    "type": "collision",
                    "severity": severity,
                    "delta_g": round(delta, 2),
                    "accel": {"x": round(ax, 2), "y": round(ay, 2), "z": round(az, 2)},
                    "gyro": {"x": round(gx, 1), "y": round(gy, 1), "z": round(gz, 1)},
                    "tilt_deg": round(tilt, 1),
                    "count": collision_count,
                    "timestamp": now
                }
                last_event_time = now
                print("[COLLISION #%d] %s (delta=%.2fg, tilt=%.1f)" % (
                    collision_count, severity, delta, tilt))

                # 自動停止
                if AUTO_STOP and not stopped:
                    emergency_stop(bus)
                    stopped = True

            # 転倒検知
            elif tilt > TILT_THRESHOLD and (now - last_event_time) > COOLDOWN:
                event = {
                    "type": "tilt",
                    "tilt_deg": round(tilt, 1),
                    "accel": {"x": round(ax, 2), "y": round(ay, 2), "z": round(az, 2)},
                    "timestamp": now
                }
                last_event_time = now
                print("[TILT] %.1f deg" % tilt)
                if AUTO_STOP and not stopped:
                    emergency_stop(bus)
                    stopped = True

            # 安定したらstoppedリセット
            if stopped and delta < 0.3 and tilt < 20:
                stopped = False

            # MQTT publish
            if event and mqtt_client:
                try:
                    mqtt_client.publish(MQTT_TOPIC_COLLISION, json.dumps(event))
                except Exception as e:
                    print("[MQTT] Publish error: %s" % e)

            prev_mag = mag
            time.sleep(dt)

    except KeyboardInterrupt:
        print("\n[IMU] Stopped. Total collisions: %d" % collision_count)
    finally:
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        bus.close()


if __name__ == "__main__":
    main()
