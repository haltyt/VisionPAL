# VisionPAL - Vision Pro App

Vision Pro アプリケーション for パルロボットコントロール

## 概要

Vision Pro でパルロボット (JetBot) をコントロールし、リアルタイム AI 画風変換された映像を表示する visionOS アプリです。

## 機能

- **DualSense Bluetooth 操縦**: PS5 コントローラーを Vision Pro に BT 直接接続して差動操舵
- **ヘッドトラッキング制御**: Vision Pro の頭の向きで JetBot を操作
- **MJPEG ストリーミング**: JetBot カメラの映像をリアルタイム表示
- **AI 画風変換**: StreamDiffusion による画風変換映像の表示
- **音声コマンド**: 日本語音声認識でスタイル変更
- **MQTT 通信**: JetBot との双方向通信
- **`.env` で接続先設定**: IP/ポートをコード外で管理

## プロジェクト構成

```
VisionPro/
├── VisionPAL.xcodeproj/          # Xcode プロジェクト
└── VisionPAL/                    # ソースコード
    ├── .env.example                Bundle 同梱用 .env テンプレ
    ├── AppConfig.swift             .env / 環境変数 / 既定値 の3層ローダー
    ├── VisionPALApp.swift          アプリエントリーポイント
    ├── ContentView.swift           メインビュー (.handlesGameControllerEvents)
    ├── MJPEGView.swift             MJPEG ストリーム表示
    ├── RobotController.swift       MQTT/ロボット制御 (タンク式 moveTank 含む)
    ├── GameControllerManager.swift DualSense BT → 差動操舵 → MQTT
    ├── VoiceStyleController.swift  音声認識
    ├── ImmersiveControlView.swift  Immersive Space UI
    ├── Info.plist                  権限設定
    └── Assets.xcassets/            アセット
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

## 設定 (`.env` 方式)

IP/ポートはすべて [VisionPAL/.env](VisionPAL/) で集約。コード書き換え不要。

### Xcode への `.env` 追加 (初回のみ)

1. `cp VisionPAL/.env.example VisionPAL/.env` でテンプレから作成、IP を編集
2. Xcode の Project Navigator で `VisionPAL/` を右クリック → **Add Files to "VisionPAL"...**
3. 隠しファイル表示 (`⌘ + Shift + .`) で `.env` を選び、`AppConfig.swift` も同時に選択
4. **Add to targets: VisionPAL** にチェック → Add

起動時に `[AppConfig] loaded .env: [...]` がコンソールに出れば成功。

### `.env` の主要キー

```
MQTT_HOST=192.168.3.12              # JetBot 上の mosquitto
MQTT_PORT=1883
CAMERA_URL=http://192.168.3.12:8554/stream
STREAM_DIFFUSION_HOST=192.168.3.7   # PC GPU
STREAM_DIFFUSION_PORT=8555
COGNITION_HOST=192.168.3.5          # 旧 Jetson ホスト (任意)
SHARP_SERVER_URL=http://192.168.3.5:8080
```

優先順位: 環境変数 (Xcode Scheme) > Bundle 内 `.env` > [AppConfig.swift](VisionPAL/AppConfig.swift) の既定値

## 必要なインフラ

アプリを実行する前に、以下のサービスが起動している必要があります:

### JetBot (`MQTT_HOST` で指定したマシン)

```bash
# Mosquitto MQTT ブローカー
sudo systemctl start mosquitto

# MQTT ロボット制御 + MJPEG カメラ
python3 ~/mqtt_robot.py &
python3 ~/mjpeg_server.py --usb &
```

### PC (StreamDiffusion サーバー、任意)

```bash
cd StreamDiffusion
conda activate visionpal
python server.py  # CAMERA_URL は .env から自動取得
```

## 使い方

### DualSense (PS5) Bluetooth 操縦

1. DualSense の **PS + Share ボタンを 3 秒長押し** → ペアリングモード (LED 高速点滅)
2. Vision Pro 設定 → Bluetooth で DualSense Wireless Controller を選んで接続
3. アプリ起動後、**メインウィンドウを「見つめてピンチ」でフォーカス**
4. 左スティックで操縦:

| 入力 | アクション |
|---|---|
| 左スティック | 差動操舵 (倒した方向に進む、横倒しで信地旋回) |
| R2 トリガー | 加速ブースト (baseSpeed → boostSpeed) |
| × ボタン長押し (0.6 秒+) | 停止トグル |
| ○ ボタン | 緊急停止 |
| ヘッダのコントローラ名タップ | 接続復旧 (再 attach) |

> 📝 visionOS では `.handlesGameControllerEvents(matching: .gamepad)` modifier がない
> とスティック入力がシステム UI に取られてアプリに届かない ([Forum #805822](https://developer.apple.com/forums/thread/805822))。
> 本アプリは ContentView root に設定済み。

### ヘッドトラッキング制御 (Immersive Space)

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

**`.env` が読み込まれない:**
- Xcode コンソールに `[AppConfig] .env not found in bundle` と出る場合、`.env` が Target Membership に含まれていない
- Project Navigator で `.env` を選び、右ペインの File Inspector → Target Membership で VisionPAL にチェック

**MQTT 接続失敗:**
- Mosquitto が起動しているか確認: `ssh <MQTT_HOST> sudo systemctl status mosquitto`
- `.env` の `MQTT_HOST` / `MQTT_PORT` が正しいか確認

**カメラ映像が表示されない:**
- JetBot の `mjpeg_server.py --usb` が起動しているか確認
- ブラウザで `$CAMERA_URL` にアクセスして確認

**DualSense スティックが効かない:**
- ContentView root に `.handlesGameControllerEvents(matching: .gamepad)` があるか
- DualSense を Vision Pro と Bluetooth ペアリングし直す (一度登録解除 → 再ペア)
- メインウィンドウを「見つめてピンチ」でフォーカス確保
- D-Pad は動くがスティックだけ動かない場合は modifier 漏れの典型症状

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
