# StreamDiffusion Server for Vision PAL

Real-time AI style transfer for JetBot camera feed.

## Architecture

```
JetBot Camera (640x480)
  → MJPEG (port 8554)
    → This Server (RTX 2080Ti)
      → StreamDiffusion img2img (512x512)
      → Transformed MJPEG stream (port 8555)
        → Vision Pro
```

## Setup

```bash
# 1. Create environment
conda create -n visionpal python=3.10
conda activate visionpal

# 2. Install PyTorch (CUDA 11.8)
pip3 install torch==2.1.0 torchvision==0.16.0 xformers --index-url https://download.pytorch.org/whl/cu118

# 3. Install StreamDiffusion
pip install "streamdiffusion[tensorrt] @ git+https://github.com/cumulo-autumn/StreamDiffusion.git@main"

# 4. Fix version compatibility
pip install numpy==1.26.4 huggingface_hub==0.25.2 transformers==4.36.0

# 5. Install server dependencies
pip install flask opencv-python==4.10.0.84

# 6. (Optional) TensorRT acceleration
python -m streamdiffusion.tools.install-tensorrt
```

## Run

```bash
# Full mode (with StreamDiffusion)
python server.py --port 8555 --jetbot http://192.168.3.8:8554/raw

# Demo mode (OpenCV toon filter, no GPU needed)
python server.py --port 8555 --no-gpu
```

## API

### GET /stream
Transformed MJPEG stream. Point Vision Pro's MJPEGView here.

### POST /transform
Transform a single frame.
```bash
curl -X POST -F "image=@photo.jpg" http://localhost:8555/transform -o output.jpg
```

### GET /style
Get current style.

### POST /style
Change style in real-time.
```bash
curl -X POST http://localhost:8555/style \
  -H "Content-Type: application/json" \
  -d '{"prompt": "cyberpunk neon city, futuristic"}'
```

### Preset Styles
- 🌿 `ghibli` - Studio Ghibli anime
- 🌃 `cyberpunk` - Neon cyberpunk
- 💧 `watercolor` - Watercolor painting
- ✏️ `sketch` - Pencil sketch
- 🖌️ `oil` - Oil painting
- 👾 `pixel` - Pixel art
- 🏯 `ukiyoe` - Japanese woodblock print
- 🎀 `pastel` - Kawaii pastel

## Performance (expected)

| GPU | FPS (SD-turbo 1step) | FPS (LCM 4step) |
|-----|---------------------|-----------------|
| RTX 4090 | 50-90 | 20-40 |
| RTX 3080 | 25-45 | 12-20 |
| RTX 2080Ti | 15-25 | 8-12 |
| No GPU (toon) | 15+ | N/A |
