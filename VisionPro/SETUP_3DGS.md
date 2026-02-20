# 3DGS Viewer セットアップ手順

## 1. MetalSplatter SPM パッケージ追加

Xcodeで:
1. File → Add Package Dependencies
2. URL: `https://github.com/scier/MetalSplatter`
3. Branch: `main`
4. 追加するproducts: **MetalSplatter**, **SplatIO**, **PLYIO**
5. ターゲット: VisionPAL

## 2. VisionPALApp.swift に SplatDemo ImmersiveSpace 追加

```swift
import SwiftUI
import CompositorServices

@main
struct VisionPALApp: App {
    @StateObject private var robotController = RobotController()
    @StateObject private var voiceStyleController = VoiceStyleController()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(robotController)
                .environmentObject(voiceStyleController)
        }
        
        ImmersiveSpace(id: "ImmersiveControl") {
            ImmersiveControlView()
                .environmentObject(robotController)
        }
        .immersionStyle(selection: .constant(.progressive), in: .progressive)
        
        // 🆕 3DGS Viewer
        WindowGroup(id: "SplatDemoWindow") {
            SplatDemoView()
        }
        
        ImmersiveSpace(id: "SplatDemo") {
            CompositorLayer(configuration: SplatDemoConfiguration()) { layerRenderer in
                SplatDemoRenderer.startRendering(layerRenderer)
            }
        }
        .immersionStyle(selection: .constant(.full), in: .full)
    }
}
```

## 3. サンプル .ply ファイル

バンドルにサンプル.plyを追加（任意）:
1. .plyファイルをXcodeプロジェクトにドラッグ
2. 「Copy items if needed」チェック
3. Target: VisionPAL にチェック
4. ファイル名を `sample.ply` に

### サンプル .ply の入手先
- 3DGS公式: https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/
  - `bicycle`, `garden`, `stump` 等（数十MB〜数百MB）
- 軽量テスト用: Procedural Splat ボタンでファイル不要のテスト可能

## 4. Info.plist 設定

以下が設定されていることを確認:
```xml
<key>NSWorldSensingUsageDescription</key>
<string>Head tracking for 3D scene viewing</string>
```

## 5. ビルド & 実行

1. Scheme: **Release** モード推奨（Debugは10倍遅い）
2. Vision Pro実機 or Simulator で実行
3. メインウィンドウから「3DGS Viewer」を開く
4. .plyを読み込むか、Procedural Splatでテスト
5. シーン内をタップ → 波紋エフェクト ✨

## 6. 新規追加ファイル一覧

```
VisionPAL/
├── SplatDemoView.swift         ← UI + CompositorServices レンダラー
├── SplatDemoConfig.swift       ← LayerRenderer設定
├── SplatSceneView.swift        ← RealityKitベースビューア（将来のSHARP統合用）
├── RippleEffect.swift          ← 波紋エフェクト管理
└── Shaders/
    └── RipplePostProcess.metal ← 波紋ポストプロセスシェーダー
```

## トラブルシューティング

- **ビルドエラー: ModelRendererViewportDescriptor重複**
  → SplatDemoView.swift内の定義を削除し、MetalSplatterのSampleAppから`ModelRenderer.swift`と`SplatRenderer+ModelRenderer.swift`をコピー

- **画面が黒い**
  → Release modeでビルドしてるか確認。.plyファイルが大きすぎる場合はメモリ不足の可能性

- **波紋が出ない**
  → 現在のバージョンはTODOマーク。rippleManager.encode()の接続が必要（次のステップ）
