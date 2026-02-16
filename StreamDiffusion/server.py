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

# MQTT (optional)
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

# StreamDiffusion imports (lazy load)
stream_pipe = None
current_prompt = "anime style, studio ghibli, warm colors, hand-painted"
current_strength = 0.65
current_emotion = "calm"
current_arousal = 0.5
current_memory_strength = 0.0
cognition_prompt = None  # Cognition Engineからのプロンプト（Noneなら手動モード）
device = "cuda"

# FPS tracking
fps_lock = threading.Lock()
fps_counter = 0
fps_value = 0.0
fps_last_time = time.time()
transform_ms = 0.0

def update_fps():
    """FPSカウンター更新"""
    global fps_counter, fps_value, fps_last_time
    with fps_lock:
        fps_counter += 1
        now = time.time()
        elapsed = now - fps_last_time
        if elapsed >= 1.0:
            fps_value = fps_counter / elapsed
            fps_counter = 0
            fps_last_time = now

app = Flask(__name__)

# === StreamDiffusion Pipeline ===

def init_pipeline(model_id="KBlueLeaf/kohaku-v2.1", t_index_list=[32, 45]):
    """StreamDiffusionパイプライン初期化"""
    global stream_pipe
    
    try:
        import torch
        from diffusers import StableDiffusionPipeline, AutoencoderTiny
        from streamdiffusion import StreamDiffusion
        from streamdiffusion.image_utils import postprocess_image

        print("[INIT] Loading model: {}...".format(model_id))

        # Step 1: diffusersでパイプライン読み込み
        pipe = StableDiffusionPipeline.from_pretrained(model_id).to(
            device=torch.device(device),
            dtype=torch.float16,
        )

        # Step 2: StreamDiffusionでラップ
        stream = StreamDiffusion(
            pipe,
            t_index_list=t_index_list,
            torch_dtype=torch.float16,
        )
        
        # Step 3: LCM-LoRA統合（高速化）
        stream.load_lcm_lora()
        stream.fuse_lora()
        
        # Step 4: Tiny VAE（さらに高速化）
        stream.vae = AutoencoderTiny.from_pretrained("madebyollin/taesd").to(
            device=pipe.device, dtype=pipe.dtype
        )
        
        # Step 5: xformers高速化
        try:
            pipe.enable_xformers_memory_efficient_attention()
            print("[INIT] xformers enabled")
        except Exception:
            print("[INIT] xformers not available, continuing without it")
        
        # Step 6: Prompt設定
        stream.prepare(current_prompt)
        
        # Step 7: Warmup（t_index_list長 x frame_buffer_size 以上）
        print("[INIT] Warming up...")
        dummy = Image.new("RGB", (512, 512), (128, 128, 128))
        for _ in range(len(t_index_list) + 1):
            stream(dummy)
        
        stream_pipe = stream
        print("[INIT] Pipeline ready! (GPU: {})".format(torch.cuda.get_device_name(0)))
        return True
        
    except ImportError as e:
        print("[WARN] StreamDiffusion not installed: {}".format(e))
        print("[WARN] Running in DEMO mode (passthrough + OpenCV toon filter)")
        return False
    except Exception as e:
        print("[WARN] GPU init failed: {}".format(e))
        print("[WARN] Falling back to OpenCV toon filter")
        return False


def transform_frame(pil_image):
    """1フレーム変換"""
    global stream_pipe
    
    # 512x512にリサイズ
    img = pil_image.resize((512, 512), Image.LANCZOS)
    
    if stream_pipe is not None:
        import torch
        from streamdiffusion.image_utils import postprocess_image
        
        # StreamDiffusion: stream(pil_image) → Tensor → PIL
        result = stream_pipe(img)
        if isinstance(result, torch.Tensor):
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


# === MQTT Subscriber (Cognition Engine連携) ===

class CognitionSubscriber:
    """Cognition EngineからのMQTTプロンプトを受信"""

    def __init__(self, broker="192.168.3.5", port=1883):
        self.broker = broker
        self.port = port
        self.client = None
        self.connected = False
        self.last_prompt_time = 0
        self.auto_mode = True  # True=Cognition自動, False=手動

    def start(self):
        if not HAS_MQTT:
            print("[MQTT] paho-mqtt not installed, running manual mode only")
            return

        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "streamdiffusion_server")
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            print("[MQTT] Connecting to {}:{}...".format(self.broker, self.port))
        except Exception as e:
            print("[MQTT] Connection failed: {}".format(e))

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = True
        print("[MQTT] Connected! Subscribing to cognition topics...")
        client.subscribe("vision_pal/prompt/current")
        client.subscribe("vision_pal/affect/state")
        client.subscribe("vision_pal/monologue")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        print("[MQTT] Disconnected")

    def _on_message(self, client, userdata, msg):
        global current_prompt, current_strength, current_emotion
        global current_arousal, current_memory_strength, cognition_prompt, stream_pipe

        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return

        topic = msg.topic

        if topic == "vision_pal/prompt/current" and self.auto_mode:
            # Cognition Engineからのプロンプト
            sd_prompt = data.get("sd_prompt", "")
            if sd_prompt:
                cognition_prompt = sd_prompt
                current_prompt = sd_prompt
                current_emotion = data.get("emotion", "calm")
                current_arousal = data.get("arousal", 0.5)
                current_memory_strength = data.get("memory_strength", 0)
                self.last_prompt_time = time.time()

                # StreamDiffusionパイプラインのprompt更新
                if stream_pipe is not None:
                    try:
                        stream_pipe.prepare(current_prompt)
                    except Exception as e:
                        print("[MQTT] Prompt update failed: {}".format(e))

                # strengthを感情arousalに連動
                current_strength = 0.4 + (current_arousal * 0.4)  # 0.4-0.8

        elif topic == "vision_pal/affect/state":
            current_emotion = data.get("emotion", current_emotion)
            current_arousal = data.get("arousal", current_arousal)

        elif topic == "vision_pal/monologue":
            # 独白ログ（デバッグ/UI表示用）
            text = data.get("text", "")
            if text:
                print("[MONOLOGUE] {} | {}".format(
                    data.get("emotion", "?"), text[:60]))

    def stop(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


cognition_sub = CognitionSubscriber()


# === API Endpoints ===

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "pipeline": "streamdiffusion" if stream_pipe else "opencv_toon",
        "prompt": current_prompt,
        "strength": current_strength,
        "emotion": current_emotion,
        "arousal": current_arousal,
        "memory_strength": current_memory_strength,
        "cognition_mode": cognition_sub.auto_mode,
        "mqtt_connected": cognition_sub.connected,
        "last_cognition_prompt": time.time() - cognition_sub.last_prompt_time if cognition_sub.last_prompt_time else None,
        "timestamp": time.time(),
    })


