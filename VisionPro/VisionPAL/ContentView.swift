import SwiftUI

struct ContentView: View {
    @EnvironmentObject var robot: RobotController
    @EnvironmentObject var voiceStyle: VoiceStyleController
    @EnvironmentObject var effectController: EmotionEffectController
    @EnvironmentObject var battleController: BattleController
    @EnvironmentObject var monsterARController: MonsterARController
    @Environment(\.openImmersiveSpace) var openImmersiveSpace
    @Environment(\.dismissImmersiveSpace) var dismissImmersiveSpace
    @Environment(\.openWindow) var openWindow
    @State private var isImmersive = false
    @State private var isEffectMode = false
    @State private var isCurvedMode = false
    @State private var isBattleArena = false
    @State private var isEmotionMonster = false
    @State private var currentCameraURL: URL?
    
    private var desiredCameraURL: URL {
        voiceStyle.isStreamDiffusionEnabled
            ? voiceStyle.transformedStreamURL
            : robot.cameraURL
    }
    
    var body: some View {
        HStack(spacing: 30) {
            // 左: カメラ + 操作
            VStack(spacing: 20) {
                // Header
                Text("Vision PAL 🐾")
                    .font(.largeTitle)
                    .bold()
                
                // Connection Status
                HStack(spacing: 8) {
                    Circle()
                        .fill(robot.isConnected ? .green : .red)
                        .frame(width: 12, height: 12)
                    Text(robot.isConnected ? "MQTT Connected" : "Disconnected")
                        .foregroundColor(.secondary)
                        .font(.caption)
                }
                
                if isCurvedMode {
                    CurvedScreenView(url: currentCameraURL ?? robot.cameraURL)
                        .frame(width: 800, height: 450)
                        .cornerRadius(16)
                } else {
                    MJPEGView(url: currentCameraURL ?? robot.cameraURL)
                        .frame(width: 800, height: 450)  // 16:9
                        .clipped()
                        .cornerRadius(16)
                        .shadow(radius: 10)
                        .overlay(
                            // スタイル表示バッジ
                            Group {
                                if voiceStyle.isStreamDiffusionEnabled {
                                    Text(voiceStyle.lastCommand)
                                        .font(.caption)
                                        .padding(6)
                                        .background(.ultraThinMaterial)
                                        .cornerRadius(8)
                                }
                            },
                            alignment: .topTrailing
                        )
                }
                
                // Manual Controls
                controlPad
                
                // Curved Screen Toggle
                Toggle("🌀 Curved Screen", isOn: $isCurvedMode)
                    .toggleStyle(.button)
                
                // Immersive Mode Toggle
                Toggle("🎯 Head Tracking Mode", isOn: $isImmersive)
                    .toggleStyle(.button)
                    .onChange(of: isImmersive) { _, newValue in
                        Task {
                            if newValue {
                                if isEffectMode { isEffectMode = false; await dismissImmersiveSpace() }
                                await openImmersiveSpace(id: "ImmersiveControl")
                            } else {
                                await dismissImmersiveSpace()
                            }
                        }
                    }

                // Battle Mode
                HStack(spacing: 12) {
                    Button("⚔️ Battle Window") {
                        openWindow(id: "BattleWindow")
                    }
                    .buttonStyle(.bordered)
                    .tint(.orange)

                    Toggle("🏟️ AR Battle", isOn: $isBattleArena)
                        .toggleStyle(.button)
                        .onChange(of: isBattleArena) { _, newValue in
                            Task {
                                if newValue {
                                    if isImmersive { isImmersive = false; await dismissImmersiveSpace() }
                                    if isEffectMode { isEffectMode = false; await dismissImmersiveSpace() }
                                    await openImmersiveSpace(id: "BattleArena")
                                } else {
                                    await dismissImmersiveSpace()
                                }
                            }
                        }
                }

                // Emotion Monster AR
                Toggle("🐱 Emotion Monster", isOn: $isEmotionMonster)
                    .toggleStyle(.button)
                    .onChange(of: isEmotionMonster) { _, newValue in
                        Task {
                            if newValue {
                                if isImmersive { isImmersive = false; await dismissImmersiveSpace() }
                                if isEffectMode { isEffectMode = false; await dismissImmersiveSpace() }
                                if isBattleArena { isBattleArena = false; await dismissImmersiveSpace() }
                                await openImmersiveSpace(id: "EmotionMonster")
                            } else {
                                await dismissImmersiveSpace()
                            }
                        }
                    }

                // Emotion Effect Mode
                Toggle("✨ Emotion Effect", isOn: $isEffectMode)
                    .toggleStyle(.button)
                    .onChange(of: isEffectMode) { _, newValue in
                        Task {
                            if newValue {
                                if isImmersive { isImmersive = false; await dismissImmersiveSpace() }
                                await openImmersiveSpace(id: "EmotionEffect")
                            } else {
                                await dismissImmersiveSpace()
                            }
                        }
                    }

                // Effect Status
                EmotionEffectOverlay()
                    .environmentObject(effectController)

                // 3DGS Viewer
                Button("🌐 3DGS Viewer") {
                    openWindow(id: "SplatDemoWindow")
                }
                .buttonStyle(.bordered)
                .tint(.cyan)
            }
            
            // 右: ボイススタイルパネル
            voiceStylePanel
        }
        .padding(40)
        .preferredSurroundingsEffect(.dark)
        .onAppear {
            voiceStyle.requestPermissions()
            currentCameraURL = desiredCameraURL
        }
        .onChange(of: voiceStyle.isStreamDiffusionEnabled) { _, _ in
            let newURL = desiredCameraURL
            if currentCameraURL != newURL {
                print("[CAM] Switching to: \(newURL.absoluteString)")
                currentCameraURL = newURL
            }
        }
    }
    
