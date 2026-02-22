import SwiftUI
import RealityKit

// MARK: - Monster AR Immersive View

struct MonsterARView: View {
    @EnvironmentObject var monsterAR: MonsterARController
    @State private var monsterEntity: Entity?
    @State private var glowEntity: ModelEntity?
    @State private var anchorEntity: AnchorEntity?
    @State private var loadedModelFile: String?
    
    var body: some View {
        RealityView { content in
            // Create world anchor (monsters appear 2m in front, on floor level)
            let anchor = AnchorEntity(.head)
            anchorEntity = anchor
            content.add(anchor)
        } update: { content in
            updateMonsterDisplay()
        }
        .onChange(of: monsterAR.currentMonster?.modelFile) { oldVal, newVal in
            if let newFile = newVal, newFile != loadedModelFile {
                loadMonsterModel(newFile)
            }
        }
        .onChange(of: monsterAR.emotionIntensity) { _, newIntensity in
            updateGlowIntensity(newIntensity)
        }
        .gesture(
            TapGesture()
                .targetedToAnyEntity()
                .onEnded { _ in
                    // Tap monster → cycle test emotions
                    cycleTestEmotion()
                }
        )
        .overlay(alignment: .bottom) {
            monsterInfoOverlay
                .padding(.bottom, 60)
        }
    }
    
    // MARK: - Model Loading
    
    private func loadMonsterModel(_ modelFile: String) {
        // Remove old monster
        monsterEntity?.removeFromParent()
        glowEntity?.removeFromParent()
        
        Task {
            do {
                // Load USDZ from app bundle
                let entity = try await Entity(named: modelFile)
                
                // Position: 2m in front, slightly below eye level
                entity.position = SIMD3<Float>(0, -0.5, -2.0)
                
                // Scale based on mapping
                let scale = monsterAR.currentMonster?.scale ?? 0.5
                entity.scale = SIMD3<Float>(repeating: scale)
                
                // Add to scene
                await MainActor.run {
                    anchorEntity?.addChild(entity)
                    monsterEntity = entity
                    loadedModelFile = modelFile
                    
                    // Create glow sphere around monster
                    createGlowEffect(around: entity)
                    
                    print("[MonsterAR] Loaded model: \(modelFile)")
                }
            } catch {
                print("[MonsterAR] Failed to load \(modelFile): \(error)")
                
                // Fallback: create colored sphere
                await MainActor.run {
                    let fallback = createFallbackEntity()
                    anchorEntity?.addChild(fallback)
                    monsterEntity = fallback
                    loadedModelFile = modelFile
                }
            }
        }
    }
    
    // MARK: - Glow Effect
    
    private func createGlowEffect(around entity: Entity) {
        guard let mapping = monsterAR.currentMonster else { return }
        
        let glowMesh = MeshResource.generateSphere(radius: 0.6)
        var glowMaterial = UnlitMaterial()
        let color = mapping.emissiveColor
        glowMaterial.color = .init(
            tint: UIColor(
                red: CGFloat(color[0]),
                green: CGFloat(color[1]),
                blue: CGFloat(color[2]),
                alpha: 0.15
            )
        )
        
        let glow = ModelEntity(mesh: glowMesh, materials: [glowMaterial])
        glow.position = entity.position
        
        // Pulsing animation via scale
        glow.scale = SIMD3<Float>(repeating: 1.0)
        
        anchorEntity?.addChild(glow)
        glowEntity = glow
    }
    
    private func updateGlowIntensity(_ intensity: Float) {
        guard let glow = glowEntity else { return }
        // Scale glow based on emotional intensity
        let scale = 0.8 + intensity * 0.6 // 0.8 ~ 1.4
        glow.scale = SIMD3<Float>(repeating: scale)
    }
    
    // MARK: - Fallback
    