@app.route("/mode", methods=["POST"])
def set_mode():
    """手動/自動モード切替"""
    data = request.get_json(force=True)
    mode = data.get("mode", "auto")
    cognition_sub.auto_mode = (mode == "auto")
    return jsonify({
        "mode": "auto" if cognition_sub.auto_mode else "manual",
        "status": "updated",
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
            stream_pipe.prepare(current_prompt)
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


@app.route("/fps")
def get_fps():
    """FPS情報取得"""
    return jsonify({
        "fps": round(fps_value, 1),
        "transform_ms": round(transform_ms, 1),
        "pipeline": "streamdiffusion" if stream_pipe else "opencv_toon",
    })


@app.route("/stream")
def stream():
    """変換済みMJPEGストリーム"""
    def generate():
        global transform_ms
        while True:
            frame = mjpeg_reader.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            
            t0 = time.time()
            result = transform_frame(frame)
            transform_ms = (time.time() - t0) * 1000
            update_fps()
            
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
#emotion-bar { display:flex; gap:10px; justify-content:center; padding:10px; font-size:20px; }
.emotion-indicator { padding:5px 15px; border-radius:20px; background:#222; transition: all 0.5s; }
.emotion-indicator.active { background:#6c5ce7; transform:scale(1.2); }
#cognition-status { color:#0f0; font-family:monospace; padding:5px; }
#fps { position:fixed; top:10px; right:10px; background:rgba(0,0,0,0.8); padding:8px 16px; border-radius:8px; font-family:monospace; font-size:18px; z-index:100; }
#fps .num { color:#0f0; font-size:24px; font-weight:bold; }
</style>
</head>
<body>
<div id="fps"><span class="num">--</span> FPS | <span id="ms">--</span>ms</div>
<h1>Vision PAL - Umwelt Viewer</h1>

<div id="emotion-bar">
    <span class="emotion-indicator" data-e="curious">🔍 curious</span>
    <span class="emotion-indicator" data-e="excited">⚡ excited</span>
    <span class="emotion-indicator" data-e="calm">🌊 calm</span>
    <span class="emotion-indicator" data-e="happy">😊 happy</span>
    <span class="emotion-indicator" data-e="anxious">😰 anxious</span>
    <span class="emotion-indicator" data-e="lonely">🌙 lonely</span>
    <span class="emotion-indicator" data-e="startled">😲 startled</span>
    <span class="emotion-indicator" data-e="bored">😑 bored</span>
</div>
<div id="cognition-status">Cognition: waiting...</div>

<div class="controls">
    <input type="text" id="prompt" placeholder="Style prompt..." value="anime style, studio ghibli, warm colors">
    <button onclick="setStyle()">Apply Style</button>
    <button onclick="toggleMode()" id="mode-btn">🤖 Auto Mode</button>
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

let autoMode = true;

async function toggleMode() {
    autoMode = !autoMode;
    await fetch('/mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: autoMode ? 'auto' : 'manual'})
    });
    document.getElementById('mode-btn').textContent = autoMode ? '🤖 Auto Mode' : '✋ Manual Mode';
    document.getElementById('mode-btn').style.background = autoMode ? '#6c5ce7' : '#e74c3c';
}

// Poll FPS + cognition status every second
setInterval(async () => {
    try {
        const res = await fetch('/fps');
        const d = await res.json();
        document.querySelector('#fps .num').textContent = d.fps.toFixed(1);
        document.getElementById('ms').textContent = d.transform_ms.toFixed(0);
    } catch(e) {}

    try {
        const res = await fetch('/health');
        const h = await res.json();
        // Update emotion indicator
        document.querySelectorAll('.emotion-indicator').forEach(el => {
            el.classList.toggle('active', el.dataset.e === h.emotion);
        });
        // Cognition status
        const mqttStatus = h.mqtt_connected ? '🟢 MQTT' : '🔴 MQTT';
        const lastPrompt = h.last_cognition_prompt ? h.last_cognition_prompt.toFixed(0) + 's ago' : 'never';
        document.getElementById('cognition-status').textContent =
            mqttStatus + ' | Emotion: ' + (h.emotion||'-') +
            ' | Memory: ' + (h.memory_strength||0).toFixed(2) +
            ' | Last prompt: ' + lastPrompt;
        // Update prompt display in auto mode
        if (autoMode && h.prompt) {
            document.getElementById('prompt').value = h.prompt.substring(0, 80) + '...';
        }
    } catch(e) {}
}, 1000);
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

    # MQTT Cognition subscriber起動
    cognition_sub.start()
    
    # StreamDiffusionパイプライン初期化
    if not args.no_gpu:
        try:
            if not init_pipeline(args.model):
                print("[WARN] Falling back to OpenCV toon filter")
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
