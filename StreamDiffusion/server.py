#!/usr/bin/env python3
"""Vision PAL - StreamDiffusion API Server
JetBotカメラ映像をリアルタイムでAI画風変換して配信

Endpoints:
  POST /transform     - 1フレーム変換（JPEG in → JPEG out）
  GET  /stream        - MJPEG変換ストリーム（JetBotのMJPEGを変換して再配信）
  GET  /style         - 現在のスタイル取得
  POST /style         - スタイル変更 {"prompt": "...", "strength": 0.0-1.0}
  GET  /health        - ヘルスチェック
  GET  /              - ビューアページ

Usage:
  pip install -r requirements.txt
  python server.py --host 0.0.0.0 --port 8555

Requires: NVIDIA GPU (RTX 2060+), CUDA 11.8+
"""
import argparse
import io
import time
import threading
import json
import numpy as np
from PIL import Image

from flask import Flask, request, Response, jsonify, send_from_directory

# StreamDiffusion imports (lazy load)
stream_pipe = None
current_prompt = "anime style, studio ghibli, warm colors, hand-painted"
current_strength = 0.65
device = "cuda"

app = Flask(__name__)

# === StreamDiffusion Pipeline ===

def init_pipeline(model_id="KBlueLeaf/kohaku-v2.1", t_index_list=[32]):
    """StreamDiffusionパイプライン初期化"""
    global stream_pipe
    
    try:
        from streamdiffusion import StreamDiffusion
        from streamdiffusion.image_utils import postprocess_image
        
        print("[INIT] Loading model: {}...".format(model_id))
        
        stream_pipe = StreamDiffusion(
            model_id_or_path=model_id,
            t_index_list=t_index_list,
            torch_dtype=torch.float16,
            width=512,
            height=512,
            do_add_noise=True,
            frame_buffer_size=1,
            use_denoising_batch=True,
        )
        
        # Prompt設定
        stream_pipe.prepare(
            prompt=current_prompt,
            num_inference_steps=50,
            guidance_scale=1.2,
        )
        
        # Warmup
        print("[INIT] Warming up...")
        dummy = Image.new("RGB", (512, 512), (128, 128, 128))
        for _ in range(5):
            stream_pipe(image=dummy)
        
        print("[INIT] Pipeline ready!")
        return True
        
    except ImportError as e:
        print("[WARN] StreamDiffusion not installed: {}".format(e))
        print("[WARN] Running in DEMO mode (passthrough + OpenCV toon filter)")
        return False


def transform_frame(pil_image):
    """1フレーム変換"""
    global stream_pipe
    
    # 512x512にリサイズ
    img = pil_image.resize((512, 512), Image.LANCZOS)
    
    if stream_pipe is not None:
        # StreamDiffusion変換
        result = stream_pipe(image=img)
        if isinstance(result, torch.Tensor):
            from streamdiffusion.image_utils import postprocess_image
            result = postprocess_image(result, output_type="pil")[0]
        return result
    else:
        # フォールバック: OpenCVトゥーンフィルタ
        return toon_filter_pil(img)


def toon_filter_pil(pil_image):
    """OpenCVトゥーンフィルタ（StreamDiffusion未インストール時のフォールバック）"""
    import cv2
    
    frame = np.array(pil_image)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    
    smooth = frame.copy()
    for _ in range(3):
        smooth = cv2.bilateralFilter(smooth, 9, 75, 75)
    
    div = 32
    quantized = (smooth // div) * div + div // 2
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    edges = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY, 9, 2
    )
    edges_color = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    toon = cv2.bitwise_and(quantized, edges_color)
    
    hsv = cv2.cvtColor(toon, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.4, 0, 255).astype(np.uint8)
    toon = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    toon = cv2.cvtColor(toon, cv2.COLOR_BGR2RGB)
    
    return Image.fromarray(toon)


# === MJPEG Source (from JetBot) ===

