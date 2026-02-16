# Vision PAL — "Umwelt" アーキテクチャ
## AIの環世界をARで可視化するアートインスタレーション

---

## コンセプト
Vision Proを覗くと、パル（AI）の認知世界が見える。
人間とは異なる知覚、確率的な世界認識、記憶から染み出す過去の風景。
パルは自律的に動き、観客はその内面を「見せてもらう」立場。

---

## システム構成

```
┌─────────────────────────────────────────────────┐
│                  Vision Pro                      │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ MJPEG View│  │ SD View  │  │ AR Overlay   │ │
│  │(リアル映像)│  │(認知映像) │  │(感情エフェクト)│ │
│  └───────────┘  └──────────┘  └──────────────┘ │
│        ↑              ↑              ↑          │
│      MJPEG          MJPEG          MQTT         │
└────────┼──────────────┼──────────────┼──────────┘
         │              │              │
    ┌────┴────┐   ┌─────┴─────┐  ┌────┴────────┐
    │ JetBot  │   │    PC     │  │  OpenClaw   │
    │ Camera  │   │ Stream    │  │  (Jetson)   │
    │ MJPEG   │   │ Diffusion │  │             │
    │ :8554   │   │ :8555     │  │ 認知エンジン │
    └────┬────┘   └─────┬─────┘  └──────┬──────┘
         │              ↑               │
         │         カメラ映像+           │
         └──────→  プロンプト  ←─────────┘
                   (MQTT)
```

---

## コンポーネント

### 1. JetBot（パルの体）
- **カメラ** — IMX219 CSI → MJPEG配信 (:8554)
- **モーター** — 自律走行 or MQTT制御
- **衝突検知** — カメラフレーム差分方式
- 場所: JetBot (192.168.3.8)

### 2. OpenClaw 認知エンジン（パルの心）
- **知覚モジュール** — カメラ映像を取得→物体認識（YOLO/DNN）
- **感情モジュール** — パルの内部状態を算出（好奇心/不安/喜び/退屈）
- **記憶モジュール** — memory_searchで今の状況に関連する記憶を検索
- **プロンプト生成** — 知覚+感情+記憶 → StreamDiffusion用プロンプト
- **MQTT配信** — プロンプト・感情状態をpublish
- 場所: Jetson コンテナ (OpenClaw)

### 3. StreamDiffusion（パルの視覚野）
- JetBotカメラ映像をimg2img入力
- OpenClawからのプロンプトでスタイル変換
- 生成映像をMJPEG配信 (:8555)
- 場所: PC (GPU)

### 4. Vision Pro（観客の窓）
- **リアル映像** — JetBotカメラのMJPEG (既存)
- **認知映像** — StreamDiffusion出力のMJPEG (新規)
- **ARオーバーレイ** — 感情エフェクト、パーティクル (新規)
- 場所: Vision Pro

---

## MQTTトピック設計

```
vision_pal/
├── move            # 操縦コマンド (既存)
├── status          # JetBotステータス (既存)
├── perception      # 知覚データ
│   ├── objects     # {"objects": [{"label":"wall","confidence":0.87,"bbox":[...]}]}
│   └── collision   # {"collision": true, "diff": 0.5}
├── affect          # 感情状態
│   └── state       # {"emotion":"curious","valence":0.7,"arousal":0.5,"color":"#FFD700"}
├── memory          # 記憶
│   └── recall      # {"text":"ハルトと三体の話をした","relevance":0.85}
├── prompt          # StreamDiffusion用
│   └── current     # {"prompt":"a curious creature...", "strength":0.6}
└── umwelt          # 統合認知状態
    └── state       # 全レイヤー統合データ
```

---

## 認知→プロンプト変換パイプライン

```
[毎1-2秒のサイクル]

1. カメラフレーム取得
   → 物体認識 → perception/objects に publish

2. パル状態算出
   → モーター状態 + 衝突 + 物体認識結果
   → 感情値を算出 → affect/state に publish

3. 記憶検索
   → 知覚+感情をクエリとして memory_search
   → 関連記憶を取得 → memory/recall に publish

4. プロンプト合成
   → LLM（軽量）で知覚+感情+記憶を
     ビジュアルプロンプト文に変換
   → prompt/current に publish

5. StreamDiffusion
   → カメラ映像 + プロンプト → 認知映像生成
```

---

## ファイル構成

```
vision_pal/
├── ARCHITECTURE.md          # この文書
├── README.md
│
├── cognition/               # 認知エンジン（OpenClawから実行）
│   ├── perception.py        # 物体認識
│   ├── affect.py            # 感情算出
│   ├── memory_recall.py     # 記憶検索→プロンプト変換
│   ├── prompt_builder.py    # プロンプト合成
│   └── cognitive_loop.py    # メインループ（全統合）
│
├── jetbot/                  # JetBot側スクリプト
│   ├── jetbot_control.py    # モーター制御
│   ├── mjpeg_light.py       # カメラMJPEG配信
│   ├── mqtt_robot.py        # MQTT操縦
│   └── collision_detect.py  # 衝突検知
│
├── stream_diffusion/        # PC側
│   └── server.py            # StreamDiffusion MJPEG配信
│
└── VisionPAL/               # Vision Pro側
    └── VisionPro/
        └── VisionPAL/
            ├── VisionPALApp.swift
            ├── ContentView.swift
            ├── MJPEGView.swift          # 既存
            ├── CurvedScreenView.swift   # 既存
            ├── RobotController.swift    # 既存（MQTT）
            ├── UmweltView.swift         # 新規: 認知映像表示
            ├── AffectOverlay.swift      # 新規: 感情ARエフェクト
            └── ImmersiveControlView.swift
```

---

## 開発フェーズ

### Phase 1: 認知エンジンのプロトタイプ
- [ ] cognitive_loop.py — MQTTでカメラ映像取得+物体認識
- [ ] affect.py — 基本的な感情状態算出
- [ ] memory_recall.py — memory_search連携
- [ ] prompt_builder.py — 3層合成してMQTT配信

### Phase 2: StreamDiffusion連携
- [ ] PC側server.py — MJPEG in + prompt in → MJPEG out
- [ ] プロンプト→映像の品質チューニング

### Phase 3: Vision Pro表示
- [ ] UmweltView.swift — StreamDiffusion映像表示
- [ ] AffectOverlay.swift — 感情パーティクル
- [ ] リアル映像と認知映像の切り替え/ブレンド

### Phase 4: 展示仕上げ
- [ ] パルの自律走行モード
- [ ] 再起動演出（記憶の立ち上がり）
- [ ] 観客検知→認知世界の変化
