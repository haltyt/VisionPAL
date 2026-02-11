#!/usr/bin/env python3
"""Vision PAL - JetBot MQTT Motor Controller
MQTTでヘッドトラッキングコマンドを受信してモーター制御

Topics:
  vision_pal/move   - {"direction": "forward|left|right|stop", "speed": 0.0-1.0}
  vision_pal/status - JetBotステータス配信

Requires: paho-mqtt, Adafruit_MotorHAT
Run on JetBot: python3 mqtt_robot.py
"""
import json
import time
import signal
import sys
import paho.mqtt.client as mqtt
from Adafruit_MotorHAT import Adafruit_MotorHAT

# === 設定 ===
MQTT_BROKER = "192.168.3.5"  # Jetsonホスト
MQTT_PORT = 1883
TOPIC_MOVE = "vision_pal/move"
TOPIC_STATUS = "vision_pal/status"

# モーター設定（JetBot）
MOTOR_LEFT = 1
MOTOR_RIGHT = 2
BASE_SPEED = 150  # 0-255、通常速度
MAX_SPEED = 200

# === モーター初期化 ===
hat = Adafruit_MotorHAT(addr=0x60, i2c_bus=1)
motor_left = hat.getMotor(MOTOR_LEFT)
motor_right = hat.getMotor(MOTOR_RIGHT)


def stop():
    """モーター停止"""
    motor_left.run(Adafruit_MotorHAT.RELEASE)
    motor_right.run(Adafruit_MotorHAT.RELEASE)


def move(direction, speed=0.5):
    """方向と速度でモーター制御
    direction: forward, left, right, stop, backward
    speed: 0.0 - 1.0
    """
    motor_speed = int(BASE_SPEED + (MAX_SPEED - BASE_SPEED) * speed)
    motor_speed = min(motor_speed, MAX_SPEED)

    if direction == "stop":
        stop()
    elif direction == "forward":
        motor_left.setSpeed(motor_speed)
        motor_right.setSpeed(motor_speed)
        motor_left.run(Adafruit_MotorHAT.BACKWARD)
        motor_right.run(Adafruit_MotorHAT.BACKWARD)
    elif direction == "backward":
        motor_left.setSpeed(motor_speed)
        motor_right.setSpeed(motor_speed)
        motor_left.run(Adafruit_MotorHAT.FORWARD)
        motor_right.run(Adafruit_MotorHAT.FORWARD)
    elif direction == "left":
        motor_left.setSpeed(int(motor_speed * 0.3))
        motor_right.setSpeed(motor_speed)
        motor_left.run(Adafruit_MotorHAT.BACKWARD)
        motor_right.run(Adafruit_MotorHAT.BACKWARD)
    elif direction == "right":
        motor_left.setSpeed(motor_speed)
        motor_right.setSpeed(int(motor_speed * 0.3))
        motor_left.run(Adafruit_MotorHAT.BACKWARD)
        motor_right.run(Adafruit_MotorHAT.BACKWARD)
    else:
        print("[WARN] Unknown direction: {}".format(direction))
        stop()

    print("[MOVE] {} speed={:.1f} motor={}".format(direction, speed, motor_speed))


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected to broker!")
        client.subscribe(TOPIC_MOVE)
        print("[MQTT] Subscribed to {}".format(TOPIC_MOVE))
        # ステータス送信
        client.publish(TOPIC_STATUS, json.dumps({
            "status": "ready",
            "timestamp": time.time()
        }))
    else:
        print("[MQTT] Connection failed: rc={}".format(rc))


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        direction = payload.get("direction", "stop")
        speed = float(payload.get("speed", 0.5))
        speed = max(0.0, min(1.0, speed))
        move(direction, speed)
    except (json.JSONDecodeError, ValueError) as e:
        print("[ERROR] Bad payload: {} - {}".format(msg.payload, e))
        stop()


def cleanup(signum=None, frame=None):
    print("\n[EXIT] Stopping motors...")
    stop()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == "__main__":
    print("=" * 40)
    print("  Vision PAL - JetBot MQTT Controller")
    print("=" * 40)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("[MQTT] Connecting to {}:{}...".format(MQTT_BROKER, MQTT_PORT))
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        print("[ERROR] {}".format(e))
        cleanup()