    private func createFallbackEntity() -> ModelEntity {
        let mapping = monsterAR.currentMonster
        let color = mapping?.emissiveColor ?? [1, 1, 1]
        
        let mesh = MeshResource.generateSphere(radius: 0.3)
        var material = PhysicallyBasedMaterial()
        material.baseColor = .init(tint: UIColor(
            red: CGFloat(color[0]),
            green: CGFloat(color[1]),
            blue: CGFloat(color[2]),
            alpha: 1.0
        ))
        material.emissiveColor = .init(color: UIColor(
            red: CGFloat(color[0]),
            green: CGFloat(color[1]),
            blue: CGFloat(color[2]),
            alpha: 1.0
        ))
        material.emissiveIntensity = 800
        
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = SIMD3<Float>(0, -0.3, -2.0)
        entity.scale = SIMD3<Float>(repeating: mapping?.scale ?? 0.5)
        
        // Add collision for tap gesture
        entity.generateCollisionShapes(recursive: false)
        entity.components.set(InputTargetComponent())
        
        return entity
    }
    
    // MARK: - Update Display
    
    private func updateMonsterDisplay() {
        guard let entity = monsterEntity, let mapping = monsterAR.currentMonster else { return }
        
        // Update opacity (for fade transitions)
        let opacity = monsterAR.monsterOpacity
        // RealityKit doesn't have direct opacity, but we can scale to simulate
        if opacity < 0.01 {
            entity.isEnabled = false
            glowEntity?.isEnabled = false
        } else {
            entity.isEnabled = true
            glowEntity?.isEnabled = true
            
            // Breathing animation: subtle scale pulse based on intensity
            let breathScale = mapping.scale * (1.0 + sin(Float(Date().timeIntervalSince1970) * 2) * 0.02 * monsterAR.emotionIntensity)
            entity.scale = SIMD3<Float>(repeating: breathScale)
        }
    }
    
    // MARK: - Test
    
    private let testEmotions = ["excited", "calm", "anxious", "lonely", "happy", "startled", "bored", "curious"]
    @State private var testIndex = 0
    
    private func cycleTestEmotion() {
        let emotion = testEmotions[testIndex % testEmotions.count]
        testIndex += 1
        monsterAR.testEmotion(emotion)
    }
    
    // MARK: - Info Overlay
    
    private var monsterInfoOverlay: some View {
        Group {
            if let monster = monsterAR.currentMonster {
                VStack(spacing: 8) {
                    HStack(spacing: 12) {
                        // Emotion indicator
                        Text(emotionEmoji(monsterAR.currentEmotion))
                            .font(.largeTitle)
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text(monster.monsterName)
                                .font(.title3)
                                .bold()
                            
                            HStack {
                                Text("属性: \(monster.element)")
                                    .font(.caption)
                                Text("感情: \(monsterAR.currentEmotion)")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                    
                    // Intensity bar
                    HStack {
                        Text("強度")
                            .font(.caption2)
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 4)
                                    .fill(Color.gray.opacity(0.3))
                                RoundedRectangle(cornerRadius: 4)
                                    .fill(elementColor(monster.element))
                                    .frame(width: geo.size.width * CGFloat(monsterAR.emotionIntensity))
                            }
                        }
                        .frame(height: 8)
                    }
                    .frame(width: 200)
                }
                .padding(16)
                .background(.ultraThinMaterial)
                .cornerRadius(16)
            } else {
                HStack {
                    Circle()
                        .fill(monsterAR.isConnected ? .green : .red)
                        .frame(width: 8, height: 8)
                    Text(monsterAR.isConnected ? "感情待機中..." : "MQTT未接続")
                        .font(.caption)
                }
                .padding(12)
                .background(.ultraThinMaterial)
                .cornerRadius(12)
            }
        }
    }
    
    private func emotionEmoji(_ emotion: String) -> String {
        switch emotion {
        case "excited": return "🔥"
        case "happy": return "😊"
        case "anxious": return "⚡"
        case "startled": return "💥"
        case "calm": return "❄️"
        case "bored": return "😪"
        case "lonely": return "🌑"
        case "curious": return "🔮"
        default: return "🐱"
        }
    }
    
    private func elementColor(_ element: String) -> Color {
        switch element {
        case "火": return .orange
        case "雷": return .yellow
        case "氷": return .cyan
        case "闇": return .purple
        default: return .white
        }
    }
}
