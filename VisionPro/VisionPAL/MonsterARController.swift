import Foundation
import SwiftUI
import Combine
import CocoaMQTT

// MARK: - Emotion → Monster Mapping

struct MonsterMapping {
    let emotion: String
    let monsterName: String      // Display name
    let modelFile: String        // USDZ filename in bundle (without extension)
    let element: String          // 属性
    let emissiveColor: [Float]   // RGB for glow effect
    let scale: Float             // Model scale
}

// MARK: - Monster AR Controller

class MonsterARController: ObservableObject {
    // Published state
    @Published var currentEmotion: String = ""
    @Published var currentMonster: MonsterMapping?
    @Published var isConnected = false
    @Published var shouldShowMonster = false
    @Published var monsterOpacity: Float = 0.0  // For fade transitions
    @Published var emotionIntensity: Float = 0.5 // arousal level
    
    // MQTT
    private var mqtt: CocoaMQTT?
    private let affectTopic = "vision_pal/affect/state"
    private let sceneTopic = "vision_pal/perception/scene"
    
    // Mapping table
    static let mappings: [String: MonsterMapping] = [
        "excited": MonsterMapping(
            emotion: "excited", monsterName: "フレイムキャット",
            modelFile: "fire_cat", element: "火",
            emissiveColor: [1.0, 0.4, 0.0], scale: 0.5
        ),
        "happy": MonsterMapping(
            emotion: "happy", monsterName: "フレイムキャット",
            modelFile: "fire_cat", element: "火",
            emissiveColor: [1.0, 0.6, 0.1], scale: 0.45
        ),
        "anxious": MonsterMapping(
            emotion: "anxious", monsterName: "サンダーキャット",
            modelFile: "thunder_cat", element: "雷",
            emissiveColor: [1.0, 1.0, 0.2], scale: 0.5
        ),
        "startled": MonsterMapping(
            emotion: "startled", monsterName: "サンダーキャット",
            modelFile: "thunder_cat", element: "雷",
            emissiveColor: [0.8, 0.8, 1.0], scale: 0.55
        ),
        "calm": MonsterMapping(
            emotion: "calm", monsterName: "アイスクリスタルキャット",
            modelFile: "ice_cat", element: "氷",
            emissiveColor: [0.5, 0.8, 1.0], scale: 0.45
        ),
        "bored": MonsterMapping(
            emotion: "bored", monsterName: "アイスクリスタルキャット",
            modelFile: "ice_cat", element: "氷",
            emissiveColor: [0.6, 0.7, 0.9], scale: 0.4
        ),
        "lonely": MonsterMapping(
            emotion: "lonely", monsterName: "シャドウキャット",
            modelFile: "shadow_cat", element: "闇",
            emissiveColor: [0.5, 0.0, 0.8], scale: 0.5
        ),
        "curious": MonsterMapping(
            emotion: "curious", monsterName: "シャドウキャット",
            modelFile: "shadow_cat", element: "闇",
            emissiveColor: [0.3, 0.1, 0.6], scale: 0.45
        ),
    ]
    
    let mqttHost: String
    let mqttPort: UInt16
    private var lastEmotionChange = Date()
    private let minChangeInterval: TimeInterval = 3.0 // 最低3秒は同じモンスター表示
    
    init(mqttHost: String = "192.168.3.5", mqttPort: UInt16 = 1883) {
        self.mqttHost = mqttHost
        self.mqttPort = mqttPort
        setupMQTT()
    }
    
    // MARK: - MQTT
    
    private func setupMQTT() {
        let clientID = "VisionPAL-MonsterAR-\(ProcessInfo.processInfo.processIdentifier)"
        mqtt = CocoaMQTT(clientID: clientID, host: mqttHost, port: mqttPort)
        mqtt?.keepAlive = 30
        mqtt?.autoReconnect = true
        
        mqtt?.didConnectAck = { [weak self] _, ack in
            if ack == .accept {
                DispatchQueue.main.async { self?.isConnected = true }
                self?.mqtt?.subscribe(self?.affectTopic ?? "", qos: .qos1)
                print("[MonsterAR] MQTT connected, subscribed to affect")
            }
        }
        
        mqtt?.didDisconnect = { [weak self] _, _ in
            DispatchQueue.main.async { self?.isConnected = false }
        }
        
        mqtt?.didReceiveMessage = { [weak self] _, message, _ in
            self?.handleMessage(topic: message.topic, payload: message.string ?? "")
        }
        
        _ = mqtt?.connect()
    }
    
    private func handleMessage(topic: String, payload: String) {
        guard let data = payload.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        
        if topic == affectTopic {
            if let emotion = dict["emotion"] as? String {
                let arousal = (dict["arousal"] as? Double) ?? 0.5
                updateEmotion(emotion, intensity: Float(arousal))
            }
        }
    }
    
    // MARK: - Emotion Update
    
    private func updateEmotion(_ emotion: String, intensity: Float) {
        // Debounce: don't switch too fast
        guard Date().timeIntervalSince(lastEmotionChange) > minChangeInterval else { return }
        guard emotion != currentEmotion else {
            // Same emotion, just update intensity
            DispatchQueue.main.async { self.emotionIntensity = intensity }
            return
        }
        
        lastEmotionChange = Date()
        
        DispatchQueue.main.async {
            let oldMonsterFile = self.currentMonster?.modelFile
            self.currentEmotion = emotion
            self.emotionIntensity = intensity
            
            if let mapping = Self.mappings[emotion] {
                // Only do full transition if model actually changes
                if mapping.modelFile != oldMonsterFile {
                    // Fade out → switch → fade in
                    withAnimation(.easeOut(duration: 0.5)) {
                        self.monsterOpacity = 0.0
                    }
                    
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        self.currentMonster = mapping
                        self.shouldShowMonster = true
                        withAnimation(.easeIn(duration: 0.8)) {
                            self.monsterOpacity = 1.0
                        }
                    }
                } else {
                    // Same model, different emotion variant — just update glow
                    self.currentMonster = mapping
                }
                
                print("[MonsterAR] 🐱 \(emotion) → \(mapping.monsterName) (\(mapping.element))")
            } else {
                // Unknown emotion — hide monster
                withAnimation(.easeOut(duration: 0.5)) {
                    self.monsterOpacity = 0.0
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    self.shouldShowMonster = false
                    self.currentMonster = nil
                }
            }
        }
    }
    
    // MARK: - Manual trigger (for testing)
    
    func testEmotion(_ emotion: String) {
        lastEmotionChange = .distantPast // bypass debounce
        updateEmotion(emotion, intensity: 0.7)
    }
    
    func disconnect() {
        mqtt?.disconnect()
    }
    
    deinit { disconnect() }
}
