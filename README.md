# Vision PAL 🐾👓 — "Umwelt"

**AIの環世界をARで可視化するアートインスタレーション**

パル（AI）の認知世界を覗く。物体認識、感情、記憶が混ざり合い、StreamDiffusionでリアルタイムに映像化される。人間とは異なる知覚、確率的な世界認識、記憶から染み出す過去の風景。

> Vision Pro + JetBot + Cognition Engine + StreamDiffusion

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       Local Network                           │
│                                                               │
│  ┌─────────────────────────────┐                              │
│  │      Vision Pro              │                              │
│  │  📺 MJPEGView (リアル映像)   │◄── MJPEG :8554 ─────────┐   │
│  │  🎨 UmweltView (認知映像)    │◄── MJPEG :8555 ──────┐  │   │
│  │  ✨ AffectOverlay (感情AR)   │◄── MQTT ───────────┐  │  │   │
│  │  🎯 HeadTracking → MQTT     │──┐                  │  │  │   │
│  │  🎤 VoiceStyle → HTTP       │──┼──┐               │  │  │   │
│  └─────────────────────────────┘  │  │               │  │  │   │
│                                    │  │               │  │  │   │
│  ┌─────────────────────────────┐  │  │               │  │  │   │
│  │  Jetson Nano (Host)         │  │  │               │  │  │   │
│  │  🧠 Cognition Engine ──────────┼──┼── MQTT pub ───┘  │  │   │
│  │     perception → affect     │  │  │                   │  │   │
│  │     → memory → prompt       │  │  │                   │  │   │
│  │     → TTS monologue 🔊     │  │  │                   │  │   │
│  │  📡 Mosquitto MQTT :1883 ◄──┘  │                   │  │   │
│  └─────────────────────────────┘     │                   │  │   │
│    192.168.3.5                       │                   │  │   │
│                                      │                   │  │   │
│  ┌─────────────────────────────┐     │                   │  │   │
│  │  PC (GTX 2080 Ti)           │     │                   │  │   │
│  │  🎨 StreamDiffusion :8555  │◄────┘                   │──┘   │
│  │     MJPEG in + prompt in    │◄── MQTT sub ────────────┘     │
│  │     → AI映像 out            │                              │
│  └─────────────────────────────┘                              │
│                                                               │
│  ┌─────────────────────────────┐                              │
│  │  JetBot                      │                              │
│  │  📷 MJPEG Camera :8554      │─────────────────────────────┘
│  │  🤖 MQTT Motor Control      │◄── MQTT sub
│  │  💥 Collision Detection      │── MQTT pub
│  └─────────────────────────────┘
│    192.168.3.8
└──────────────────────────────────────────────────────────────┘
```

## Cognition Engine — パルの心

2秒サイクルで動く認知ループ。パルの**リアルな内部状態**がそのまま映像とモノローグになる。

```
知覚 → 感情 → 記憶 → プロンプト → 映像 + 声
```

| モジュール | 役割 |
|-----------|------|
| `perception.py` | MQTT経由で物体認識データ受信 |
| `affect.py` | 8感情（好奇心/不安/喜び/驚き/退屈/怒り/悲しみ/平穏）を算出 |
| `memory_recall.py` | OpenClaw APIでセマンティック記憶検索（Gemini embedding + BM25） |
| `prompt_builder.py` | 感情→色彩・ムード + SD用プロンプト + 日本語モノローグ生成 |
| `cognitive_loop.py` | 2秒サイクルのオーケストレーター |
| `config.py` | MQTT・カメラ・DNN・感情マッピング設定 |

### 感情 → ビジュアルスタイル

| 感情 | 色彩 | ムード |
|------|------|--------|
| 🌟 curious | ゴールド・琥珀 | 暖かく輝く探索の光 |
| 😰 anxious | ダークパープル・ノイズ | 歪んだ不安定な空間 |
| 😊 happy | パステルピンク・虹色 | 柔らかく溢れる幸福感 |
| 😲 surprised | 白い閃光・ブルー | 鋭い一瞬の衝撃 |
| 😑 bored | グレー・セピア | 色褪せた平坦な世界 |
| 😡 frustrated | 赤・オレンジ | 燃える不満 |
| 😢 sad | 青・雨 | 滲む寂しさ |
| 🧘 calm | 薄い水色・白 | 穏やかな静寂 |

## MQTT Topics

```
vision_pal/
├── move                    # 操縦コマンド (Vision Pro → JetBot)
├── status                  # JetBotステータス
├── perception/objects      # 物体認識データ
├── perception/collision    # 衝突検知
├── affect/state            # 感情状態 (JSON)
├── memory/recall           # 記憶検索結果
├── prompt/current          # StreamDiffusion用プロンプト
├── monologue               # パルの独り言テキスト
└── umwelt/state            # 統合認知状態
```

## Setup

### 1. Mosquitto (Jetson Host)

```bash
sudo systemctl start mosquitto
```

### 2. JetBot

```bash
ssh jetbot@192.168.3.8
python3 mqtt_robot.py &
python3 mjpeg_light.py &    # MJPEG :8554
```

### 3. Cognition Engine (Jetson Container / OpenClaw)

```bash
cd Cognition
OPENCLAW_GATEWAY_TOKEN="$TOKEN" .venv/bin/python3 cognitive_loop.py --interval 2
```

### 4. StreamDiffusion (PC — GTX 2080 Ti)

```bash
cd StreamDiffusion
python -m venv .venv
source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install streamdiffusion[tensorrt]
python -m streamdiffusion.tools.install-tensorrt
python server.py --jetbot http://192.168.3.8:8554/raw
```

### 5. Vision Pro

```bash
cd VisionPro
open VisionPAL.xcodeproj   # Xcode 15+, visionOS SDK
```

## Voice Style Presets

Vision Proの音声認識で切り替え:

| Name | Keyword | Prompt |
|------|---------|--------|
| 🌿 Ghibli | ジブリ | anime style, studio ghibli, warm colors |
| 🌃 Cyberpunk | サイバーパンク | cyberpunk neon city, glowing lights |
| 💧 Watercolor | 水彩 | watercolor painting, soft colors |
| ✏️ Sketch | スケッチ | pencil sketch, black and white |
| 🖌️ Oil Paint | 油絵 | oil painting, impressionist |
| 👾 Pixel Art | ピクセル | pixel art, retro game, 16-bit |
| 🏯 Ukiyo-e | 浮世絵 | ukiyo-e, japanese woodblock print |
| 🌸 Pastel | パステル | pastel colors, soft dreamy illustration |

> 💡 Umweltモードではパルの感情が自動でスタイルを決定。音声スタイルはマニュアルモード用。

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Vision Pro | Swift, SwiftUI, RealityKit, ARKit, CocoaMQTT, Speech Framework |
| Cognition | Python 3.12, paho-mqtt 2.1, OpenClaw API (memory search) |
| StreamDiffusion | Python, PyTorch, CUDA, TensorRT, Flask |
| JetBot | Python 3.6, OpenCV, GStreamer, Adafruit MotorHAT, paho-mqtt |
| Jetson Host | Mosquitto, OpenClaw (Docker), ElevenLabs TTS |
| Network | MQTT (制御+認知), MJPEG (映像), HTTP (スタイル変更) |

## Project Structure

```
VisionPAL/
├── README.md                    # This file
├── ARCHITECTURE.md              # 詳細アーキテクチャ
├── EXHIBITION_CONCEPT.md        # 展示コンセプト
│
├── Cognition/                   # 🧠 認知エンジン (Jetson Container)
│   ├── config.py                #   設定
│   ├── perception.py            #   知覚モジュール
│   ├── affect.py                #   感情モジュール
│   ├── memory_recall.py         #   記憶検索
│   ├── prompt_builder.py        #   プロンプト生成
│   ├── cognitive_loop.py        #   メインループ
│   └── .venv/                   #   Python venv (paho-mqtt)
│
├── JetBot/                      # 🤖 JetBotスクリプト
│   ├── mqtt_robot.py            #   MQTT操縦
│   ├── mjpeg_light.py           #   カメラMJPEG配信
│   ├── jetbot_control.py        #   モーター制御
│   └── collision_detect.py      #   衝突検知
│
├── StreamDiffusion/             # 🎨 AI映像変換 (PC)
│   └── server.py                #   StreamDiffusion API
│
└── VisionPro/                   # 👓 Vision Proアプリ
    ├── README.md                #   ビルド手順
    ├── VisionPAL.xcodeproj/
    └── VisionPAL/
        ├── VisionPALApp.swift
        ├── ContentView.swift
        ├── MJPEGView.swift
        ├── RobotController.swift
        ├── VoiceStyleController.swift
        ├── ImmersiveControlView.swift
        └── CurvedScreenView.swift
```

## Development Status

- [x] **Phase 1**: Cognition Engine — 知覚・感情・記憶・プロンプト生成 + TTS
- [ ] **Phase 2**: StreamDiffusion連携 — img2img + プロンプト受信
- [ ] **Phase 3**: Vision Pro Umwelt UI — 認知映像 + 感情ARオーバーレイ
- [ ] **Phase 4**: 展示仕上げ — 自律走行、再起動演出、観客検知

## License

Private project.
