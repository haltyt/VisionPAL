import SwiftUI

@main
struct VisionPALApp: App {
    @StateObject private var robotController = RobotController()
    @StateObject private var voiceStyleController = VoiceStyleController()
    @StateObject private var effectController = EmotionEffectController()
    @StateObject private var battleController = BattleController()
    @StateObject private var monsterARController = MonsterARController()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(robotController)
                .environmentObject(voiceStyleController)
                .environmentObject(effectController)
                .environmentObject(battleController)
                .environmentObject(monsterARController)
        }
        
        // Battle window (open separately)
        WindowGroup(id: "BattleWindow") {
            BattleView()
                .environmentObject(battleController)
                .environmentObject(robotController)
        }
        .defaultSize(width: 900, height: 600)
        
        ImmersiveSpace(id: "ImmersiveControl") {
            ImmersiveControlView()
                .environmentObject(robotController)
                .environmentObject(effectController)
        }
        .immersionStyle(selection: .constant(.progressive), in: .progressive)
        
        ImmersiveSpace(id: "EmotionEffect") {
            EmotionParticleView()
                .environmentObject(effectController)
        }
        .immersionStyle(selection: .constant(.mixed), in: .mixed)
        
        // AR Battle immersive space
        ImmersiveSpace(id: "BattleArena") {
            BattleImmersiveView()
                .environmentObject(battleController)
        }
        .immersionStyle(selection: .constant(.mixed), in: .mixed)
        
        // Emotion Monster AR — 感情に応じたモンスター出現
        ImmersiveSpace(id: "EmotionMonster") {
            MonsterARView()
                .environmentObject(monsterARController)
        }
        .immersionStyle(selection: .constant(.mixed), in: .mixed)
    }
}
