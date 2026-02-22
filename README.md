# Vision PAL 🐾👁️

**AI の環世界（Umwelt）をリアルタイムで体験する** — JetBot ロボットが見て、感じて、記憶して、語る。

## 概要

Vision PAL は、JetBot（Jetson Nano）に搭載されたカメラ映像を VLM（Vision Language Model）で解析し、感情・記憶・独白を自律的に生成するシステムです。Apple Vision Pro と組み合わせて、AI の内面世界を AR で可視化するインスタレーション作品としても機能します。

## パイプライン

```
JetBot カメラ → MJPEG配信 → Gemini VLM → MQTT → Cognition Engine → TTS → スピーカー
  (USB)        (8554)     (cloud API)   (broker)  (感情/記憶/独白)  (ElevenLabs)  (JetBot USB)
```

### コンポーネント

| コンポーネント | 場所 | 役割 |
|---|---|---|
| `mjpeg_server.py` | JetBot | USB カメラ → MJPEG 配信 (port 8554) |
| `vlm_watcher.py` | Jetson/コンテナ | MJPEG スナップ → Gemini flash-lite → MQTT publish |
| `cognitive_loop.py` | コンテナ | MQTT subscribe → 感情遷移 → 独白生成 → TTS → スピーカー再生 |
| `config.py` | - | MQTT トピック・ブローカー設定 |
| `affect.py` | - | 感情エンジン（valence/arousal モデル） |
| `perception.py` | - | 知覚データ管理 |
| `prompt_builder.py` | - | 独白プロンプト生成（VLM シーン情報統合） |
| `memory_recall.py` | - | 短期記憶・記憶強度管理 |
| `mqtt_robot.py` | JetBot | MQTT → モーター制御 |

### オプション（展示用）

| コンポーネント | 場所 | 役割 |
|---|---|---|
| `VisionPAL/` | Vision Pro | Swift/RealityKit アプリ（AR 表示 + MQTT 操縦） |
| `server.py` | PC | StreamDiffusion サーバー（認知映像変換） |
| `sharp_server.py` | PC | SHARP 3DGS 生成サーバー |

## セットアップ

### 必要環境

- **JetBot**: Jetson Nano 4GB, USB カメラ, USB スピーカー
- **Jetson ホスト**: Mosquitto MQTT ブローカー, OpenClaw
- **クラウド API**: Gemini API キー, ElevenLabs API キー（TTS 用）

### 環境変数

```bash
# vlm_watcher.py
GEMINI_API_KEY=...          # または ~/.openclaw/openclaw.json から自動読み込み

# cognitive_loop.py
OPENCLAW_API_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=...  # OpenClaw ゲートウェイトークン
OPENCLAW_SESSION_KEY=main
PAL_TTS_METHOD=openclaw     # "openclaw" (ElevenLabs) or "local" (Open JTalk)
```

> ⚠️ **API キーやトークンをソースコードにハードコードしないこと。** 環境変数または OpenClaw config 経由で管理する。

### 起動

```bash
# 1. JetBot: MJPEG 配信
ssh jetbot@<JETBOT_IP> "python3 ~/mjpeg_server.py --usb"

# 2. VLM Watcher（5秒間隔）
PYTHONUNBUFFERED=1 python3 vision_pal/Cognition/vlm_watcher.py --interval 5

# 3. Cognition Engine（独白クールダウン10秒）
PYTHONUNBUFFERED=1 python3 vision_pal/Cognition/cognitive_loop.py --monologue-cooldown 10
```

### MQTT トピック

| トピック | 方向 | 内容 |
|---|---|---|
| `vision_pal/perception/scene` | vlm_watcher → cognitive_loop | VLM シーン解析結果 (JSON) |
| `vision_pal/perception/collision` | mjpeg_perception → cognitive_loop | 衝突検知 |
| `vision_pal/perception/objects` | cognitive_loop → | 知覚オブジェクト |
| `vision_pal/monologue` | cognitive_loop → | 生成された独白 |
| `vision_pal/control` | Vision Pro → mqtt_robot | モーター操縦コマンド |

## アーキテクチャ詳細

→ [ARCHITECTURE.md](ARCHITECTURE.md)

## 展示コンセプト

→ [EXHIBITION_CONCEPT.md](EXHIBITION_CONCEPT.md)

## コスト目安（1時間稼働）

| 項目 | コスト |
|---|---|
| Gemini VLM (flash-lite) | ~$0.04（≈6円） |
| ElevenLabs TTS | 月間枠の ~3% |
| 独白生成 (Claude) | ~$0.02 |
| **合計** | **~$0.21（≈30円）** |

## ライセンス

MIT

## 作者

- **haltyt** — <https://github.com/haltyt>
- **パル** 🐾 — AI 相棒
