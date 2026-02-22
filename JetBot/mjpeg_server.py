#!/usr/bin/env python3
"""Vision PAL - JetBot MJPEG Streaming Server with Toon Filter
CSIカメラからアニメ風フィルタ付きMJPEGストリーム配信

http://jetbot-ip:8554/stream  - トゥーンフィルタ
http://jetbot-ip:8554/raw     - 生映像
http://jetbot-ip:8554/        - ビューアページ

Requires: OpenCV (pre-installed on JetBot)
Run on JetBot: python3 mjpeg_server.py
"""
import cv2
import numpy as np
import time
import threading
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from BaseHTTPServer import HTTPServer
    from BaseHTTPServer import BaseHTTPRequestHandler

PORT = 8554
FPS = 15

# グローバルフレーム
current_frame = None
toon_frame = None
frame_lock = threading.Lock()


def toon_filter(frame):
    """アニメ風トゥーンフィルタ
    1. バイラテラルフィルタで平坦化（アニメ塗り）
    2. 色量子化（減色）
    3. エッジ検出で輪郭線
    4. 輪郭線を合成
    """
    # 1. バイラテラルフィルタ（エッジ保持しつつ平坦化）
    # 複数回かけるとよりアニメっぽく
    smooth = frame
    for _ in range(3):
        smooth = cv2.bilateralFilter(smooth, 9, 75, 75)

    # 2. 色量子化（8段階に減色）
    div = 32
    quantized = (smooth // div) * div + div // 2

    # 3. エッジ検出（太めの輪郭線）
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    edges = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY,
        blockSize=9,
        C=2
    )

    # 4. エッジをカラー化して合成
    edges_color = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    toon = cv2.bitwise_and(quantized, edges_color)

    # 彩度ブースト（アニメっぽい鮮やかさ）
    hsv = cv2.cvtColor(toon, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.4, 0, 255).astype(np.uint8)
    toon = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    return toon


def camera_thread():
    """GStreamerでCSIカメラキャプチャ + トゥーンフィルタ適用"""
    global current_frame, toon_frame

    gst_pipeline = (
        "nvarguscamerasrc ! "
        "video/x-raw(memory:NVMM), width=640, height=480, "
        "format=NV12, framerate=30/1 ! "
        "nvvidconv ! "
        "video/x-raw, format=BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=1"
    )

    cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("[ERROR] Camera open failed!")
        return

    print("[CAMERA] Opened CSI camera")
    frame_interval = 1.0 / FPS

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[CAMERA] Frame read failed, retrying...")
            time.sleep(1)
            continue

        # トゥーンフィルタ適用
        filtered = toon_filter(frame)

        with frame_lock:
            current_frame = frame
            toon_frame = filtered

        time.sleep(frame_interval)

    cap.release()


class MJPEGHandler(BaseHTTPRequestHandler):
    def _stream(self, use_toon=True):
        self.send_response(200)
        self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
        self.end_headers()

        try:
            while True:
                with frame_lock:
                    frame = toon_frame if use_toon else current_frame

                if frame is None:
                    time.sleep(0.1)
                    continue

                ret, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ret:
                    continue

                self.wfile.write(b"--jpgboundary\r\n")
                self.wfile.write(b"Content-type: image/jpeg\r\n")
                self.wfile.write("Content-length: {}\r\n\r\n".format(len(jpg)).encode())
                self.wfile.write(jpg.tobytes())
                self.wfile.write(b"\r\n")

                time.sleep(1.0 / FPS)
        except (BrokenPipeError, ConnectionResetError, IOError):
            pass

    def do_GET(self):
        if self.path == '/stream':
            self._stream(use_toon=True)
        elif self.path == '/raw':
            self._stream(use_toon=False)
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Vision PAL - JetBot Camera</title>
<style>
body { margin:0; background:#111; color:#fff; font-family:sans-serif; text-align:center; }
.container { display:flex; justify-content:center; gap:20px; padding:20px; flex-wrap:wrap; }
.feed { display:flex; flex-direction:column; align-items:center; }
.feed img { border-radius:12px; max-width:640px; }
.feed h2 { margin:10px 0; }
h1 { padding:20px 0 0; }
</style>
</head>
<body>
<h1>Vision PAL Camera</h1>
<div class="container">
  <div class="feed">
    <h2>Toon Filter</h2>
    <img src="/stream">
  </div>
  <div class="feed">
    <h2>Raw</h2>
    <img src="/raw">
  </div>
</div>
</body>
</html>"""
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print("=" * 40)
    print("  Vision PAL - Toon Camera Server")
    print("=" * 40)

    cam_thread = threading.Thread(target=camera_thread, daemon=True)
    cam_thread.start()
    time.sleep(2)

    print("[HTTP] Starting server on port {}...".format(PORT))
    print("[HTTP] Toon:  http://192.168.3.8:{}/stream".format(PORT))
    print("[HTTP] Raw:   http://192.168.3.8:{}/raw".format(PORT))
    print("[HTTP] View:  http://192.168.3.8:{}/".format(PORT))

    server = HTTPServer(('0.0.0.0', PORT), MJPEGHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[EXIT] Server stopped.")
        server.server_close()
