#!/usr/bin/env python3
"""Vision PAL - MJPEG Server + Perception (物体認識統合版)
mjpeg_light.pyベース + DNN物体認識 + MQTT配信

元のmjpeg_light.py / mjpeg_server.py はそのまま残してあります。

Usage:
  python3 mjpeg_perception.py              # 自動検出
  python3 mjpeg_perception.py --csi        # CSIカメラ強制
  python3 mjpeg_perception.py --no-mqtt    # MQTT無し（テスト用）

Endpoints:
  http://jetbot-ip:8554/        ビューワー
  http://jetbot-ip:8554/stream  MJPEGストリーム
  http://jetbot-ip:8554/snap    静止画1枚
  http://jetbot-ip:8554/perception  最新の認識結果JSON
  http://jetbot-ip:8554/status  ステータス

MQTT Topics:
  vision_pal/perception/objects  物体認識結果
"""
import cv2
import sys
import os
import time
import json
import argparse
import threading
import numpy as np
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from BaseHTTPServer import HTTPServer
    from BaseHTTPServer import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[WARN] paho-mqtt not installed, MQTT disabled")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# === 設定 ===
PORT = 8554
FPS = 15
PERCEPTION_INTERVAL = 2.0  # 物体認識の間隔（秒）

MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883
TOPIC_PERCEPTION = "vision_pal/perception/objects"

# DNN SSD モデル (顔検出 → 汎用物体検出に差し替え可能)
DNN_PROTOTXT = os.path.expanduser("~/models/deploy.prototxt")
DNN_MODEL = os.path.expanduser("~/models/res10_300x300_ssd_iter_140000.caffemodel")
DNN_CONFIDENCE = 0.2

# MobileNet SSD (VOC 20クラス) — あれば使う
MOBILENET_PROTOTXT = os.path.expanduser("~/models/MobileNetSSD_deploy.prototxt")
MOBILENET_MODEL = os.path.expanduser("~/models/MobileNetSSD_deploy.caffemodel")

MOBILENET_LABELS = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair",
    "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor"
]

# === グローバル状態 ===
current_frame = None
frame_lock = threading.Lock()
perception_result = {"objects": [], "scene": "", "timestamp": 0}
perception_lock = threading.Lock()
camera_info = {"type": "unknown", "resolution": ""}
mqtt_client = None


# === カメラ ===
def open_usb_camera(device=1, width=1280, height=720):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    ret, frame = cap.read()
    if not ret or frame is None:
        cap.release()
        return None
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    camera_info["type"] = "USB"
    camera_info["resolution"] = "{}x{}".format(actual_w, actual_h)
    print("[CAMERA] USB: /dev/video{} ({}x{})".format(device, actual_w, actual_h))
    return cap


def open_csi_camera(width=640, height=480):
    gst = (
        "nvarguscamerasrc ! "
        "video/x-raw(memory:NVMM),width={w},height={h},"
        "format=NV12,framerate=30/1 ! "
        "nvvidconv ! video/x-raw,format=BGRx ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=1".format(w=width, h=height)
    )
    cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    if not ret or frame is None:
        cap.release()
        return None
    camera_info["type"] = "CSI"
    camera_info["resolution"] = "{}x{}".format(width, height)
    print("[CAMERA] CSI ({}x{})".format(width, height))
    return cap


def auto_detect_camera():
    for dev in [1, 2, 3]:
        cap = open_usb_camera(device=dev)
        if cap:
            return cap
    cap = open_csi_camera()
    if cap:
        return cap
    cap = open_usb_camera(device=0)
    return cap


# === カメラスレッド ===
def camera_thread(cap):
    global current_frame
    interval = 1.0 / FPS
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(1)
            continue
        with frame_lock:
            current_frame = frame
        time.sleep(interval)


# === モデル読み込み（メインスレッドで実行） ===
dnn_net = None
dnn_model_type = None

