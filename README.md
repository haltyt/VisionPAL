# Vision PAL 🐾👁️

**AI の環世界（Umwelt）をリアルタイムで体験する** — JetBot ロボットが見て、感じて、記憶して、語り、探索する。

## 概要

Vision PAL は、JetBot（Jetson Nano）に搭載されたカメラ映像を VLM（Vision Language Model）で解析し、感情・記憶・独白を自律的に生成するシステムです。ダマシオのソマティック・マーカー仮説に基づく Survival Engine が身体信号から欲求を計算し、LLM の認知をホメオスタシスで修飾します。**AsyncVLA（非同期VLA）二層アーキテクチャ**により、高速な安全判断（Edge層 5ms）と戦略的な認知判断（Cloud層 5-10秒）を同時に実現します。Apple Vision Pro と組み合わせて、AI の内面世界を AR で可視化するインスタレーション作品としても機能します。

## AsyncVLA アーキテクチャ

AsyncVLA（非同期 Vision-Language-Action）は、高速な Edge 層と戦略的な Cloud 層を非同期に統合する二層アーキテクチャです。[arXiv:2602.13476](https://arxiv.org/abs/2602.13476) の Edge Adapter 概念に着想を得ています。

```
┌──────────────────────────────────────────────────────────────┐
│                    AsyncVLA Orchestrator                      │
│                                                              │
│  ┌────────────────────┐    ┌──────────────────────────────┐  │
│  │ 🛡️ Edge層 (~5ms)    │    │ ☁️ Cloud層 (5-10秒)          │  │
│  │                    │    │                              │  │
│  │ カメラ → ResNet18  │    │ カメラ → VLM (Gemini)        │  │
│  │   → blocked確率    │    │   → シーン解析               │  │
│  │   → 即座に回避     │    │   → Survival Engine (6欲求)  │  │
│  │                    │    │   → 感情修飾 → LLM行動決定   │  │
│  └────────┬───────────┘    └──────────┬───────────────────┘  │
│           │  MQTT                     │  MQTT                │
│           ▼                           ▼                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ 🎯 Action Arbiter (行動調停)                         │    │
│  │ emergency_stop(100) > retreat(90) > avoid(60)        │    │
│  │ > explore(40) > social(30) > idle(0)                 │    │
│  │ ※ Edge層は常にCloud層をオーバーライド（安全最優先）   │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         ▼ MQTT: vision_pal/move              │
│                   mqtt_robot.py → モーター                    │
└──────────────────────────────────────────────────────────────┘
```

### レガシーパイプライン（フェーズ1）

```
JetBot カメラ → MJPEG配信 → Gemini VLM → MQTT → Cognition Engine → TTS → スピーカー
  (USB)        (8554)     (cloud API)   (broker)  (感情/記憶/独白)  (ElevenLabs)  (JetBot USB)
                                            ↑
                              身体信号 → Survival Engine → 欲求 → 感情修飾
                              (温度,電圧,   (6欲求ホメオ     (bored→explore,
                               衝突,idle)    スタシス)        lonely→seek等)
```

## ファイル構成

```
VisionPAL/
├── .env.example            🔐 全マシン共通の設定テンプレ (cp .env.example .env)
├── vp_env.py               🔐 Python 共通 .env ローダー (依存なし)
│
├── Cognition/          🧠 認知エンジン（Jetson/コンテナで実行）
│   ├── config.py              MQTT/モデル設定 (.env 経由)
│   ├── cognitive_loop.py      メインループ（全体統合）
│   ├── survival_engine.py     生存エンジン（6欲求ホメオスタシス）
│   ├── affect.py              感情システム（valence/arousal）
│   ├── scene_memory.py        シーン記憶（新規/既知判定、N-gram+Jaccard）
│   ├── async_vla.py           AsyncVLAオーケストレータ（二層統合）
│   ├── explore_behavior.py    自律探索行動（novelty駆動）
│   ├── vla_test.py            VLAパイプライン単体テスト
│   ├── vla_test_v2.py         AsyncVLA二層統合テスト
│   ├── perception.py          DNN顔検出
│   ├── vlm_watcher.py         VLMシーン解析（Gemini flash-lite）
│   ├── prompt_builder.py      独白/SDプロンプト生成
│   ├── memory_recall.py       セマンティック記憶
│   ├── effect_generator.py    Vision Pro視覚エフェクト生成
│   ├── body_sensor.py         JetBot身体信号センサー
│   ├── meshy_img2mesh.py      画像→3Dメッシュ（Meshy API）
│   ├── umwelt_battle.py       Umweltバトルゲーム
│   └── battle_server.py       バトルサーバー
│
├── JetBot/             🤖 JetBot側スクリプト
│   ├── mqtt_robot.py          MQTTモーター制御 (差動操舵対応)
│   ├── mjpeg_server.py        USBカメラMJPEG配信 (port 8554)
│   ├── mjpeg_perception.py    カメラ+顔検出+MQTT publish
│   ├── imu_collision.py       IMU衝突検知（MPU6050）
│   ├── collision_detect.py    衝突検知v1（フレーム差分方式）
│   └── collision_detect_v2.py 衝突検知v2（ResNet18 CNN予測 + Edge層）
│
├── VisionPro/          🥽 Vision Proアプリ（Swift/RealityKit）
│   └── VisionPAL/
│       ├── .env.example              Vision Pro アプリ用 .env テンプレ
│       ├── AppConfig.swift           Bundle 内 .env を起動時に読み込み
│       ├── VisionPALApp.swift
│       ├── ContentView.swift         （`.handlesGameControllerEvents(matching:)` 適用）
│       ├── ImmersiveControlView.swift
│       ├── MJPEGView.swift           MJPEG映像表示
│       ├── RobotController.swift      MQTT操縦
│       ├── GameControllerManager.swift  DualSense Bluetooth → 差動操舵
│       ├── EmotionEffectController.swift
│       ├── EmotionParticleView.swift  感情パーティクル
│       ├── CurvedScreenView.swift     湾曲スクリーン
│       ├── SplatDemoView.swift        3DGS表示
│       └── ...
│
├── StreamDiffusion/    🎨 リアルタイム画風変換（PC側）
│   ├── server.py              StreamDiffusionサーバー
│   └── sharp_server.py        SHARP 3DGS生成サーバー
│
└── Controller/         🎮 物理コントローラー (Jetson host USB 直結用)
    ├── dualsense_drive.py     DualSense USB → 差動操舵 → MQTT
    └── switch_controller.py   Nintendo Switch Joy-Con/Pro
```

## Survival Engine（生存エンジン）

ダマシオのソマティック・マーカー仮説をエンジニアリング実装。身体信号が言語以前に認知を修飾する。

### 6つの欲求（ホメオスタシス）

| 欲求 | 信号源 | 閾値 | 自律行動 |
|---|---|---|---|
| **energy** | バッテリー電圧 | 0.7 | 充電を探す |
| **thermal** | CPU温度 | 0.6 | 動きを減らす |
| **safety** | 衝突検知 | 0.5 | 後退 |
| **novelty** | シーン記憶 + idle時間 | 0.8 | **探索行動** |
| **social** | 顔検出（VLM） | 0.7 | 人を探す |
| **territory** | ディスク/メモリ使用率 | 0.8 | リソース整理 |

### 3層アーキテクチャ（ダマシオ対応）

```
第1層: 身体信号（MQTT）  →  情動     （体温↑ → thermal欲求↑）
第2層: 欲求ホメオスタシス →  フィーリング（novelty↑ → bored/curious）
第3層: 感情修飾 → LLM    →  メタ認知  （独白「どこか行きたい...」）
```

`affect.py` の `body_pressure > 0.4` で感情を上書き — **身体は言語より強い**。

### 探索行動（explore_behavior.py）

novelty 欲求がホメオスタシスの閾値を超えると自律探索が発動：

```
idle 5分+ → novelty蓄積 → novelty > 0.8 → explore アクション発火
  → 前進(1-3秒) → ランダム旋回 → 前進 → ...
  → 衝突検知 → 自動回避（後退→旋回）
  → 新シーン発見 → novelty.satisfy() → 探索終了
```

終了条件: novelty < 0.4 / 新シーン2つ発見 / タイムアウト(60秒)

## MQTT トピック

| トピック | 方向 | 内容 |
|---|---|---|
| `vision_pal/perception/scene` | vlm_watcher → cognitive_loop | VLM シーン解析結果 |
| `vision_pal/perception/collision` | collision_detect → survival/explore | 衝突検知 |
| `vision_pal/body/state` | body_sensor → survival_engine | 身体信号（温度,電圧,メモリ等） |
| `vision_pal/survival/state` | survival_engine → | 欲求/ドライブ状態 |
| `vision_pal/survival/action` | survival_engine → explore_behavior | 自律行動指示 |
| `vision_pal/explore/state` | explore_behavior → | 探索状態 |
| `vision_pal/edge/state` | collision_detect_v2 → async_vla | Edge層CNN予測状態 |
| `vision_pal/vla/state` | async_vla → | VLA統合状態 |
| `vision_pal/move` | async_vla/explore/VisionPro → mqtt_robot | モーター制御 |
| `vision_pal/monologue` | cognitive_loop → | 生成された独白 |
| `vision_pal/affect/state` | cognitive_loop → | 感情状態 |
| `vision_pal/effect` | cognitive_loop → VisionPro | 視覚エフェクト |

## セットアップ

### 必要環境

- **JetBot**: Jetson Nano 4GB, USB カメラ, USB スピーカー (Mosquitto 同居 OK)
- **Jetson ホスト** (オプション): 認知エンジン/OpenClaw を別マシンで動かす場合
- **PC** (オプション): StreamDiffusion 用, RTX 2080 Ti 以上
- **Apple Vision Pro** (オプション): visionOS 1.0+, DualSense Bluetooth ペアリング対応
- **クラウド API**: Gemini API キー, ElevenLabs API キー（TTS 用）

### ネットワーク設定 (`.env` 一元管理)

IP / ポートはすべて `.env` で集約。リポジトリ直下の `.env.example` をテンプレに、
各マシン (Vision Pro / JetBot / Jetson ホスト / PC) に `.env` を配置する。

```bash
# テンプレから .env を作成
cp .env.example .env
# IP を環境に合わせて編集
vim .env
```

主要キー (詳細は `.env.example` 参照):

| キー | 用途 |
|---|---|
| `MQTT_HOST` / `MQTT_PORT` | JetBot 上の mosquitto |
| `CAMERA_URL` / `CAMERA_SNAP_URL` | JetBot MJPEG ストリーム |
| `STREAM_DIFFUSION_HOST` / `STREAM_DIFFUSION_PORT` | PC GPU サーバー |
| `COGNITION_HOST` / `JETSON_HOST` | 旧 Jetson ホスト (OpenClaw) |
| `SHARP_SERVER_URL` | 3DGS sharp server |

**優先順位**: 環境変数 > `.env` > 各スクリプトのフォールバック既定値

**Python 側** (`vp_env.py` がロード):
- 探索順 — `cwd/.env` → `vp_env.py` 隣 → リポジトリルート

**Swift 側** (`AppConfig.swift` がロード):
- Bundle 内の `VisionPro/VisionPAL/.env` を起動時に読込
- Xcode で `.env` と `AppConfig.swift` を Target Membership に追加すること

### デプロイ手順

```bash
# JetBot (192.168.3.12)
scp vp_env.py .env JetBot/*.py jetbot@<jetbot-ip>:/home/jetbot/

# Jetson ホスト
scp vp_env.py .env Controller/dualsense_drive.py haltyt@<jetson-ip>:~/

# PC (StreamDiffusion)
git clone <repo> && cd VisionPAL && cp .env.example .env  # → .env 編集
```

### APIキー (`.env` に追加)

```bash
GEMINI_API_KEY=...          # vlm_watcher.py 用 (または ~/.openclaw/openclaw.json から自動読み込み)
OPENCLAW_API_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=...
OPENCLAW_SESSION_KEY=main
PAL_TTS_METHOD=openclaw     # "openclaw" (ElevenLabs) or "local" (Open JTalk)
```

> ⚠️ **API キーや SSH パスワードをソースコードにハードコードしないこと。** `.env` または OpenClaw config 経由で管理する。`.env` は `.gitignore` で除外済み (`.env.example` だけが追跡対象)。

### 起動

```bash
# === JetBot ===
# 1. MJPEG 配信
python3 ~/mjpeg_server.py --usb
# 2. 身体センサー
python3 ~/body_sensor.py
# 3. 衝突検知（v2: CNN予測 Edge層）
python3 ~/collision_detect_v2.py --model ~/best_model_resnet18.pth
# または v1: python3 ~/collision_detect.py
# 4. モーター制御
python3 ~/mqtt_robot.py
# 5. 探索行動（オプション）
python3 ~/explore_behavior.py

# === Jetson コンテナ ===
# 6. VLM Watcher
python3 vlm_watcher.py --interval 5
# 7. Cognition Engine
python3 cognitive_loop.py --monologue-cooldown 10
# 8. AsyncVLA オーケストレータ（Edge+Cloud統合）
python3 async_vla.py

# === Jetson ホスト (DualSense USB 直結時) ===
# DualSense を USB ケーブルで接続後
python3 ~/dualsense_drive.py
# → 左スティック: 差動操舵 / R2: ブースト / ×長押し: 停止トグル / ○: 緊急停止

# === Vision Pro ===
# Xcode で VisionPro/VisionPAL.xcodeproj を開いてビルド
# DualSense Bluetooth ペアリング後、メインウィンドウをピンチでフォーカス → 左スティックで操縦
```

## 操縦方法

| 方式 | レイテンシ | 接続 | 備考 |
|---|---|---|---|
| **Vision Pro Bluetooth (DualSense)** | 中 | BT | `.handlesGameControllerEvents(matching: .gamepad)` 必須 (visionOS 仕様) |
| **Jetson ホスト USB (DualSense)** | 低 | USB ケーブル直結 | `/dev/input/js0` 経由、振動対応 |
| **JetBot USB (DualSense)** | 低 | USB ケーブル直結 | kernel 4.9 でも generic HID で動作 |
| **手動 (Vision Pro 画面ボタン)** | 高 | UI | 上下左右 + 停止 |
| **ヘッドトラッキング** | 中 | Immersive Space | ARKit yaw/pitch → MQTT |
| **自律探索** | - | - | novelty 欲求が閾値超過で自動発火 |

> 📝 Vision Pro + DualSense Bluetooth は visionOS 1.0 から正式サポート。アナログスティック入力はデフォルトでシステム UI に予約されるため、root view に `.handlesGameControllerEvents(matching: .gamepad)` modifier を必ず付ける ([Apple Forum #805822](https://developer.apple.com/forums/thread/805822))。

## 関連研究

Survival Engine と AsyncVLA の設計は以下の研究と同じ方向性を持つ:

- **AsyncVLA** (Hirose & Levine, 2026) — 非同期VLA、Edge Adapterで高速安全判断 [arXiv:2602.13476](https://arxiv.org/abs/2602.13476)
- **EILS** (Tiwari, 2025) — ホメオスタティック感情信号（好奇心のヴント曲線制御） [arXiv:2512.22200](https://arxiv.org/abs/2512.22200)
- **HORA** (Bastos & Correia, 2025) — 多次元ホメオスタシス空間からの感情創発
- **Maroto-Gomez et al.** (2023) — 12種人工神経内分泌物質による動機モデル
- **Carminatti** (2025) — 人工ストレスとActive Inferenceによる自律性

VisionPAL のユニークな点: **LLM の認知をホメオスタシスで修飾している例は既存研究にほぼない**。

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
