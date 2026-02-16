# StreamDiffusion Server — Vision PAL

JetBotカメラ映像をパルの認知世界（Umwelt）としてリアルタイム変換・配信するサーバー。

## 概要

```
JetBot Camera →MJPEG→ StreamDiffusion Server ←MQTT← Cognition Engine
                              ↓                          ↑
                        変換済み映像                memory_search
                              ↓                    (OpenClaw API)
                    Vision Pro / Browser
```

パルの知覚・感情・記憶に基づいて、カメラ映像がリアルタイムでスタイル変換される。
- 嬉しい時 → 暖色系、レンズフレア、ボケ
- 不安な時 → 暗い紫、グリッチ、断片化
- 記憶が浮かぶ → ゴーストオーバーレイが濃くなる

## セットアップ

### 必要環境
- Python 3.10+
- NVIDIA GPU (GTX 2080 Ti以上推奨) + CUDA 12.1+
- GPUなしでもOpenCVトゥーンフィルタで動作（デモ用）

### インストール

```bash
python -m venv .venv
source .venv/bin/activate

# PyTorch + CUDA
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# StreamDiffusion + TensorRT（推奨、大幅に高速化）
pip install streamdiffusion[tensorrt]
python -m streamdiffusion.tools.install-tensorrt

# その他依存
pip install -r requirements.txt
```

> 💡 condaは不要。venvで十分動く。

### TensorRTなしで試す場合

```bash
pip install streamdiffusion
# TensorRTなしでも動作するが、FPSは低下（~10fps → ~3-5fps）
```

## 起動

```bash
source .venv/bin/activate

# 通常起動（GPU + MQTT自動接続）
python server.py

# JetBotのMJPEG URLを指定
python server.py --jetbot http://192.168.3.8:8554/raw

# GPUなし（OpenCVトゥーンフィルタ）
python server.py --no-gpu

# ポート変更
python server.py --port 8555
```

## APIエンドポイント

| Method | Path | 説明 |
|--------|------|------|
| GET | `/` | Umwelt Viewer（ブラウザUI） |
| GET | `/stream` | 変換済みMJPEGストリーム |
| GET | `/health` | ステータス（パイプライン、感情、MQTT状態） |
| GET | `/style` | 現在のスタイル取得 |
| POST | `/style` | スタイル変更 `{"prompt": "...", "strength": 0.65}` |
| POST | `/mode` | モード切替 `{"mode": "auto"}` or `{"mode": "manual"}` |
| POST | `/transform` | 1フレーム変換（multipart image） |
| GET | `/fps` | FPS・変換時間 |

## MQTT連携（Cognition Engine）

MQTTブローカー（デフォルト `192.168.3.5:1883`）に接続し、以下のトピックを購読：

| トピック | 内容 |
|---------|------|
| `vision_pal/prompt/current` | SDプロンプト自動更新 |
| `vision_pal/affect/state` | 感情状態（emotion, arousal） |
| `vision_pal/monologue` | パルの内面独白（ログ表示） |

### Auto / Manual モード

- **Auto**（デフォルト）: Cognition Engineのプロンプトで自動変換
- **Manual**: ブラウザUIやAPIから手動でスタイル指定

`POST /mode {"mode": "manual"}` で切替、またはUIの「Auto Mode」ボタン。

### 感情連動

| パラメータ | 効果 |
|-----------|------|
| arousal | 変換強度に連動（高い→強い変換 0.4-0.8） |
| emotion | UIの感情インジケーターに表示 |
| memory_strength | 記憶の鮮明さ（UIに表示） |

## プリセットスタイル

UIまたは `POST /style {"style": "ghibli"}` で指定:

| プリセット | 説明 |
|-----------|------|
| `ghibli` | ジブリ風アニメ |
| `cyberpunk` | サイバーパンクネオン |
| `watercolor` | 水彩画 |
| `sketch` | 鉛筆スケッチ |
| `oil` | 油絵・印象派 |
| `pixel` | ピクセルアート |
| `ukiyoe` | 浮世絵 |
| `pastel` | パステルカラー |

## Umwelt Viewer

ブラウザで `http://PC:8555` にアクセスすると、リアルタイムビューアが開く：

- **変換映像ストリーム** — パルの認知世界
- **感情インジケーター** — 現在の感情がハイライト
- **Cognitionステータス** — MQTT接続状態、最終プロンプト受信時刻
- **FPSカウンター** — 変換速度
- **プリセットボタン** — 手動モード時のクイック切替

## アーキテクチャ

```
┌─────────────────────────────────────────────┐
│              StreamDiffusion Server           │
│                                               │
│  MJPEGReader ──→ transform_frame() ──→ /stream│
│  (JetBot:8554)       ↑                       │
│                      │                       │
│  CognitionSubscriber │                       │
│  (MQTT)         prompt更新                    │
│    ├── prompt/current → current_prompt        │
│    ├── affect/state   → emotion, arousal      │
│    └── monologue      → console log           │
└─────────────────────────────────────────────┘
```

## 開発メモ

- StreamDiffusion未インストール時はOpenCVトゥーンフィルタにフォールバック
- MQTT未接続でも手動モードで動作
- `--no-gpu` フラグでCPUのみ動作（デモ・テスト用）