def load_dnn_model():
    global dnn_net, dnn_model_type
    # 顔検出DNN (ResNet SSD) — 人検出に十分
    print("[PERCEPTION] Looking for face DNN: {} + {}".format(DNN_PROTOTXT, DNN_MODEL))
    print("[PERCEPTION] exists: {} + {}".format(os.path.exists(DNN_PROTOTXT), os.path.exists(DNN_MODEL)))
    if os.path.exists(DNN_PROTOTXT) and os.path.exists(DNN_MODEL):
        try:
            dnn_net = cv2.dnn.readNetFromCaffe(DNN_PROTOTXT, DNN_MODEL)
            dnn_model_type = "face"
            print("[PERCEPTION] Face DNN loaded OK")
            return
        except Exception as e:
            print("[PERCEPTION] Face DNN failed: {}".format(e))
    print("[PERCEPTION] No model available, perception disabled")


# === 物体認識スレッド ===
def perception_thread(use_mqtt=True):
    global perception_result, mqtt_client

    net = dnn_net
    model_type = dnn_model_type

    if net is None:
        print("[PERCEPTION] No model, thread exiting")
        return

    # MQTT接続
    if use_mqtt and HAS_MQTT:
        try:
            mqtt_client = mqtt.Client()
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
            print("[MQTT] Connected to {}:{}".format(MQTT_BROKER, MQTT_PORT))
        except Exception as e:
            print("[MQTT] Connection failed: {}".format(e))
            mqtt_client = None

    print("[PERCEPTION] Running every {:.1f}s".format(PERCEPTION_INTERVAL))

    frame_wait = 0
    while True:
        time.sleep(PERCEPTION_INTERVAL)

        with frame_lock:
            frame = current_frame
        if frame is None:
            frame_wait += 1
            if frame_wait % 5 == 1:
                print("[PERCEPTION] Waiting for frame... ({})".format(frame_wait), flush=True)
            continue
        frame_wait = 0

        try:
            h, w = frame.shape[:2]
            if model_type == "face":
                blob = cv2.dnn.blobFromImage(
                    cv2.resize(frame, (300, 300)), 1.0,
                    (300, 300), (104.0, 177.0, 123.0)
                )
            else:
                blob = cv2.dnn.blobFromImage(
                    cv2.resize(frame, (300, 300)), 0.007843,
                    (300, 300), 127.5
                )
            net.setInput(blob)
            detections = net.forward()

            objects = []
            for i in range(detections.shape[2]):
                confidence = float(detections[0, 0, i, 2])
                if confidence > DNN_CONFIDENCE:
                    idx = int(detections[0, 0, i, 1])
                    if model_type == "mobilenet":
                        label = MOBILENET_LABELS[idx] if idx < len(MOBILENET_LABELS) else "unknown"
                    else:
                        label = "person"  # 顔検出モデルは人のみ

                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    x1, y1, x2, y2 = box.astype("int")
                    objects.append({
                        "label": label,
                        "confidence": round(confidence, 3),
                        "bbox": [int(x1), int(y1), int(x2), int(y2)]
                    })

            # ログ
            if objects:
                print("[PERCEPTION] Detected: {}".format(
                    [(o["label"], o["confidence"]) for o in objects]), flush=True)

            # シーン記述
            scene = describe_scene(objects)

            result = {
                "timestamp": time.time(),
                "objects": objects,
                "scene": scene,
                "object_count": len(objects),
                "has_person": any(o["label"] == "person" for o in objects),
                "model": model_type,
            }

            with perception_lock:
                perception_result = result

            # MQTT publish
            if mqtt_client:
                try:
                    mqtt_client.publish(TOPIC_PERCEPTION, json.dumps(result))
                except Exception:
                    pass

        except Exception as e:
            print("[PERCEPTION] Error: {}".format(e))


def describe_scene(objects):
    """知覚データからシーン記述を生成"""
    if not objects:
        return "empty space, quiet, nothing detected"

    labels = [o["label"] for o in objects]
    unique = list(set(l for l in labels if l != "background"))

    parts = []
    person_count = labels.count("person")
    if person_count == 1:
        parts.append("a person nearby")
    elif person_count > 1:
        parts.append("{} people nearby".format(person_count))

    others = [l for l in unique if l != "person"]
    if others:
        parts.append(", ".join(others))

    if not parts:
        return "open space, ambient environment"

    avg_conf = sum(o["confidence"] for o in objects) / len(objects)
    if avg_conf < 0.4:
        parts.append("vague uncertain perception")
    elif avg_conf > 0.8:
        parts.append("clear sharp perception")

    return ", ".join(parts)


