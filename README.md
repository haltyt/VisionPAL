# Vision PAL 🐾👓

**OpenClaw Eye — AIロボットは人間の夢を見るか？**

Vision Pro + JetBot + StreamDiffusion = パルの目で見る世界をリアルタイムAI画風変換

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                        Local Network                              │
│                                                                   │
│  Vision Pro (Swift/RealityKit)                                    │
│  ┌──────────────────────────┐                                     │
│  │  🎯 HeadTracking         │──MQTT──┐                            │
│  │  → yaw/pitch → direction │        │                            │
│  │                          │        │                            │
│  │  🎤 VoiceStyleController │        │                            │
│  │  → SFSpeechRecognizer    │──HTTP──┼──────────────┐             │
│  │  →「ジブリにして」        │        │              │             │
│  │                          │        │              ▼             │
│  │  📺 MJPEGView            │    ┌───┴──────────────────────┐     │
│  │  → Camera / AI Feed      │    │  PC (RTX 2080Ti)         │     │
│  └──────────┬───────────────┘    │  ┌────────────────────┐  │     │
│             │                    │  │  StreamDiffusion    │  │     │
│             │                    │  │  server.py :8555    │  │     │
│             │                    │  │                     │  │     │
│             │◄──HTTP (SD)────────│  │  MJPEG In → AI     │  │     │
│             │                    │  │  Transform → Out    │  │     │
│             │                    │  │  10 FPS / 512x512   │  │     │
│             │                    │  └────────┬───────────┘  │     │
│             │                    │           │              │     │
│             │                    │  8 Presets: Ghibli /     │     │
│             │                    │  Cyberpunk / Watercolor / │     │
│             │                    │  Sketch / Oil / Pixel /  │     │
│             │                    │  Ukiyo-e / Pastel        │     │
│             │                    └───────────┬──────────────┘     │
│             │                                │                    │
│             │      ┌─────────────────────────┘                    │
│             │      │ HTTP (MJPEG)                                 │
│             │      ▼                                              │
│  ┌──────────┴──────────────┐     ┌─────────────────────────┐     │
│  │  Jetson Nano (Host)     │     │  JetBot                  │     │
│  │  ┌───────────────────┐  │     │  ┌────────────────────┐  │     │
│  │  │ Mosquitto MQTT    │  │     │  │ mqtt_robot.py      │  │     │
│  │  │ :1883             │──┼──┐  │  │ → Motor Control    │  │     │
│  │  └───────────────────┘  │  │  │  │ (Adafruit MotorHAT)│  │     │
│  │  ┌───────────────────┐  │  └──┼─→│                    │  │     │
│  │  │ OpenClaw (Docker) │  │     │  └────────────────────┘  │     │
│  │  │ パルの脳 🧠       │  │     │  ┌────────────────────┐  │     │
│  │  └───────────────────┘  │     │  │ mjpeg_server.py    │  │     │
│  └─────────────────────────┘     │  │ :8554 CSI Camera   │──┼──→  │
│    192.168.3.5                   │  │ 640x480 @15fps     │  │     │
│                                  │  └────────────────────┘  │     │
│                                  │  192.168.3.8             │     │
│                                  └─────────────────────────┘     │
└───────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
JetBot Camera → MJPEG :8554 → PC StreamDiffusion → AI Transformed MJPEG :8555 → Vision Pro
                                      ↑
Vision Pro Voice →「サイバーパンク」→ POST /style → Prompt Update → Style Change
Vision Pro Head → MQTT → Jetson Mosquitto → JetBot mqtt_robot.py → Motor Move
```

## Components

### Vision Pro App (Swift + RealityKit)
- **HeadTracking** → MQTT move commands (yaw/pitch → direction)
- **MJPEGView** → Camera feed display (direct or AI-transformed)
- **VoiceStyleController** → 日本語音声認識 → スタイル変更
  - SFSpeechRecognizer (on-device, Japanese)
  - 8 preset keywords: ジブリ / サイバーパンク / 水彩 / スケッチ / 油絵 / ピクセル / 浮世絵 / パステル

### StreamDiffusion Server (PC with GPU)
- `server.py` — Flask API on port 8555
- JetBot MJPEG → img2img → AI-transformed MJPEG
- SD-turbo 1-step, LCM-LoRA, Tiny VAE (taesd)
- **~10 FPS** on RTX 2080Ti
- Endpoints:
  - `GET /stream` — Transformed MJPEG stream
  - `POST /style` — Change style (`{"style": "ghibli"}` or `{"prompt": "..."}`)
  - `GET /fps` — Real-time FPS & latency
  - `GET /` — Web UI with preset buttons

### JetBot (Python 3.6)
- `mqtt_robot.py` — MQTT subscriber → Adafruit MotorHAT control
- `mjpeg_server.py` — CSI camera (IMX219) → HTTP MJPEG stream on port 8554

### Infrastructure
- Mosquitto MQTT broker on Jetson host (192.168.3.5:1883)
- OpenClaw container on Jetson (パルの脳)
- All communication over local WiFi network

## Setup

```bash
# 1. Start Mosquitto on Jetson
sudo systemctl start mosquitto

# 2. Start JetBot scripts
ssh jetbot@192.168.3.8
python3 mqtt_robot.py &
python3 mjpeg_server.py &

# 3. Start StreamDiffusion on PC
cd StreamDiffusion
conda activate visionpal
python server.py --jetbot http://192.168.3.8:8554/raw

# 4. Open browser → http://localhost:8555 (Web UI)

# 5. (Optional) Open VisionPAL app on Vision Pro
```

## MQTT Topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `vision_pal/move` | Vision Pro → JetBot | `{"direction": "forward\|left\|right\|stop", "speed": 0.0-1.0}` |
| `vision_pal/status` | JetBot → Vision Pro | `{"status": "ready", "timestamp": ...}` |

## Style Presets

| Name | Prompt |
|------|--------|
| 🌿 Ghibli | anime style, studio ghibli, warm colors, hand-painted, magical |
| 🌃 Cyberpunk | cyberpunk neon city, glowing lights, futuristic, dark atmosphere |
| 💧 Watercolor | watercolor painting, soft colors, artistic, dreamy |
| ✏️ Sketch | pencil sketch, detailed drawing, black and white, artistic |
| 🖌️ Oil Paint | oil painting, impressionist, vivid colors, thick brushstrokes |
| 👾 Pixel Art | pixel art, retro game, 16-bit style, colorful |
| 🏯 Ukiyo-e | ukiyo-e, japanese woodblock print, traditional art |
| 🌸 Pastel | pastel colors, soft dreamy illustration, kawaii style |

## Tech Stack

- **Vision Pro**: Swift, RealityKit, ARKit, CocoaMQTT, Speech Framework
- **PC**: Python, StreamDiffusion, PyTorch, CUDA, Flask
- **JetBot**: Python 3.6, OpenCV, GStreamer, Adafruit MotorHAT, paho-mqtt
- **Jetson Host**: Mosquitto, OpenClaw (Docker)
