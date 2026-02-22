import SwiftUI
import RealityKit

/// Vision Pro AR空間にパルの感情パーティクルを表示するビュー
struct EmotionParticleView: View {
    @EnvironmentObject var effectController: EmotionEffectController
    @State private var particleEntity: Entity?
    @State private var postProcessEntity: Entity?
    
    var body: some View {
        RealityView { content in
            // パーティクル用のアンカー（頭の前方1.5m）
            let anchor = AnchorEntity(.head)
            
            // パーティクルエミッターのコンテナ
            let container = Entity()
            container.name = "emotionParticles"
            container.position = [0, 0, -1.5]  // 前方1.5m
            
            // 初期パーティクル（calm: fireflies）
            let emitter = createParticleEntity(preset: .fireflies, effect: nil)
            container.addChild(emitter)
            
            anchor.addChild(container)
            content.add(anchor)
            
            particleEntity = emitter
            
            // 環境光エフェクト用（ポストプロセスの代替）
            let ambientSphere = createAmbientSphere()
            container.addChild(ambientSphere)
            postProcessEntity = ambientSphere
            
        } update: { content in
            // エフェクト更新
            guard let effect = effectController.currentEffect else { return }
            updateParticles(effect: effect)
            updateAmbient(effect: effect)
        }
    }
    
    // MARK: - Particle Creation
    
    private func createParticleEntity(preset: ParticlePreset, effect: EmotionEffect?) -> Entity {
        let entity = Entity()
        entity.name = "particleEmitter"
        
        var emitter = ParticleEmitterComponent()
        
        // 基本設定
        emitter.timing = .repeating(warmUp: 0.5, emit: ParticleEmitterComponent.Timing.VariableDuration(duration: 100))
        emitter.emitterShape = .sphere
        emitter.emitterShapeSize = [2, 2, 2]  // 2m sphere around viewer
        emitter.birthLocation = .volume
        
        // パーティクル外観
        let pe = effect?.particles
        let density = pe?.density ?? 0.3
        let speed = pe?.speed ?? 0.5
        let size = pe?.size ?? 0.015
        let gravity = pe?.gravity ?? -0.05
        
        emitter.mainEmitter.birthRate = Float(density * 100 * preset.birthRateMultiplier)
        emitter.mainEmitter.lifeSpan = Double(3.0 / max(speed, 0.1))
        emitter.mainEmitter.size = size
        emitter.mainEmitter.sizeVariation = size * 0.5
        
        // 速度
        emitter.speed = speed * 0.3
        emitter.speedVariation = speed * 0.15
        
        // 色
        let color = pe?.color ?? [1, 1, 1, 0.5]
        let r = CGFloat(color.count > 0 ? color[0] : 1)
        let g = CGFloat(color.count > 1 ? color[1] : 1)
        let b = CGFloat(color.count > 2 ? color[2] : 1)
        let a = CGFloat(color.count > 3 ? color[3] : 0.5)
        
        emitter.mainEmitter.color = .constant(.single(
            UIColor(red: r, green: g, blue: b, alpha: a)
        ))
        
        // 重力（負=浮く、正=落ちる）
        emitter.mainEmitter.acceleration = [0, gravity * -9.8, 0]
        
        // ブレンドモード（光系はadditive）
        switch preset {
        case .sparkles, .stars, .fireflies, .embers:
            emitter.mainEmitter.blendMode = .additive
        default:
            emitter.mainEmitter.blendMode = .alpha
        }
        
        // 回転（花びら・雪）
        if preset.shouldRotate {
            emitter.mainEmitter.angularSpeed = Float.random(in: 0.5...2.0)
        }
        
        // フェードイン・アウト
        emitter.mainEmitter.opacityCurve = .linearFadeIn
        
        entity.components[ParticleEmitterComponent.self] = emitter
        return entity
    }
    
    // MARK: - Ambient Sphere (Post-Process substitute)
    
    private func createAmbientSphere() -> Entity {
        // 大きな半透明球体で環境色を表現
        let mesh = MeshResource.generateSphere(radius: 5)
        var material = UnlitMaterial()
        material.color = .init(tint: .clear)
        material.blending = .transparent(opacity: 0)
        
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.name = "ambientSphere"
        entity.scale = [-1, 1, 1]  // 内側を向く
        return entity
    }
    
