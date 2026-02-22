import SwiftUI

@main
struct VisionPALApp: App {
    @StateObject private var robotController = RobotController()
    @StateObject private var voiceStyleController = VoiceStyleController()
    @StateObject private var effectController = EmotionEffectController()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(robotController)
                .environmentObject(voiceStyleController)
                .environmentObject(effectController)
        }
        
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
    }
}
