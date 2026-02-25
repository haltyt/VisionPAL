#!/usr/bin/env python3
"""
JetBot 衝突検知 v2 — CNN予測型 (AsyncVLA Edge層)
ResNet18で「衝突しそう」を事前予測 + MQTT publish。
フレーム差分方式も残してハイブリッド判定。

Edge Adapter概念: 5-10msで高速判定 → 即座にモーター制御
Cloud層(VLM+Survival Engine)は別プロセスで5-10秒の戦略的判断

Usage:
    python3 collision_detect_v2.py
    python3 collision_detect_v2.py --model /path/to/best_model_resnet18.pth
    python3 collision_detect_v2.py --threshold 0.7 --no-motor
"""

import cv2
import numpy as np
import time
import subprocess
import sys
import json
import argparse
import signal

# Python 3.6 互換
try:
    import torch
    import torch.nn.functional as F
    import torchvision.transforms as transforms
    import torchvision.models as models
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    print("[WARN] PyTorch not found, falling back to frame-diff only")

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[WARN] paho-mqtt not found, MQTT disabled")


# ─── Config ─────────────────────────────────────────────
# CNN model
DEFAULT_MODEL_PATH = "/home/jetbot/best_model_resnet18.pth"
CNN_INPUT_SIZE = 224
CNN_THRESHOLD = 0.7      # blocked確率がこれ以上で回避

# Frame diff (フォールバック)
FRAMEDIFF_THRESHOLD = 1.0
FRAMEDIFF_FRAMES = 3

# Camera
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240
CHECK_INTERVAL = 0.05    # 50ms (20fps) — Edge層は高速に回す

# GStreamer (CSI camera)
GST_PIPELINE = (
    "nvarguscamerasrc ! "
    "video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1 ! "
    "nvvidconv ! video/x-raw,width={w},height={h},format=BGRx ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink drop=1"
)

# USB camera fallback
USB_CAMERA_ID = 0

# MQTT
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_EDGE = "vision_pal/edge/state"         # Edge層の連続状態
TOPIC_MOVE = "vision_pal/move"               # 緊急モーター制御
TOPIC_MOTOR_STATE = "vision_pal/motor/state"  # モーター状態監視

# Motor
MOTOR_STATE_FILE = "/tmp/jetbot_motor_state"

# ─── Globals ────────────────────────────────────────────
running = True

def signal_handler(sig, frame):
    global running
    print("\n[Edge] シャットダウン...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def log(msg):
    print(msg, flush=True)


# ─── Camera ─────────────────────────────────────────────
def open_camera(use_usb=False):
    """カメラを開く（CSI優先、USBフォールバック）"""
    if not use_usb:
        log("[Edge] CSIカメラ起動中...")
        gst = GST_PIPELINE.format(w=CAMERA_WIDTH, h=CAMERA_HEIGHT)
        cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            # ウォームアップ
            for _ in range(10):
                cap.read()
                time.sleep(0.05)
            log("[Edge] CSIカメラ起動OK")
            return cap
        log("[WARN] CSI開けない、USBフォールバック")

    log("[Edge] USBカメラ起動中...")
    cap = cv2.VideoCapture(USB_CAMERA_ID)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        log("[Edge] USBカメラ起動OK")
        return cap

    log("[ERROR] カメラ開けない！")
    sys.exit(1)


# ─── CNN Model ──────────────────────────────────────────
class CollisionCNN:
    """ResNet18ベースの衝突予測モデル"""

    def __init__(self, model_path, device="cuda"):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        log("[CNN] デバイス: {}".format(self.device))

        # ResNet18をロード（2クラス: free/blocked）
        self.model = models.resnet18(pretrained=False)
        self.model.fc = torch.nn.Linear(512, 2)

        # 学習済み重みロード
        state_dict = torch.load(model_path, map_location=self.device)
        self.model.load_state_dict(state_dict)
        self.model = self.model.to(self.device)
        self.model.eval()
        log("[CNN] モデルロード完了: {}".format(model_path))

        # 前処理（ImageNet正規化）
        self.transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((CNN_INPUT_SIZE, CNN_INPUT_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            ),
        ])

        # ウォームアップ推論
        dummy = torch.zeros(1, 3, CNN_INPUT_SIZE, CNN_INPUT_SIZE).to(self.device)
        with torch.no_grad():
            self.model(dummy)
        log("[CNN] ウォームアップ完了")

    def predict(self, frame_bgr):
        """
        フレームからblocked確率を予測
        Returns: (blocked_prob, free_prob, inference_ms)
        """
        t0 = time.time()

        # BGR → RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        tensor = self.transform(frame_rgb).unsqueeze(0).to(self.device)

        with torch.no_grad():
            output = self.model(tensor)
            probs = F.softmax(output, dim=1).cpu().numpy()[0]

        elapsed_ms = (time.time() - t0) * 1000

        # class 0 = blocked, class 1 = free (NVIDIA JetBot convention)
        blocked_prob = float(probs[0])
        free_prob = float(probs[1])

        return blocked_prob, free_prob, elapsed_ms


