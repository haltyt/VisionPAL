# VisionPAL - Claude Code Project Guide

このファイルは Claude Code がプロジェクトを理解するための情報を提供します。

## プロジェクト概要

**VisionPAL** は、Vision Pro でパルロボット (JetBot) をコントロールし、リアルタイム AI 画風変換された映像を表示するシステムです。

- **Vision Pro アプリ**: visionOS ネイティブアプリ (Swift/RealityKit)
- **JetBot**: NVIDIA Jetson Nano 上のロボット (Python)
- **StreamDiffusion**: PC 上のリアルタイム AI 画風変換サーバー (Python)
- **通信**: MQTT, HTTP/MJPEG

## プロジェクト構造

```
VisionPAL/
├── .claude/                      # Claude Code 設定
├── README.md                     # システム全体のアーキテクチャ
├── JetBot/                       # JetBot 用 Python スクリプト
│   ├── mqtt_robot.py             # MQTT ロボット制御
│   └── mjpeg_server.py           # カメラストリーミング
├── StreamDiffusion/              # PC 用 AI サーバー
│   └── server.py                 # StreamDiffusion API サーバー
└── VisionPro/                    # Vision Pro アプリ ⭐ メイン開発対象
    ├── README.md                 # ビルド手順
    ├── VisionPAL.xcodeproj/      # Xcode プロジェクト
    └── VisionPAL/                # Swift ソースコード
        ├── VisionPALApp.swift        # アプリエントリーポイント
        ├── ContentView.swift         # メインビュー
        ├── MJPEGView.swift           # MJPEG ストリーム表示
        ├── RobotController.swift     # MQTT/ロボット制御
        ├── VoiceStyleController.swift # 音声認識
        ├── ImmersiveControlView.swift # Immersive Space UI
        ├── Info.plist                # 権限設定
        └── Assets.xcassets/          # アセット
```

## 技術スタック

### Vision Pro アプリ (VisionPro/)
- **言語**: Swift
- **フレームワーク**: SwiftUI, RealityKit, ARKit
- **依存関係**:
  - CocoaMQTT 2.0.9 (MQTT クライアント)
  - Starscream (WebSocket - CocoaMQTT の依存)
- **ビルドツール**: Xcode 15+
- **プラットフォーム**: visionOS 1.0+

### JetBot (JetBot/)
- **言語**: Python 3.6
- **ハードウェア**: NVIDIA Jetson Nano
- **ライブラリ**: OpenCV, GStreamer, paho-mqtt, Adafruit MotorHAT

### StreamDiffusion (StreamDiffusion/)
- **言語**: Python
- **フレームワーク**: PyTorch, StreamDiffusion, Flask
- **ハードウェア**: RTX 2080Ti 以上推奨

## 重要なファイル

### Vision Pro アプリ開発時

- **VisionPro/VisionPAL/VisionPALApp.swift**: アプリのエントリーポイント、Immersive Space の設定
- **VisionPro/VisionPAL/ContentView.swift**: メイン UI、カメラ切り替え、スタイル選択
- **VisionPro/VisionPAL/RobotController.swift**: MQTT 通信、JetBot 制御ロジック
- **VisionPro/VisionPAL/MJPEGView.swift**: MJPEG ストリーミング表示
- **VisionPro/VisionPAL/VoiceStyleController.swift**: 音声認識、スタイル変更
- **VisionPro/VisionPAL/Info.plist**: 権限設定 (音声認識、マイク、ローカルネットワーク)

### 設定ファイル

