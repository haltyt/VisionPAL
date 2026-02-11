#!/usr/bin/env python3
"""Vision PAL - JetBot MJPEG Streaming Server
CSIカメラからMJPEGストリーム配信

http://jetbot-ip:8554/stream でブラウザから視聴可能

Requires: OpenCV (pre-installed on JetBot)
Run on JetBot: python3 mjpeg_server.py
"""
import cv2
import time
import threading
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from BaseHTTPServer import HTTPServer
    from BaseHTTPServer import BaseHTTPRequestHandler

PORT = 8554
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
FPS = 15

# グローバルフレーム
current_frame = None
frame_lock = threading.Lock()


def camera_thread():
    """GStreamerでCSIカメラキャプチャ"""
    global current_frame
    
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
        
        with frame_lock:
            current_frame = frame
        
        time.sleep(frame_interval)
    
    cap.release()


class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream':
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
        
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Vision PAL - JetBot Camera</title></head>
<body style="margin:0; background:#000; display:flex; justify-content:center; align-items:center; height:100vh;">
    <img src="/stream" style="max-width:100%; max-height:100vh;">
</body>
</html>"""
            self.wfile.write(html.encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # アクセスログ抑制
        pass


if __name__ == "__main__":
    print("=" * 40)
    print("  Vision PAL - MJPEG Camera Server")
    print("=" * 40)
    
    # カメラスレッド起動
    cam_thread = threading.Thread(target=camera_thread, daemon=True)
    cam_thread.start()
    time.sleep(2)  # カメラ初期化待ち
    
    print("[HTTP] Starting server on port {}...".format(PORT))
    print("[HTTP] View at http://192.168.3.8:{}".format(PORT))
    
    server = HTTPServer(('0.0.0.0', PORT), MJPEGHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[EXIT] Server stopped.")
        server.server_close()