# ─── Frame Diff (フォールバック) ─────────────────────────
class FrameDiffDetector:
    """フレーム差分方式（CNNが使えない時のフォールバック）"""

    def __init__(self):
        self.prev_gray = None
        self.still_count = 0

    def update(self, frame):
        """
        Returns: (is_collision, diff_val)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None:
            self.prev_gray = gray
            return False, 0.0

        diff = cv2.absdiff(self.prev_gray, gray)
        diff_val = float(np.mean(diff))
        self.prev_gray = gray

        if diff_val < FRAMEDIFF_THRESHOLD:
            self.still_count += 1
        else:
            self.still_count = 0

        is_collision = self.still_count >= FRAMEDIFF_FRAMES
        if is_collision:
            self.still_count = 0  # リセット

        return is_collision, diff_val


# ─── Motor Control ──────────────────────────────────────
def emergency_stop():
    """緊急モーター停止"""
    try:
        from Adafruit_MotorHAT import Adafruit_MotorHAT
        mh = Adafruit_MotorHAT(addr=0x60, i2c_bus=1)
        mh.getMotor(1).run(Adafruit_MotorHAT.RELEASE)
        mh.getMotor(2).run(Adafruit_MotorHAT.RELEASE)
        log("[STOP] モーター緊急停止")
    except Exception as e:
        log("[WARN] モーター停止失敗: {}".format(e))


def play_alert():
    """アラート音再生"""
    try:
        subprocess.Popen(
            ["aplay", "-D", "plughw:2,0", "/tmp/beep.wav"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception:
        pass


def is_motor_running():
    """モーター動作中かチェック"""
    try:
        with open(MOTOR_STATE_FILE, "r") as f:
            return f.read().strip() == "running"
    except Exception:
        return False


# ─── Edge Layer Main ────────────────────────────────────
class EdgeLayer:
    """AsyncVLA Edge層 — 高速衝突予測＋即座回避"""

    def __init__(self, model_path=None, threshold=CNN_THRESHOLD,
                 use_motor=True, use_usb=False):
        self.threshold = threshold
        self.use_motor = use_motor

        # CNN
        self.cnn = None
        if HAS_TORCH and model_path:
            try:
                self.cnn = CollisionCNN(model_path)
            except Exception as e:
                log("[WARN] CNNロード失敗: {} → フレーム差分のみ".format(e))

        # フレーム差分（常にバックアップとして動作）
        self.frame_diff = FrameDiffDetector()

        # カメラ
        self.cap = open_camera(use_usb=use_usb)

        # MQTT
        self.mqtt = None
        self.mqtt_connected = False
        if HAS_MQTT:
            self._setup_mqtt()

        # 統計
        self.total_frames = 0
        self.collision_count = 0
        self.avg_inference_ms = 0
        self.cooldown_until = 0

        # 状態
        self.last_blocked_prob = 0.0
        self.last_free_prob = 1.0
        self.danger_zone = False  # blocked > 0.5 の警戒ゾーン

    def _setup_mqtt(self):
        try:
            try:
                self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "edge_layer")
            except (AttributeError, TypeError):
                self.mqtt = mqtt.Client("edge_layer")

            self.mqtt.on_connect = self._on_connect
            self.mqtt.on_disconnect = self._on_disconnect
            self.mqtt.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt.loop_start()
            log("[Edge] MQTT connecting...")
        except Exception as e:
            log("[Edge] MQTT error: {}".format(e))

    def _on_connect(self, *args):
        self.mqtt_connected = True
        log("[Edge] MQTT connected")

    def _on_disconnect(self, *args):
        self.mqtt_connected = False

    def _publish(self, topic, data):
        if self.mqtt and self.mqtt_connected:
            try:
                self.mqtt.publish(topic, json.dumps(data, ensure_ascii=False))
            except Exception:
                pass

    def process_frame(self, frame):
        """
        1フレーム処理 → 衝突判定 + MQTT publish
        Returns: dict with collision state
        """
        now = time.time()
        self.total_frames += 1
        result = {
            "timestamp": now,
            "frame": self.total_frames,
            "collision": False,
            "blocked_prob": 0.0,
            "free_prob": 1.0,
            "method": "none",
            "inference_ms": 0,
            "motor_running": is_motor_running(),
        }

        # ── CNN予測 ──
        if self.cnn:
            blocked, free, ms = self.cnn.predict(frame)
            result["blocked_prob"] = round(blocked, 4)
            result["free_prob"] = round(free, 4)
            result["inference_ms"] = round(ms, 1)
            result["method"] = "cnn"
            self.last_blocked_prob = blocked
            self.last_free_prob = free

            # 移動平均
            self.avg_inference_ms = self.avg_inference_ms * 0.9 + ms * 0.1

            # 警戒ゾーン
            self.danger_zone = blocked > 0.5

            # 衝突予測
            if blocked > self.threshold:
                result["collision"] = True
                result["severity"] = "predicted"

        # ── フレーム差分（バックアップ） ──
        fd_collision, diff_val = self.frame_diff.update(frame)
        result["frame_diff"] = round(diff_val, 2)

        if fd_collision and result["motor_running"]:
            result["collision"] = True
            if result["method"] == "none":
                result["method"] = "frame_diff"
            else:
                result["method"] = "cnn+frame_diff"
            result["severity"] = "detected"

        # ── 衝突対応 ──
        if result["collision"] and now > self.cooldown_until:
            self.collision_count += 1
            self.cooldown_until = now + 3.0  # 3秒クールダウン

            log("💥 衝突{} (method={}, blocked={:.2f}, diff={:.1f})".format(
                "予測！" if result.get("severity") == "predicted" else "検知！",
                result["method"],
                result["blocked_prob"],
                result.get("frame_diff", 0),
            ))

            # 緊急停止
            if self.use_motor:
                emergency_stop()
                play_alert()

            # MQTT: 衝突イベント
            self._publish(TOPIC_COLLISION, {
                "collision": True,
                "blocked_prob": result["blocked_prob"],
                "severity": result.get("severity", "unknown"),
                "method": result["method"],
                "timestamp": now,
            })

            # MQTT: 緊急停止コマンド
            self._publish(TOPIC_MOVE, {
                "action": "stop",
                "source": "edge_layer",
                "reason": "collision_{}".format(result.get("severity", "detected")),
            })

        # ── Edge状態を定期publish（10フレームごと）──
        if self.total_frames % 10 == 0:
            self._publish(TOPIC_EDGE, {
                "blocked_prob": result["blocked_prob"],
                "free_prob": result["free_prob"],
                "danger_zone": self.danger_zone,
                "inference_ms": result["inference_ms"],
                "avg_inference_ms": round(self.avg_inference_ms, 1),
                "total_frames": self.total_frames,
                "collisions": self.collision_count,
                "motor_running": result["motor_running"],
                "timestamp": now,
            })

        return result

    def run(self):
        """メインループ"""
        log("=" * 50)
        log("🛡️ AsyncVLA Edge Layer v2")
        log("=" * 50)
        log("  CNN: {}".format("ON" if self.cnn else "OFF (frame-diff only)"))
        log("  Threshold: {}".format(self.threshold))
        log("  Motor control: {}".format(self.use_motor))
        log("  MQTT: {}".format("ON" if self.mqtt_connected else "OFF"))
        log("  Check interval: {}ms".format(int(CHECK_INTERVAL * 1000)))
        log("=" * 50)

        global running
        last_log = 0

        try:
            while running:
                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                result = self.process_frame(frame)

                # 定期ログ（5秒ごと）
                now = time.time()
                if now - last_log > 5:
                    if self.cnn:
                        log("[Edge #{:>6d}] blocked={:.3f} free={:.3f} infer={:.1f}ms{}{}".format(
                            self.total_frames,
                            result["blocked_prob"],
                            result["free_prob"],
                            result["inference_ms"],
                            " ⚠️" if self.danger_zone else "",
                            " 🏃" if result["motor_running"] else "",
                        ))
                    else:
                        log("[Edge #{:>6d}] diff={:.2f}{}".format(
                            self.total_frames,
                            result.get("frame_diff", 0),
                            " 🏃" if result["motor_running"] else "",
                        ))
                    last_log = now

                time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log("[Edge] エラー: {}".format(e))
        finally:
            self.cap.release()
            if self.mqtt:
                self.mqtt.loop_stop()
                self.mqtt.disconnect()
            log("[Edge] 終了 (frames={}, collisions={})".format(
                self.total_frames, self.collision_count))


def main():
    parser = argparse.ArgumentParser(description="AsyncVLA Edge Layer v2")
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH,
                        help="ResNet18モデルパス")
    parser.add_argument("--threshold", type=float, default=CNN_THRESHOLD,
                        help="blocked確率閾値 (default: {})".format(CNN_THRESHOLD))
    parser.add_argument("--no-motor", action="store_true",
                        help="モーター制御無効")
    parser.add_argument("--usb", action="store_true",
                        help="USBカメラ使用")
    parser.add_argument("--no-cnn", action="store_true",
                        help="CNN無効（フレーム差分のみ）")
    args = parser.parse_args()

    model_path = None if args.no_cnn else args.model
    edge = EdgeLayer(
        model_path=model_path,
        threshold=args.threshold,
        use_motor=not args.no_motor,
        use_usb=args.usb,
    )
    edge.run()


if __name__ == "__main__":
    main()
