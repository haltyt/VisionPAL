import SwiftUI

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
    }
}
