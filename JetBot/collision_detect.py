#!/usr/bin/env python3
"""
JetBot 衝突検知 - MJPEG経由カメラフレーム差分方式
モーター動作中に映像変化が止まったら衝突と判定
衝突イベントをMQTT publishする
Python 3.6対応
"""

import cv2
import numpy as np
import time
import subprocess
import sys
import json

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

# --- 設定 ---
COLLISION_THRESHOLD = 1.0
COLLISION_FRAMES = 3
CHECK_INTERVAL = 0.1
MJPEG_URL = "http://127.0.0.1:8554/raw"
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
MQTT_TOPIC = "vision_pal/perception/collision"

MOTOR_STATE_FILE = "/tmp/jetbot_motor_state"


def log(msg):
    print(msg, flush=True)


def setup_mqtt():
    if not HAS_MQTT:
        log("[WARN] paho-mqtt not installed, MQTT disabled")
        return None
    try:
        client = mqtt.Client("jetbot_collision")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        log("[OK] MQTT connected to {}:{}".format(MQTT_BROKER, MQTT_PORT))
        return client
    except Exception as e:
        log("[WARN] MQTT connection failed: {}".format(e))
        return None


def open_camera():
    log("[INFO] MJPEG接続中... {}".format(MJPEG_URL))
    cap = cv2.VideoCapture(MJPEG_URL)
    if not cap.isOpened():
        log("[ERROR] MJPEG開けない！mjpeg_light.py起動してる？")
        sys.exit(1)
    # ウォームアップ
    for i in range(5):
        ret, _ = cap.read()
        if i == 0:
            log("[INFO] 最初のread: ret={}".format(ret))
        time.sleep(0.05)
    log("[OK] カメラ接続完了")
    return cap


def frame_diff(prev_gray, curr_gray):
    diff = cv2.absdiff(prev_gray, curr_gray)
    return np.mean(diff)


def on_collision(mqtt_client, diff_val):
    log("💥 衝突検知！！！")
    # モーター停止
    try:
        from Adafruit_MotorHAT import Adafruit_MotorHAT
        mh = Adafruit_MotorHAT(addr=0x60, i2c_bus=1)
        mh.getMotor(1).run(Adafruit_MotorHAT.RELEASE)
        mh.getMotor(2).run(Adafruit_MotorHAT.RELEASE)
        log("[STOP] モーター停止")
    except Exception as e:
        log("[WARN] モーター停止失敗: {}".format(e))

    # MQTT publish
    if mqtt_client:
        payload = json.dumps({
            "collision": True,
            "diff": round(diff_val, 3),
            "timestamp": time.time()
        })
        mqtt_client.publish(MQTT_TOPIC, payload)
        log("[MQTT] collision published")

    # ブザー音
    try:
        subprocess.Popen(
            ["aplay", "-D", "plughw:2,0", "/tmp/beep.wav"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception:
        pass


def is_motor_running():
    try:
        with open(MOTOR_STATE_FILE, "r") as f:
            return f.read().strip() == "running"
    except Exception:
        pass
    try:
        result = subprocess.Popen(
            ["pgrep", "-f", "jetbot_control"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out, _ = result.communicate()
        return len(out.strip()) > 0
    except Exception:
        return False


def main():
    log("=== JetBot 衝突検知スタート (MJPEG版) ===")
    log("閾値: {}, 連続フレーム: {}".format(COLLISION_THRESHOLD, COLLISION_FRAMES))

    mqtt_client = setup_mqtt()
    cap = open_camera()

    ret, frame = cap.read()
    if not ret:
        log("[ERROR] 最初のフレーム取得失敗")
        return

    prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.resize(prev_gray, (320, 240))
    still_count = 0
    collision_cooldown = 0

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            ret, frame = cap.read()
            if not ret:
                # MJPEG再接続
                log("[WARN] フレーム取得失敗、再接続...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(MJPEG_URL)
                continue

            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.resize(curr_gray, (320, 240))
            diff_val = frame_diff(prev_gray, curr_gray)
            prev_gray = curr_gray

            if collision_cooldown > 0:
                collision_cooldown -= 1
                continue

            if not is_motor_running():
                still_count = 0
                continue

            if diff_val < COLLISION_THRESHOLD:
                still_count += 1
                log("  静止検知 ({}/{}) diff={:.2f}".format(
                    still_count, COLLISION_FRAMES, diff_val))
            else:
                if still_count > 0:
                    log("  動き復帰 diff={:.2f}".format(diff_val))
                still_count = 0

            if still_count >= COLLISION_FRAMES:
                on_collision(mqtt_client, diff_val)
                still_count = 0
                collision_cooldown = 30

    except KeyboardInterrupt:
        log("\n終了")
    finally:
        cap.release()
        if mqtt_client:
            mqtt_client.loop_stop()


if __name__ == "__main__":
    main()
