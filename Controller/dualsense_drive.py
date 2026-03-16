#!/usr/bin/env python3
"""DualSense → MQTT JetBot操縦
Jetsonホストで実行。DualSenseの左スティックでJetBot操縦。

左スティック:
  上: 前進
  下: 後退
  左: 左旋回
  右: 右旋回

R2: スピードブースト
×ボタン: 緊急停止
○ボタン: 終了
"""
import struct
import json
import time
import sys
import binascii

import paho.mqtt.client as mqtt

# --- 設定 ---
JS_DEVICE = "/dev/input/js0"
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
MQTT_TOPIC = "vision_pal/move"

# スティック設定
DEADZONE = 5000       # スティック中央の不感帯
BASE_SPEED = 0.25      # 通常速度 (0.0-1.0)
BOOST_SPEED = 0.4     # ブースト速度
SEND_INTERVAL = 0.1   # MQTT送信間隔(秒)
HIDRAW_DEVICE = "/dev/hidraw1"  # DualSense hidraw

# DualSense (Linux HID) ボタン/軸マッピング
# 軸: 0=LX, 1=LY, 2=RX, 3=RY, 4=L2, 5=R2
# ボタン: 0=×, 1=○, 2=△, 3=□


def open_haptics():
    """DualSense hidrawを開く（振動用、USB: O_RDWR）"""
    try:
        import os
        fd = os.open(HIDRAW_DEVICE, os.O_RDWR)
        print("[HAPTICS] Opened %s (USB rdwr)" % HIDRAW_DEVICE)
        return fd
    except Exception as e:
        print("[HAPTICS] Failed: %s (try: sudo chmod 666 /dev/hidraw1)" % e)
        return None


def set_rumble(hf, right, left):
    """DualSense USB振動 (0-255)"""
    if hf is None:
        return
    try:
        import os
        buf = bytearray(48)
        buf[0] = 0x02
        buf[1] = 0xFF
        buf[2] = 0x01
        buf[3] = min(255, max(0, right))
        buf[4] = min(255, max(0, left))
        os.write(hf, bytes(buf))
    except Exception:
        pass


def main():
    # MQTT接続
    client = mqtt.Client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        print("[MQTT] Connected to %s:%d" % (MQTT_BROKER, MQTT_PORT))
    except Exception as e:
        print("[MQTT] Failed: %s" % e)
        sys.exit(1)

    # ジョイスティック
    try:
        js = open(JS_DEVICE, "rb")
        print("[JS] Opened %s" % JS_DEVICE)
    except Exception as e:
        print("[JS] Failed to open %s: %s" % (JS_DEVICE, e))
        sys.exit(1)

    # 状態
    axes = {}
    buttons = {}
    last_send = 0
    last_direction = "stop"
    running = True


    haptics = open_haptics()

    paused = False
    print("[DRIVE] Ready! Left stick to drive, × to stop, ○ to quit")
    print("[DRIVE] Base speed: %.0f%%, Boost (R2): %.0f%%" % (
        BASE_SPEED * 100, BOOST_SPEED * 100))

    try:
        while running:
            # jsイベント読み取り (8 bytes: time, value, type, number)
            event = js.read(8)
            if not event:
                continue

            t, value, etype, number = struct.unpack("IhBB", event)

            # 初期化イベントのマスクを外す
            etype &= ~0x80

            if etype == 1:  # ボタン
                buttons[number] = value
                if number == 1 and value == 1:  # × 押下(USB): トグル停止/再開
                    paused = not paused
                    if paused:
                        print("[STOP] Paused! Press × to resume")
                        client.publish(MQTT_TOPIC, json.dumps({
                            "direction": "stop", "speed": 0
                        }))
                        set_rumble(haptics, 0, 0)
                        last_direction = "stop"
                    else:
                        print("[RESUME] Resumed!")
                elif number == 2 and value == 1:  # ○ 押下(USB)
                    print("[QUIT] Bye!")
                    client.publish(MQTT_TOPIC, json.dumps({
                        "direction": "stop", "speed": 0
                    }))
                    running = False

            elif etype == 2:  # 軸
                axes[number] = value

            # 定期送信
            now = time.time()
            if now - last_send < SEND_INTERVAL:
                continue
            last_send = now

            # スティック値取得
            if paused:
                continue
            lx = axes.get(0, 0)  # 左右 (-32768 ~ 32767)
            ly = axes.get(1, 0)  # 上下 (-32768=上, 32767=下)
            r2 = axes.get(5, -32768)  # R2トリガー (-32768=離す, 32767=全押し)

            # スピード計算
            boost = (r2 + 32768) / 65535.0  # 0.0 ~ 1.0
            speed = BASE_SPEED + (BOOST_SPEED - BASE_SPEED) * boost

            # 方向判定（斜め移動対応）
            direction = "stop"
            left_speed = speed
            right_speed = speed

            if abs(ly) > DEADZONE or abs(lx) > DEADZONE:
                # スティック倒し量
                fx = lx / 32768.0  # -1(左) ~ +1(右)
                fy = -ly / 32768.0  # -1(後) ~ +1(前) ※Y軸反転

                # 差動操舵（タンク式）
                # 左右モーターの速度を独立制御
                left_speed = speed * max(-1.0, min(1.0, fy + fx))
                right_speed = speed * max(-1.0, min(1.0, fy - fx))

                # 方向ラベル（ログ用）
                if abs(fy) > 0.15 and abs(fx) > 0.15:
                    if fy > 0:
                        direction = "forward-left" if fx < 0 else "forward-right"
                    else:
                        direction = "backward-left" if fx < 0 else "backward-right"
                elif abs(fy) > abs(fx):
                    direction = "forward" if fy > 0 else "backward"
                else:
                    direction = "left" if fx < 0 else "right"

            # 速度連動ハプティクス
            motor_mag = max(abs(left_speed), abs(right_speed))
            rumble = int(motor_mag * 40)  # 0-200 (max 200で手が痺れない程度)
            rumble = min(40, max(0, rumble))
            if direction == "stop":
                rumble = 0
            set_rumble(haptics, rumble, rumble)

            # 変化があった時 or 動いてる時だけ送信
            if direction != last_direction or direction != "stop":
                msg = {
                    "direction": direction,
                    "speed": round(max(abs(left_speed), abs(right_speed)), 2),
                    "left_speed": round(left_speed, 2),
                    "right_speed": round(right_speed, 2)
                }
                client.publish(MQTT_TOPIC, json.dumps(msg))
                if direction != last_direction:
                    print("[DRIVE] %s (L=%.0f%% R=%.0f%% rumble=%d)" % (
                        direction, left_speed * 100, right_speed * 100, rumble))
                last_direction = direction

    except KeyboardInterrupt:
        print("\n[DRIVE] Ctrl+C")
    finally:
        set_rumble(haptics, 0, 0)
        client.publish(MQTT_TOPIC, json.dumps({"direction": "stop", "speed": 0}))
        time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
        js.close()
        if haptics:
            import os; os.close(haptics) if haptics else None
        print("[DRIVE] Stopped")


if __name__ == "__main__":
    main()