    // MARK: - Control Pad
    
    private var controlPad: some View {
        VStack(spacing: 16) {
            Text("Manual Control")
                .font(.headline)
            
            VStack(spacing: 8) {
                Button("⬆️ Forward") {
                    robot.move(direction: .forward, speed: 0.4)
                }
                .buttonStyle(.borderedProminent)
                
                HStack(spacing: 20) {
                    Button("⬅️ Left") {
                        robot.move(direction: .left, speed: 0.4)
                    }
                    .buttonStyle(.bordered)
                    
                    Button("🛑 Stop") {
                        robot.move(direction: .stop)
                    }
                    .buttonStyle(.bordered)
                    .tint(.red)
                    
                    Button("➡️ Right") {
                        robot.move(direction: .right, speed: 0.4)
                    }
                    .buttonStyle(.bordered)
                }
                
                Button("⬇️ Backward") {
                    robot.move(direction: .backward, speed: 0.3)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding()
        .background(.ultraThinMaterial)
        .cornerRadius(16)
    }
    
    // MARK: - Voice Style Panel
    
    private var voiceStylePanel: some View {
        VStack(spacing: 16) {
            Text("🎨 Voice Style")
                .font(.title2)
                .bold()
            
            // マイクボタン
            Button {
                voiceStyle.toggleListening()
            } label: {
                VStack(spacing: 8) {
                    Image(systemName: voiceStyle.isListening ? "mic.fill" : "mic.slash")
                        .font(.system(size: 40))
                        .foregroundStyle(voiceStyle.isListening ? .red : .secondary)
                        .symbolEffect(.pulse, isActive: voiceStyle.isListening)
                    Text(voiceStyle.isListening ? "聞いてるよ..." : "タップで音声認識")
                        .font(.caption)
                }
            }
            .buttonStyle(.plain)
            
            // 認識テキスト表示
            if !voiceStyle.recognizedText.isEmpty {
                Text(voiceStyle.recognizedText)
                    .font(.body)
                    .foregroundColor(.primary)
                    .lineLimit(2)
                    .frame(maxWidth: 250)
                    .padding(8)
                    .background(.ultraThinMaterial)
                    .cornerRadius(8)
            }
            
            // 現在のスタイル
            if voiceStyle.currentStyle != "none" {
                HStack {
                    Text("現在: \(voiceStyle.lastCommand)")
                        .font(.subheadline)
                    Button("✕") {
                        voiceStyle.isStreamDiffusionEnabled = false
                        voiceStyle.currentStyle = "none"
                    }
                    .font(.caption)
                }
            }
            
            Divider()
            
            // スタイルプリセットボタン（手動選択も可能）
            Text("プリセット")
                .font(.caption)
                .foregroundColor(.secondary)
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(VoiceStyleController.styleMap, id: \.preset) { style in
                    Button(style.display) {
                        voiceStyle.currentStyle = style.preset
                        voiceStyle.lastCommand = style.display
                        voiceStyle.isStreamDiffusionEnabled = true
                        // API呼び出しはVoiceStyleController内部で
                        applyStyleManually(style.preset)
                    }
                    .buttonStyle(.bordered)
                    .tint(voiceStyle.currentStyle == style.preset ? .blue : .secondary)
                    .font(.caption)
                }
            }
            
            // エラー表示
            if let error = voiceStyle.errorMessage {
                Text(error)
                    .font(.caption2)
                    .foregroundColor(.red)
                    .lineLimit(2)
            }
            
            Spacer()
            
            // StreamDiffusion接続先設定
            Text("SD Server: \(voiceStyle.streamDiffusionHost):\(voiceStyle.streamDiffusionPort)")
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .frame(width: 280)
        .padding()
        .background(.ultraThinMaterial)
        .cornerRadius(16)
    }
    
    private func applyStyleManually(_ preset: String) {
        let url = voiceStyle.streamDiffusionBaseURL.appendingPathComponent("style")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["style": preset])
        URLSession.shared.dataTask(with: request) { _, _, _ in }.resume()
    }
}