# === HTTPハンドラ ===
class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/stream', '/raw'):
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        frame = current_frame
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    ret, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if not ret:
                        continue
                    self.wfile.write(b"--jpgboundary\r\n")
                    self.wfile.write(b"Content-type: image/jpeg\r\n")
                    self.wfile.write("Content-length: {}\r\n\r\n".format(len(jpg)).encode())
                    self.wfile.write(jpg.tobytes())
                    self.wfile.write(b"\r\n")
                    time.sleep(1.0 / FPS)
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == '/snap':
            with frame_lock:
                frame = current_frame
            if frame is None:
                self.send_response(503)
                self.end_headers()
                return
            ret, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-type', 'image/jpeg')
            self.send_header('Content-length', str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg.tobytes())

        elif self.path == '/perception':
            with perception_lock:
                data = json.dumps(perception_result)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data.encode())

        elif self.path == '/status':
            with perception_lock:
                last_perception = perception_result.get("timestamp", 0)
            status = {
                "camera": camera_info["type"],
                "resolution": camera_info["resolution"],
                "fps": FPS,
                "hasFrame": current_frame is not None,
                "perception_interval": PERCEPTION_INTERVAL,
                "last_perception": last_perception,
                "mqtt": mqtt_client is not None,
            }
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())

        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Vision PAL - Umwelt Perception</title></head>
<body style="margin:0;background:#000;display:flex;flex-direction:column;align-items:center;height:100vh;color:#fff;font-family:sans-serif;">
<img src="/stream" style="max-width:100%%;max-height:70vh;">
<div id="info" style="margin:8px;font-size:14px;opacity:0.8;"></div>
<pre id="perception" style="color:#0f0;font-size:12px;max-width:90%%;overflow:auto;"></pre>
<script>
setInterval(function(){
  fetch('/perception').then(r=>r.json()).then(d=>{
    document.getElementById('perception').textContent=JSON.stringify(d,null,2);
    document.getElementById('info').textContent=d.scene||'...';
  });
},2000);
</script>
</body></html>"""
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


# === メイン ===
def _set_globals(fps_val, interval_val):
    global FPS, PERCEPTION_INTERVAL
    FPS = fps_val
    PERCEPTION_INTERVAL = interval_val


def main():
    parser = argparse.ArgumentParser(description='Vision PAL MJPEG + Perception Server')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--usb', action='store_true')
    group.add_argument('--csi', action='store_true')
    group.add_argument('--device', type=int)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--fps', type=int, default=FPS)
    parser.add_argument('--no-mqtt', action='store_true')
    parser.add_argument('--interval', type=float, default=PERCEPTION_INTERVAL,
                        help='Perception interval in seconds')
    args = parser.parse_args()

    _set_globals(args.fps, args.interval)

    print("=" * 50)
    print("  Vision PAL - Umwelt Perception Server")
    print("  MJPEG + DNN Object Detection + MQTT")
    print("=" * 50)

    cap = None
    if args.device is not None:
        cap = open_usb_camera(device=args.device, width=args.width, height=args.height)
    elif args.usb:
        for dev in [1, 2, 3, 0]:
            cap = open_usb_camera(device=dev, width=args.width, height=args.height)
            if cap:
                break
    elif args.csi:
        cap = open_csi_camera()
    else:
        cap = auto_detect_camera()

    if cap is None:
        print("[ERROR] No camera found!")
        sys.exit(1)

    # カメラスレッド
    cam_t = threading.Thread(target=camera_thread, args=(cap,), daemon=True)
    cam_t.start()
    time.sleep(1)

    # モデル読み込み（メインスレッドで）
    load_dnn_model()

    # 物体認識スレッド
    perc_t = threading.Thread(target=perception_thread, args=(not args.no_mqtt,), daemon=True)
    perc_t.start()

    # HTTPサーバー
    port = args.port
    print("[HTTP] Server on port {}".format(port))
    print("[HTTP] Endpoints: /stream /snap /perception /status")

    server = ThreadedHTTPServer(('0.0.0.0', port), MJPEGHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[EXIT] Server stopped.")
        if mqtt_client:
            mqtt_client.loop_stop()
        server.server_close()


if __name__ == "__main__":
    main()
