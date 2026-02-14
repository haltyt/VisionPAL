#!/usr/bin/env python3
"""Vision PAL - JetBot MJPEG Streaming Server
CSIカメラ / USBカメラ 両対応

Usage:
  python3 mjpeg_server.py              # 自動検出（USB優先）
  python3 mjpeg_server.py --usb        # USBカメラ強制
  python3 mjpeg_server.py --csi        # CSIカメラ強制
  python3 mjpeg_server.py --device 1   # デバイス番号指定

Endpoints:
  http://jetbot-ip:8554/        ビューワー
  http://jetbot-ip:8554/stream  MJPEGストリーム
  http://jetbot-ip:8554/snap    静止画1枚

Requires: OpenCV (pre-installed on JetBot)
"""
import cv2
import sys
import time
import argparse
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
frame_lock = threading.Lock()
camera_info = {"type": "unknown", "resolution": ""}


def open_usb_camera(device=1, width=1280, height=720):
    """USBカメラをMJPEGモードで開く（CPU負荷ほぼゼロ）"""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    # MJPEG出力を要求（カメラHWエンコード）
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # 実際に取得できたか確認
    ret, frame = cap.read()
    if not ret or frame is None:
        cap.release()
        return None
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    camera_info["type"] = "USB"
    camera_info["resolution"] = "{}x{}".format(actual_w, actual_h)
    print("[CAMERA] USB camera opened: /dev/video{} ({}x{})".format(device, actual_w, actual_h))
    return cap


def open_csi_camera(width=640, height=480):
    """CSIカメラをGStreamerで開く"""
    gst_pipeline = (
        "nvarguscamerasrc ! "
        "video/x-raw(memory:NVMM), width={w}, height={h}, "
        "format=NV12, framerate=30/1 ! "
        "nvvidconv ! "
        "video/x-raw, format=BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=1".format(w=width, h=height)
    )
    cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    if not ret or frame is None:
        cap.release()
        return None
    camera_info["type"] = "CSI"
    camera_info["resolution"] = "{}x{}".format(width, height)
    print("[CAMERA] CSI camera opened ({}x{})".format(width, height))
    return cap


def auto_detect_camera():
    """カメラ自動検出（USB優先）"""
    # まずUSBカメラを探す（/dev/video1〜3）
    for dev in [1, 2, 3]:
        cap = open_usb_camera(device=dev)
        if cap is not None:
            return cap
    # USBなければCSI
    cap = open_csi_camera()
    if cap is not None:
        return cap
    # /dev/video0もUSBの可能性
    cap = open_usb_camera(device=0)
    if cap is not None:
        return cap
    return None


def camera_thread(cap):
    """カメラキャプチャスレッド"""
    global current_frame
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

        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            import json
            status = json.dumps({
                "camera": camera_info["type"],
                "resolution": camera_info["resolution"],
                "fps": FPS,
                "hasFrame": current_frame is not None
            })
            self.wfile.write(status.encode())

        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Vision PAL - JetBot Camera</title></head>
<body style="margin:0; background:#000; display:flex; flex-direction:column; justify-content:center; align-items:center; height:100vh; color:#fff; font-family:sans-serif;">
    <img src="/stream" style="max-width:100%%; max-height:90vh;">
    <p style="margin-top:8px; opacity:0.6;">{type} {res} @ {fps}fps</p>
</body>
</html>""".format(type=camera_info["type"], res=camera_info["resolution"], fps=FPS)
            self.wfile.write(html.encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    global FPS

    parser = argparse.ArgumentParser(description='Vision PAL MJPEG Server')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--usb', action='store_true', help='Force USB camera')
    group.add_argument('--csi', action='store_true', help='Force CSI camera')
    group.add_argument('--device', type=int, help='Video device number')
    parser.add_argument('--width', type=int, default=1280, help='Width (USB, default: 1280)')
    parser.add_argument('--height', type=int, default=720, help='Height (USB, default: 720)')
    parser.add_argument('--port', type=int, default=PORT, help='HTTP port (default: 8554)')
    parser.add_argument('--fps', type=int, default=FPS, help='Target FPS (default: 15)')
    args = parser.parse_args()

    FPS = args.fps

    print("=" * 40)
    print("  Vision PAL - MJPEG Camera Server")
    print("=" * 40)

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

    # カメラスレッド起動
    cam_thread = threading.Thread(target=camera_thread, args=(cap,), daemon=True)
    cam_thread.start()
    time.sleep(1)

    port = args.port
    print("[HTTP] Starting server on port {}...".format(port))
    print("[HTTP] View at http://0.0.0.0:{}".format(port))
    print("[HTTP] Endpoints: /stream /snap /status")

    server = HTTPServer(('0.0.0.0', port), MJPEGHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[EXIT] Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
