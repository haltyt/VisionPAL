import Foundation
import Combine
import CocoaMQTT

// MARK: - Effect Data Models

struct ParticleEffect: Codable {
    var type: String        // sparkles, fireflies, snowfall, bubbles, embers, storm, petals, dust, stars, rain
    var density: Float
    var speed: Float
    var color: [Float]      // [R, G, B, A]
    var size: Float
    var gravity: Float
    var spread: Float
}

struct PostProcessEffect: Codable {
    var type: String        // warmGlow, coolFog, vignette, chromatic, ripple, blur, none
    var intensity: Float
    var color: [Float]      // [R, G, B]
}

struct AmbientEffect: Codable {
    var colorShift: [Float] // [R, G, B] shift
    var brightness: Float
    var fog: Float
}

struct EmotionEffect: Codable {
    var particles: ParticleEffect
    var postProcess: PostProcessEffect
    var ambient: AmbientEffect
}

struct EffectMessage: Codable {
    var effect: EmotionEffect
    var emotion: String
    var timestamp: Double
}

// MARK: - Particle Type Mapping

enum ParticlePreset: String, CaseIterable {
    case sparkles, fireflies, snowfall, bubbles, embers, storm, petals, dust, stars, rain
    
    /// Base particle image name (SF Symbol or custom asset)
    var imageName: String {
        switch self {
        case .sparkles:  return "sparkle"
        case .fireflies: return "circle.fill"
        case .snowfall:  return "snowflake"
        case .bubbles:   return "circle"
        case .embers:    return "flame.fill"
        case .storm:     return "cloud.bolt.fill"
        case .petals:    return "leaf.fill"
        case .dust:      return "circle.fill"
        case .stars:     return "star.fill"
        case .rain:      return "drop.fill"
        }
    }
    
    /// Whether particles should rotate
    var shouldRotate: Bool {
        switch self {
        case .petals, .snowfall: return true
        default: return false
        }
    }
    
    /// Birth rate multiplier (base = density * 100)
    var birthRateMultiplier: Float {
        switch self {
        case .rain, .storm: return 3.0
        case .sparkles, .stars: return 2.0
        case .fireflies: return 0.5
        default: return 1.0
        }
    }
}

// MARK: - Effect Controller

class EmotionEffectController: ObservableObject {
    // Published state for SwiftUI
    @Published var currentEffect: EmotionEffect?
    @Published var currentEmotion: String = ""
    @Published var isConnected = false
    
    // Interpolated values (for smooth transitions)
    @Published var displayParticleColor: [Float] = [1, 1, 1, 0.5]
    @Published var displayBrightness: Float = 1.0
    @Published var displayFog: Float = 0.0
    @Published var displayPostProcessIntensity: Float = 0.0
    
    // MQTT
    private var mqtt: CocoaMQTT?
    private let effectTopic = "vision_pal/effect"
    private let affectTopic = "vision_pal/affect/state"
    
    // Interpolation
    private var targetEffect: EmotionEffect?
    private var interpolationTimer: Timer?
    private let interpolationSpeed: Float = 0.05  // 5% per tick toward target
    
    // Config
    let mqttHost: String
    let mqttPort: UInt16
    
    init(mqttHost: String = "192.168.3.5", mqttPort: UInt16 = 1883) {
        self.mqttHost = mqttHost
        self.mqttPort = mqttPort
        setupMQTT()
        startInterpolation()
    }
    
    deinit {
        interpolationTimer?.invalidate()
        mqtt?.disconnect()
    }
    
    // MARK: - MQTT
    
    private func setupMQTT() {
        let clientID = "VisionPAL-Effect-\(ProcessInfo.processInfo.processIdentifier)"
        mqtt = CocoaMQTT(clientID: clientID, host: mqttHost, port: mqttPort)
        mqtt?.keepAlive = 30
        mqtt?.autoReconnect = true
        
        mqtt?.didConnectAck = { [weak self] _, ack in
            if ack == .accept {
                DispatchQueue.main.async { self?.isConnected = true }
                self?.mqtt?.subscribe(self?.effectTopic ?? "", qos: .qos1)
                self?.mqtt?.subscribe(self?.affectTopic ?? "", qos: .qos0)
                print("[Effect] MQTT connected, subscribed to \(self?.effectTopic ?? "")")
            }
        }
        
        mqtt?.didDisconnect = { [weak self] _, _ in
            DispatchQueue.main.async { self?.isConnected = false }
            print("[Effect] MQTT disconnected")
        }
        
        mqtt?.didReceiveMessage = { [weak self] _, message, _ in
            self?.handleMessage(topic: message.topic, payload: message.string ?? "")
        }
        
        _ = mqtt?.connect()
    }
    
    private func handleMessage(topic: String, payload: String) {
        guard let data = payload.data(using: .utf8) else { return }
        
        if topic == effectTopic {
            do {
                let msg = try JSONDecoder().decode(EffectMessage.self, from: data)
                DispatchQueue.main.async {
                    self.targetEffect = msg.effect
                    self.currentEffect = msg.effect
                    self.currentEmotion = msg.emotion
                    print("[Effect] 🎨 \(msg.emotion) → \(msg.effect.particles.type) + \(msg.effect.postProcess.type)")
                }
            } catch {
                print("[Effect] Parse error: \(error)")
            }
        }
    }
    
    // MARK: - Smooth Interpolation
    
    private func startInterpolation() {
        interpolationTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            self?.interpolateStep()
        }
    }
    
    private func interpolateStep() {
        guard let target = targetEffect else { return }
        
        let speed = interpolationSpeed
        
        // Interpolate particle color
        if displayParticleColor.count == 4 && target.particles.color.count == 4 {
            for i in 0..<4 {
                displayParticleColor[i] += (target.particles.color[i] - displayParticleColor[i]) * speed
            }
        }
        
        // Interpolate ambient
        displayBrightness += (target.ambient.brightness - displayBrightness) * speed
        displayFog += (target.ambient.fog - displayFog) * speed
        displayPostProcessIntensity += (target.postProcess.intensity - displayPostProcessIntensity) * speed
    }
    
    // MARK: - Convenience
    
    var particlePreset: ParticlePreset {
        guard let effect = currentEffect else { return .fireflies }
        return ParticlePreset(rawValue: effect.particles.type) ?? .fireflies
    }
    
    var postProcessType: String {
        currentEffect?.postProcess.type ?? "none"
    }
}