class MJPEGReader:
    """JetBotのMJPEGストリームからフレーム取得"""
    
    def __init__(self, url="http://192.168.3.8:8554/raw"):
        self.url = url
        self.current_frame = None
        self.lock = threading.Lock()
        self.running = False
    
    def start(self):
        self.running = True
        t = threading.Thread(target=self._read_loop, daemon=True)
        t.start()
        print("[MJPEG] Reader started: {}".format(self.url))
    
    def stop(self):
        self.running = False
    
    def get_frame(self):
        with self.lock:
            return self.current_frame
    
    def _read_loop(self):
        import urllib.request
        
        while self.running:
            try:
                stream = urllib.request.urlopen(self.url, timeout=10)
                buf = b""
                
                while self.running:
                    buf += stream.read(4096)
                    
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9", start) if start >= 0 else -1
                    
                    if start >= 0 and end >= 0:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        
                        img = Image.open(io.BytesIO(jpg)).convert("RGB")
                        with self.lock:
                            self.current_frame = img
                
            except Exception as e:
                print("[MJPEG] Error: {}, retrying...".format(e))
                time.sleep(2)


mjpeg_reader = MJPEGReader()


# === API Endpoints ===

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "pipeline": "streamdiffusion" if stream_pipe else "opencv_toon",
        "prompt": current_prompt,
        "strength": current_strength,
        "timestamp": time.time(),
    })


@app.route("/style", methods=["GET"])
def get_style():
    return jsonify({
        "prompt": current_prompt,
        "strength": current_strength,
    })


@app.route("/style", methods=["POST"])
def set_style():
    global current_prompt, current_strength, stream_pipe
    
    data = request.get_json(force=True)
    
    # プリセット名対応（VoiceStyleControllerから {"style": "ghibli"} 等）
    if "style" in data:
        preset_name = data["style"].lower()
        if preset_name in STYLE_PRESETS:
            current_prompt = STYLE_PRESETS[preset_name]
        else:
            return jsonify({"error": "Unknown style: {}".format(preset_name), "available": list(STYLE_PRESETS.keys())}), 400
    
    if "prompt" in data:
        current_prompt = data["prompt"]
    if "strength" in data:
        current_strength = float(data["strength"])
    
    # パイプラインのprompt更新
    if stream_pipe is not None:
        try:
            stream_pipe.prepare(
                prompt=current_prompt,
                num_inference_steps=50,
                guidance_scale=1.2,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({
        "prompt": current_prompt,
        "strength": current_strength,
        "status": "updated",
    })


@app.route("/transform", methods=["POST"])
def transform():
    """1フレーム変換 API
    POST: multipart/form-data with 'image' file
    Returns: JPEG image
    """
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    
    file = request.files["image"]
    img = Image.open(file.stream).convert("RGB")
    
    t0 = time.time()
    result = transform_frame(img)
    elapsed = time.time() - t0
    
    # JPEG出力
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    
    response = Response(buf.getvalue(), mimetype="image/jpeg")
    response.headers["X-Transform-Time"] = "{:.3f}".format(elapsed)
    return response


@app.route("/stream")
def stream():
    """変換済みMJPEGストリーム"""
    def generate():
        while True:
            frame = mjpeg_reader.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            
            result = transform_frame(frame)
            
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=80)
            jpg = buf.getvalue()
            
            yield (
                b"--jpgboundary\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                + jpg + b"\r\n"
            )
    
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=--jpgboundary"
    )


