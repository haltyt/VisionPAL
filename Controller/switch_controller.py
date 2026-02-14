#!/usr/bin/env python3
"""Vision PAL - Nintendo Switch Controller → MQTT
Switchコントローラー(Joy-Con/Pro)でJetBotを操縦

Usage:
  pip install pygame paho-mqtt
  python switch_controller.py
  python switch_controller.py --broker 192.168.3.5 --speed 0.6

Requires: Bluetooth接続済みのSwitchコントローラー
"""
import sys
import time
import json
import argparse

try:
    import pygame
except ImportError:
    print("ERROR: pygame not installed. Run: pip install pygame")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)


# デフォルト設定
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
MQTT_TOPIC = "vision_pal/move"

# スティック設定
DEADZONE = 0.15          # スティックの遊び
TURN_THRESHOLD = 0.3     # 旋回判定の閾値
POLL_INTERVAL = 0.05     # 50ms (20Hz)


def connect_mqtt(broker, port):
    """MQTTブローカーに接続"""
    client = mqtt.Client()
    try:
        client.connect(broker, port, 60)
        client.loop_start()
        print("[MQTT] Connected to {}:{}".format(broker, port))
        return client
    except Exception as e:
        print("[MQTT] Connection failed: {}".format(e))
        sys.exit(1)


def send_move(client, direction, speed=0.5):
    """MQTT移動コマンド送信"""
    payload = json.dumps({"direction": direction, "speed": speed})
    client.publish(MQTT_TOPIC, payload)


def main():
    parser = argparse.ArgumentParser(description="Switch Controller → JetBot MQTT")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker IP")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT port")
    parser.add_argument("--speed", type=float, default=0.5, help="Base speed (0.0-1.0)")
    parser.add_argument("--boost", type=float, default=0.8, help="Boost speed (0.0-1.0)")
    parser.add_argument("--list", action="store_true", help="List connected controllers")
    args = parser.parse_args()

    # pygame初期化
    pygame.init()
    pygame.joystick.init()

    joystick_count = pygame.joystick.get_count()
    if joystick_count == 0:
        print("[ERROR] No controller found!")
        print("  1. Bluetoothでコントローラーをペアリング")
        print("  2. Windowsの設定 → Bluetooth → コントローラーを接続")
        pygame.quit()
        sys.exit(1)

    # コントローラー一覧
    print("\n[CONTROLLER] Found {} controller(s):".format(joystick_count))
    for i in range(joystick_count):
        js = pygame.joystick.Joystick(i)
        js.init()
        print("  [{}] {} (axes:{}, buttons:{}, hats:{})".format(
            i, js.get_name(), js.get_numaxes(), js.get_numbuttons(), js.get_numhats()))

    if args.list:
        pygame.quit()
        return

    # 最初のコントローラーを使用
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    print("\n[CTRL] Using: {}".format(joystick.get_name()))

    # MQTT接続
    client = connect_mqtt(args.broker, args.port)

    print("\n" + "=" * 40)
    print("  Vision PAL - Switch Controller")
    print("=" * 40)
    print("  Left Stick : Move")
    print("  R/ZR       : Speed Boost")
    print("  B          : Emergency Stop")
    print("  A          : Snap Photo")
    print("  +          : Quit")
    print("=" * 40 + "\n")

    last_direction = "stop"
    running = True

    try:
        while running:
            pygame.event.pump()

            # スティック入力（左スティック）
            axis_x = joystick.get_axis(0)  # 左右
            axis_y = joystick.get_axis(1)  # 上下（上がマイナス）

            # ブーストボタン（R=7, ZR=9 は一般的なマッピング、コントローラーで異なる場合あり）
            boost = False
            for btn_id in [7, 9, 5, 10]:  # R, ZR候補
                if btn_id < joystick.get_numbuttons() and joystick.get_button(btn_id):
                    boost = True
                    break

            speed = args.boost if boost else args.speed

            # Bボタン（緊急停止）— 一般的にボタン1
            if joystick.get_numbuttons() > 1 and joystick.get_button(1):
                if last_direction != "stop":
                    send_move(client, "stop")
                    last_direction = "stop"
                    print("[STOP] Emergency stop!")
                time.sleep(POLL_INTERVAL)
                continue

            # Aボタン（スナップ）— 一般的にボタン0
            if joystick.get_numbuttons() > 0 and joystick.get_button(0):
                print("[SNAP] Photo request")
                client.publish("vision_pal/snap", "{}")
                time.sleep(0.3)  # デバウンス
                continue

            # +ボタン（終了）— 一般的にボタン6 or 9
            for quit_btn in [6, 9]:
                if quit_btn < joystick.get_numbuttons() and joystick.get_button(quit_btn):
                    running = False
                    break

            # HAT（十字キー）もサポート
            if joystick.get_numhats() > 0:
                hat = joystick.get_hat(0)
                if hat != (0, 0):
                    if hat[1] > 0:
                        direction = "forward"
                    elif hat[1] < 0:
                        direction = "backward"
                    elif hat[0] < 0:
                        direction = "left"
                    else:
                        direction = "right"
                    if direction != last_direction:
                        send_move(client, direction, speed)
                        last_direction = direction
                        print("[MOVE] {} speed={:.1f} (D-Pad)".format(direction, speed))
                    time.sleep(POLL_INTERVAL)
                    continue

            # スティック → 方向判定
            magnitude = (axis_x ** 2 + axis_y ** 2) ** 0.5

            if magnitude < DEADZONE:
                direction = "stop"
            elif abs(axis_y) > abs(axis_x):
                # 前後が優勢
                if axis_y < -DEADZONE:
                    direction = "forward"
                else:
                    direction = "backward"
            else:
                # 左右が優勢
                if axis_x < -TURN_THRESHOLD:
                    direction = "left"
                else:
                    direction = "right"

            # スティック倒し具合でスピード調整
            if direction != "stop":
                stick_speed = min(1.0, magnitude) * speed
                stick_speed = max(0.2, stick_speed)  # 最低速度
            else:
                stick_speed = 0

            if direction != last_direction:
                send_move(client, direction, stick_speed if direction != "stop" else 0)
                last_direction = direction
                if direction != "stop":
                    print("[MOVE] {} speed={:.2f} (stick x={:.2f} y={:.2f})".format(
                        direction, stick_speed, axis_x, axis_y))
                else:
                    print("[STOP]")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        send_move(client, "stop")
        print("\n[EXIT] Stopped.")
        client.disconnect()
        pygame.quit()


if __name__ == "__main__":
    main()
