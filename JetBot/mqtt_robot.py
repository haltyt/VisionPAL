#!/usr/bin/env python3
"""Vision PAL - JetBot MQTT Motor Controller v3
Waveshare Motor Driver HAT (PCA9685 @ I2C 0x40)
Motor A (ch0,1,2) = RIGHT, Motor B (ch5,3,4) = LEFT

Topics:
  vision_pal/move   - {"direction": "forward|left|right|stop|backward", "speed": 0.0-1.0}
  vision_pal/status - JetBotステータス配信

Run on JetBot: python3 mqtt_robot.py
"""
import json
import time
import signal
import sys
import atexit

try:
    import smbus
except ImportError:
    import smbus2 as smbus

import paho.mqtt.client as mqtt

# === 設定 ===
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
TOPIC_MOVE = "vision_pal/move"
TOPIC_STATUS = "vision_pal/status"

# === PCA9685 ===
PCA9685_ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0_ON_L = 0x06

# Channel mapping (confirmed 2026-03-13)
CH_R = {'pwm': 0, 'in1': 1, 'in2': 2}  # Motor A = RIGHT
CH_L = {'pwm': 5, 'in1': 3, 'in2': 4}  # Motor B = LEFT

bus = smbus.SMBus(1)

# 衝突検知用状態ファイル
MOTOR_STATE_FILE = "/tmp/jetbot_motor_state"


def init_pca9685():
    bus.write_byte_data(PCA9685_ADDR, MODE1, 0x00)
    time.sleep(0.005)
    old_mode = bus.read_byte_data(PCA9685_ADDR, MODE1)
    bus.write_byte_data(PCA9685_ADDR, MODE1, (old_mode & 0x7F) | 0x10)
    bus.write_byte_data(PCA9685_ADDR, PRESCALE, 121)  # ~50Hz
    bus.write_byte_data(PCA9685_ADDR, MODE1, old_mode)
    time.sleep(0.005)
    bus.write_byte_data(PCA9685_ADDR, MODE1, old_mode | 0xA0)


def set_pwm(channel, on, off):
    reg = LED0_ON_L + 4 * channel
    bus.write_byte_data(PCA9685_ADDR, reg, on & 0xFF)
    bus.write_byte_data(PCA9685_ADDR, reg + 1, on >> 8)
    bus.write_byte_data(PCA9685_ADDR, reg + 2, off & 0xFF)
    bus.write_byte_data(PCA9685_ADDR, reg + 3, off >> 8)


def set_motor(ch, speed):
    """Drive one motor. speed: -1.0 to 1.0."""
    pwm_val = int(abs(speed) * 4095)
    pwm_val = min(pwm_val, 4095)
    if speed > 0:
        set_pwm(ch['in1'], 0, 4095)
        set_pwm(ch['in2'], 0, 0)
        set_pwm(ch['pwm'], 0, pwm_val)
    elif speed < 0:
        set_pwm(ch['in1'], 0, 0)
        set_pwm(ch['in2'], 0, 4095)
        set_pwm(ch['pwm'], 0, pwm_val)
    else:
        set_pwm(ch['in1'], 0, 0)
        set_pwm(ch['in2'], 0, 0)
        set_pwm(ch['pwm'], 0, 0)


def write_state(state):
    try:
        with open(MOTOR_STATE_FILE, "w") as f:
            f.write(state)
    except Exception:
        pass


def stop():
    set_motor(CH_L, 0)
    set_motor(CH_R, 0)
    write_state("stopped")


def move(direction, speed=0.5):
    speed = max(0.0, min(1.0, speed))
    if direction == "stop":
        stop()
    elif direction == "forward":
        set_motor(CH_L, speed)
        set_motor(CH_R, speed)
        write_state("running")
    elif direction == "backward":
        set_motor(CH_L, -speed)
        set_motor(CH_R, -speed)
        write_state("running")
    elif direction == "left":
        set_motor(CH_L, -speed)
        set_motor(CH_R, speed)
        write_state("running")
    elif direction == "right":
        set_motor(CH_L, speed)
        set_motor(CH_R, -speed)
        write_state("running")
    else:
        print("[WARN] Unknown direction: {}".format(direction))
        stop()
        return

    print("[MOVE] {} speed={:.2f}".format(direction, speed))


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected to broker!")
        client.subscribe(TOPIC_MOVE)
        print("[MQTT] Subscribed to {}".format(TOPIC_MOVE))
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
atexit.register(stop)

if __name__ == "__main__":
    print("=" * 40)
    print("  Vision PAL - MQTT Controller v3")
    print("  Waveshare HAT (PCA9685 @ 0x40)")
    print("=" * 40)

    init_pca9685()
    print("[OK] PCA9685 initialized")

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
