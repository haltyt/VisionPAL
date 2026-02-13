# VisionPAL - Vision Pro App

Vision Pro アプリケーション for パルロボットコントロール

## 概要

Vision Pro でパルロボット (JetBot) をコントロールし、リアルタイム AI 画風変換された映像を表示する visionOS アプリです。

## 機能

- **ヘッドトラッキング制御**: Vision Pro の頭の向きで JetBot を操作
- **MJPEG ストリーミング**: JetBot カメラの映像をリアルタイム表示
- **AI 画風変換**: StreamDiffusion による画風変換映像の表示
- **音声コマンド**: 日本語音声認識でスタイル変更
- **MQTT 通信**: JetBot との双方向通信

## プロジェクト構成

```
VisionPro/
├── VisionPAL.xcodeproj/          # Xcode プロジェクト
└── VisionPAL/                    # ソースコード
    ├── VisionPALApp.swift        # アプリエントリーポイント
    ├── ContentView.swift         # メインビュー
    ├── MJPEGView.swift           # MJPEG ストリーム表示
    ├── RobotController.swift     # MQTT/ロボット制御
    ├── VoiceStyleController.swift # 音声認識
    ├── ImmersiveControlView.swift # Immersive Space UI
    ├── Info.plist                # 権限設定
    └── Assets.xcassets/          # アセット
```

## ビルド手順

### 1. 必要な環境

- **macOS 14 (Sonoma) 以降**
- **Xcode 15.0 以降** (visionOS SDK 含む)
- **Apple Developer アカウント** (実機デプロイの場合)

### 2. プロジェクトを開く

```bash
cd VisionPAL/VisionPro
open VisionPAL.xcodeproj
```

### 3. パッケージ依存関係

以下のパッケージが自動的に解決されます:

- **CocoaMQTT 2.0.9**: MQTT クライアント
- **Starscream**: WebSocket (CocoaMQTT の依存関係)

パッケージが解決されない場合:
- **File → Packages → Reset Package Caches**
- **File → Packages → Resolve Package Versions**

### 4. ビルド

- シミュレータの場合: ターゲットを **Apple Vision Pro** に設定
- **⌘ + B** でビルド
- **⌘ + R** で実行

### 5. 実機デプロイ (オプション)

1. Vision Pro を USB-C で Mac に接続
2. Xcode で **Signing & Capabilities** → チームを選択
3. ターゲットを Vision Pro 実機に設定
4. **⌘ + R** で実行

## 設定

### ネットワーク設定

[RobotController.swift](VisionPAL/RobotController.swift) で接続先を変更できます:

```swift
let mqttHost = "192.168.3.5"      // MQTT ブローカー (Jetson)
let mqttPort: UInt16 = 1883
let cameraURL = URL(string: "http://192.168.3.8:8554/stream")!  // JetBot カメラ
```

### StreamDiffusion 設定

[ContentView.swift](VisionPAL/ContentView.swift) で StreamDiffusion サーバーの URL を設定:

```swift
let streamDiffusionURL = URL(string: "http://192.168.3.xxx:8555/stream")!
```

## 必要なインフラ

アプリを実行する前に、以下のサービスが起動している必要があります:

### 1. Jetson Nano (192.168.3.5)

```bash
# Mosquitto MQTT ブローカー
sudo systemctl start mosquitto
```

### 2. JetBot (192.168.3.8)

```bash
# MQTT ロボット制御
python3 mqtt_robot.py &

# MJPEG カメラサーバー
python3 mjpeg_server.py &
```

### 3. PC (StreamDiffusion サーバー)

```bash
cd StreamDiffusion
conda activate visionpal
python server.py --jetbot http://192.168.3.8:8554/raw
```

## 使い方

### ヘッドトラッキング制御

- **正面を向く**: 前進
- **左を向く**: 左旋回
- **右を向く**: 右旋回
- **下を向く**: 停止 (安全装置)

### 音声コマンド

以下の日本語キーワードで画風を変更:

- 「ジブリ」
- 「サイバーパンク」
- 「水彩」
- 「スケッチ」
- 「油絵」
- 「ピクセル」
- 「浮世絵」
- 「パステル」

## 権限

[Info.plist](VisionPAL/Info.plist) で以下の権限が設定されています:

- **音声認識** (`NSSpeechRecognitionUsageDescription`)
- **マイク** (`NSMicrophoneUsageDescription`)
- **ローカルネットワーク** (`NSLocalNetworkUsageDescription`)
- **Bonjour サービス** (`NSBonjourServices`)

## トラブルシューティング

### ビルドエラー

**パッケージが見つからない:**
```bash
# Xcode でキャッシュをリセット
File → Packages → Reset Package Caches
```

**Starscream の互換性エラー:**
- CocoaMQTT 2.0.9 を使用していることを確認
- Package Dependencies で Starscream のバージョンを確認

### 実行時エラー

**MQTT 接続失敗:**
- Mosquitto が起動しているか確認: `sudo systemctl status mosquitto`
- ネットワーク設定を確認 (192.168.3.5:1883)

**カメラ映像が表示されない:**
- JetBot の MJPEG サーバーが起動しているか確認
- ブラウザで `http://192.168.3.8:8554/stream` にアクセスして確認

**音声認識が動作しない:**
- Info.plist の権限設定を確認
- 実機の場合、設定で音声認識を許可

## アーキテクチャ

詳細なシステムアーキテクチャは [プロジェクトルートの README](../README.md) を参照してください。

## ライセンス

このプロジェクトは個人プロジェクトです。

## 関連リンク

- [CocoaMQTT](https://github.com/emqx/CocoaMQTT)
- [Starscream](https://github.com/daltoniam/Starscream)
- [StreamDiffusion](https://github.com/cumulo-autumn/StreamDiffusion)