@app.route("/")
def index():
    return """<!DOCTYPE html>
<html>
<head><title>Vision PAL - StreamDiffusion</title>
<style>
body { margin:0; background:#111; color:#fff; font-family:sans-serif; text-align:center; }
.container { display:flex; justify-content:center; gap:20px; padding:20px; flex-wrap:wrap; }
.feed { display:flex; flex-direction:column; align-items:center; }
.feed img { border-radius:12px; max-width:512px; }
h1 { padding:20px 0 0; }
.controls { padding:20px; }
input[type=text] { width:400px; padding:8px; font-size:16px; border-radius:8px; border:1px solid #555; background:#222; color:#fff; }
button { padding:8px 20px; font-size:16px; border-radius:8px; border:none; background:#6c5ce7; color:#fff; cursor:pointer; margin:5px; }
button:hover { background:#a29bfe; }
#status { color:#aaa; margin-top:10px; }
</style>
</head>
<body>
<h1>Vision PAL - AI World Filter</h1>

<div class="controls">
    <input type="text" id="prompt" placeholder="Style prompt..." value="anime style, studio ghibli, warm colors">
    <button onclick="setStyle()">Apply Style</button>
    <div id="status">Loading...</div>
</div>

<div class="container">
    <div class="feed">
        <h2>AI Transformed</h2>
        <img src="/stream" id="transformed">
    </div>
</div>

<h3>Preset Styles</h3>
<button onclick="setPreset('anime style, studio ghibli, warm colors, hand-painted, magical')">🌿 Ghibli</button>
<button onclick="setPreset('cyberpunk neon city, glowing lights, futuristic, dark atmosphere')">🌃 Cyberpunk</button>
<button onclick="setPreset('watercolor painting, soft colors, artistic, dreamy')">💧 Watercolor</button>
<button onclick="setPreset('pencil sketch, detailed drawing, black and white, artistic')">✏️ Sketch</button>
<button onclick="setPreset('oil painting, impressionist, vivid colors, thick brushstrokes')">🖌️ Oil Paint</button>
<button onclick="setPreset('pixel art, retro game, 16-bit style, colorful')">👾 Pixel Art</button>
<button onclick="setPreset('ukiyo-e, japanese woodblock print, traditional art')">🏯 Ukiyo-e</button>

<script>
async function setStyle() {
    const prompt = document.getElementById('prompt').value;
    const res = await fetch('/style', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt: prompt, strength: 0.65})
    });
    const data = await res.json();
    document.getElementById('status').textContent = 'Style: ' + data.prompt;
}

function setPreset(prompt) {
    document.getElementById('prompt').value = prompt;
    setStyle();
}

// Health check
fetch('/health').then(r => r.json()).then(d => {
    document.getElementById('status').textContent = 
        'Pipeline: ' + d.pipeline + ' | Style: ' + d.prompt;
});
</script>
</body>
</html>"""


# === Preset Styles (for MQTT integration) ===

STYLE_PRESETS = {
    "ghibli": "anime style, studio ghibli, warm colors, hand-painted, magical",
    "cyberpunk": "cyberpunk neon city, glowing lights, futuristic, dark atmosphere",
    "watercolor": "watercolor painting, soft colors, artistic, dreamy",
    "sketch": "pencil sketch, detailed drawing, black and white, artistic",
    "oil": "oil painting, impressionist, vivid colors, thick brushstrokes",
    "pixel": "pixel art, retro game, 16-bit style, colorful",
    "ukiyoe": "ukiyo-e, japanese woodblock print, traditional art",
    "pastel": "pastel colors, soft dreamy illustration, kawaii style",
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vision PAL StreamDiffusion Server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8555, help="Server port")
    parser.add_argument("--model", default="KBlueLeaf/kohaku-v2.1", help="SD model")
    parser.add_argument("--jetbot", default="http://192.168.3.8:8554/raw", help="JetBot MJPEG URL")
    parser.add_argument("--no-gpu", action="store_true", help="CPU/toon filter only")
    args = parser.parse_args()
    
    print("=" * 50)
    print("  Vision PAL - StreamDiffusion API Server")
    print("=" * 50)
    
    # MJPEG reader起動
    mjpeg_reader.url = args.jetbot
    mjpeg_reader.start()
    
    # StreamDiffusionパイプライン初期化
    if not args.no_gpu:
        try:
            import torch
            init_pipeline(args.model)
        except Exception as e:
            print("[WARN] GPU init failed: {}".format(e))
            print("[WARN] Falling back to OpenCV toon filter")
    else:
        print("[INFO] Running in CPU/toon filter mode")
    
    print("[HTTP] Server: http://{}:{}".format(args.host, args.port))
    print("[HTTP] Styles: /style (GET/POST)")
    print("[HTTP] Stream: /stream")
    print("[HTTP] Single: /transform (POST)")
    
    app.run(host=args.host, port=args.port, threaded=True)
