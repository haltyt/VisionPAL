# Vision PAL 🐾👁️

**AI の環世界（Umwelt）をリアルタイムで体験する** — JetBot ロボットが見て、感じて、記憶して、語り、探索する。

## 概要

Vision PAL は、JetBot（Jetson Nano）に搭載されたカメラ映像を VLM（Vision Language Model）で解析し、感情・記憶・独白を自律的に生成するシステムです。ダマシオのソマティック・マーカー仮説に基づく Survival Engine が身体信号から欲求を計算し、LLM の認知をホメオスタシスで修飾します。Apple Vision Pro と組み合わせて、AI の内面世界を AR で可視化するインスタレーション作品としても機能します。

## パイプライン

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
├── Cognition/          🧠 認知エンジン（Jetson/コンテナで実行）
│   ├── config.py              MQTT/モデル設定
│   ├── cognitive_loop.py      メインループ（全体統合）
│   ├── survival_engine.py     生存エンジン（6欲求ホメオスタシス）
│   ├── affect.py              感情システム（valence/arousal）
│   ├── scene_memory.py        シーン記憶（新規/既知判定、N-gram+Jaccard）
│   ├── explore_behavior.py    自律探索行動（novelty駆動）
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
│   ├── mqtt_robot.py          MQTTモーター制御
│   ├── mjpeg_server.py        USBカメラMJPEG配信 (port 8554)
│   ├── mjpeg_perception.py    カメラ+顔検出+MQTT publish
│   └── collision_detect.py    衝突検知CNN
│
├── VisionPro/          🥽 Vision Proアプリ（Swift/RealityKit）
│   └── VisionPAL/
│       ├── VisionPALApp.swift
│       ├── ContentView.swift
│       ├── ImmersiveControlView.swift
│       ├── MJPEGView.swift           MJPEG映像表示
│       ├── RobotController.swift      MQTT操縦
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
└── Controller/         🎮 物理コントローラー
    └── switch_controller.py
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
| `vision_pal/move` | explore/VisionPro → mqtt_robot | モーター制御 |
| `vision_pal/monologue` | cognitive_loop → | 生成された独白 |
| `vision_pal/affect/state` | cognitive_loop → | 感情状態 |
| `vision_pal/effect` | cognitive_loop → VisionPro | 視覚エフェクト |

## セットアップ

### 必要環境

- **JetBot**: Jetson Nano 4GB, USB カメラ, USB スピーカー
- **Jetson ホスト**: Mosquitto MQTT ブローカー, OpenClaw
- **クラウド API**: Gemini API キー, ElevenLabs API キー（TTS 用）
- **オプション**: Apple Vision Pro, PC (StreamDiffusion用, RTX 2080 Ti)

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
# === JetBot ===
# 1. MJPEG 配信
python3 ~/mjpeg_server.py --usb
# 2. 身体センサー
python3 ~/body_sensor.py
# 3. 衝突検知
python3 ~/collision_detect.py
# 4. モーター制御
python3 ~/mqtt_robot.py
# 5. 探索行動（オプション）
python3 ~/explore_behavior.py

# === Jetson コンテナ ===
# 6. VLM Watcher
python3 vlm_watcher.py --interval 5
# 7. Cognition Engine
python3 cognitive_loop.py --monologue-cooldown 10
```

## 関連研究

Survival Engine の設計は以下の研究と同じ方向性を持つ:

- **EILS** (Tiwari, 2025) — ホメオスタティック感情信号（好奇心のヴント曲線制御）
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