    // MARK: - Updates
    
    private func updateParticles(effect: EmotionEffect) {
        guard let entity = particleEntity,
              var emitter = entity.components[ParticleEmitterComponent.self] else { return }
        
        let pe = effect.particles
        let preset = ParticlePreset(rawValue: pe.type) ?? .fireflies
        
        // パラメータ更新
        emitter.mainEmitter.birthRate = pe.density * 100 * preset.birthRateMultiplier
        emitter.mainEmitter.size = pe.size
        emitter.mainEmitter.sizeVariation = pe.size * 0.5
        emitter.speed = pe.speed * 0.3
        emitter.mainEmitter.acceleration = [0, pe.gravity * -9.8, 0]
        emitter.emitterShapeSize = SIMD3<Float>(repeating: pe.spread * 2)
        
        // 色
        if pe.color.count >= 4 {
            let color = UIColor(
                red: CGFloat(pe.color[0]),
                green: CGFloat(pe.color[1]),
                blue: CGFloat(pe.color[2]),
                alpha: CGFloat(pe.color[3])
            )
            emitter.mainEmitter.color = .constant(.single(color))
        }
        
        // ブレンドモード
        switch preset {
        case .sparkles, .stars, .fireflies, .embers:
            emitter.mainEmitter.blendMode = .additive
        default:
            emitter.mainEmitter.blendMode = .alpha
        }
        
        entity.components[ParticleEmitterComponent.self] = emitter
    }
    
    private func updateAmbient(effect: EmotionEffect) {
        guard let entity = postProcessEntity as? ModelEntity else { return }
        
        let ambient = effect.ambient
        let pp = effect.postProcess
        
        // 環境色 = ポストプロセスの色 × intensity + ambient colorShift
        let ppColor = pp.color.count >= 3 ? pp.color : [1, 1, 1]
        let shift = ambient.colorShift.count >= 3 ? ambient.colorShift : [0, 0, 0]
        
        let r = CGFloat((ppColor[0] + shift[0]) * pp.intensity * 0.3)
        let g = CGFloat((ppColor[1] + shift[1]) * pp.intensity * 0.3)
        let b = CGFloat((ppColor[2] + shift[2]) * pp.intensity * 0.3)
        let fogAlpha = CGFloat(ambient.fog * 0.15)  // 霧は控えめに
        
        var material = UnlitMaterial()
        
        switch pp.type {
        case "warmGlow":
            material.color = .init(tint: UIColor(red: r, green: g, blue: b, alpha: fogAlpha + 0.02))
        case "coolFog":
            material.color = .init(tint: UIColor(red: 0.5, green: 0.6, blue: 0.8, alpha: fogAlpha + 0.05))
        case "vignette":
            // ビネットは球体の端を暗くする（簡易実装）
            material.color = .init(tint: UIColor(red: 0, green: 0, blue: 0, alpha: CGFloat(pp.intensity * 0.1)))
        default:
            material.color = .init(tint: .clear)
        }
        
        material.blending = .transparent(opacity: .init(floatLiteral: Double(min(fogAlpha + 0.02, 0.2))))
        entity.model?.materials = [material]
    }
}

// MARK: - Status Overlay

struct EmotionEffectOverlay: View {
    @EnvironmentObject var effectController: EmotionEffectController
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Circle()
                    .fill(effectController.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text("Effect Engine")
                    .font(.caption)
            }
            
            if let effect = effectController.currentEffect {
                Text("💭 \(effectController.currentEmotion)")
                    .font(.headline)
                
                HStack {
                    Text("🎆 \(effect.particles.type)")
                    Text("🌈 \(effect.postProcess.type)")
                }
                .font(.caption)
                
                // 色プレビュー
                if effect.particles.color.count >= 3 {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color(
                            red: Double(effect.particles.color[0]),
                            green: Double(effect.particles.color[1]),
                            blue: Double(effect.particles.color[2])
                        ))
                        .frame(width: 60, height: 12)
                }
            } else {
                Text("待機中...")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .cornerRadius(12)
    }
}

// MARK: - Preview

#Preview {
    EmotionEffectOverlay()
        .environmentObject(EmotionEffectController())
}