- **VisionPro/VisionPAL.xcodeproj/**: Xcode プロジェクト設定
- **.gitignore**: Git 除外設定

## 開発ガイドライン

### Vision Pro アプリのビルド

```bash
cd VisionPro
open VisionPAL.xcodeproj
# Xcode で ⌘ + B でビルド
```

詳細は [VisionPro/README.md](../VisionPro/README.md) を参照。

### コーディング規約

- **Swift**: Swift 5.9+, SwiftUI, async/await
- **命名**: camelCase (変数/関数), PascalCase (型/クラス)
- **コメント**: 日本語コメント OK (既存コードに合わせる)
- **エラーハンドリング**: Optional チェーン (`?.`) を活用

### ネットワーク設定

- **MQTT ブローカー**: 192.168.3.5:1883 (Jetson Nano)
- **JetBot カメラ**: http://192.168.3.8:8554/stream
- **StreamDiffusion**: http://192.168.3.xxx:8555/stream (PC)

設定変更は `RobotController.swift` を編集。

## よくあるタスク

### パッケージ依存関係の更新

Xcode で:
```
File → Packages → Reset Package Caches
File → Packages → Update to Latest Package Versions
```

### ビルドエラー対応

**CocoaMQTT が見つからない:**
- Xcode の Package Dependencies タブで CocoaMQTT 2.0.9 を追加

**Starscream 互換性エラー:**
- CocoaMQTT 2.0.9 を使用していることを確認
- Starscream は CocoaMQTT の依存として自動解決される

### 新機能追加時の注意点

- **権限追加**: Info.plist に説明を追加
- **MQTT トピック**: 既存の命名規則に従う (`vision_pal/*`)
- **UI 変更**: SwiftUI で宣言的に記述
- **非同期処理**: `@MainActor` と `Task` を適切に使用

## デバッグ

### ログ出力

- `print("[TAG] message")` でコンソールに出力
- Xcode の Console で確認

### よくある問題

**MQTT 接続失敗:**
```bash
# Jetson Nano で確認
sudo systemctl status mosquitto
```

**カメラ映像が表示されない:**
```bash
# ブラウザでテスト
open http://192.168.3.8:8554/stream
```

**音声認識が動作しない:**
- Info.plist の権限を確認
- 実機の場合、設定で許可されているか確認

## アーキテクチャ

詳細なシステムアーキテクチャ図は [README.md](../README.md) を参照。

### データフロー

```
JetBot Camera → MJPEG :8554 → PC StreamDiffusion → AI Transformed MJPEG :8555 → Vision Pro
                                      ↑
Vision Pro Voice → POST /style → Prompt Update → Style Change
Vision Pro Head → MQTT → Jetson Mosquitto → JetBot mqtt_robot.py → Motor Move
```

### 主要コンポーネント

1. **ヘッドトラッキング**: ARKit でヘッドの向き検出 → MQTT で JetBot に送信
2. **MJPEG ストリーミング**: URLSession で HTTP ストリーム受信 → UIImage に変換 → SwiftUI で表示
3. **音声認識**: SFSpeechRecognizer (日本語) → キーワードマッチ → HTTP POST でスタイル変更
4. **MQTT 通信**: CocoaMQTT で双方向通信、ロボット制御

## テスト

### シミュレータでのテスト

- MQTT/カメラ接続は実際のネットワークが必要
- UI/音声認識はシミュレータで一部動作

### 実機テスト

- Vision Pro 実機が必要
- Apple Developer アカウントでサイニング

## デプロイ

### 開発ビルド

Xcode で実機を選択して ⌘ + R

### リリースビルド (将来)

- App Store Connect 未対応
- TestFlight での配布を検討

## 参考リンク

- [visionOS Documentation](https://developer.apple.com/visionos/)
- [CocoaMQTT GitHub](https://github.com/emqx/CocoaMQTT)
- [StreamDiffusion GitHub](https://github.com/cumulo-autumn/StreamDiffusion)

## メンテナンス

### 依存関係の更新

定期的に Xcode の Package Dependencies を確認し、セキュリティアップデートを適用。

### バックアップ

Git でバージョン管理中。重要な変更は commit & push。

---

**最終更新**: 2026-02-13
**プロジェクトステータス**: 開発中 ✅ ビルド成功
