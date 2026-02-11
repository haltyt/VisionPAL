import SwiftUI

struct ContentView: View {
    @EnvironmentObject var robot: RobotController
    @Environment(\.openImmersiveSpace) var openImmersiveSpace
    @Environment(\.dismissImmersiveSpace) var dismissImmersiveSpace
    @State private var isImmersive = false
    
    var body: some View {
        VStack(spacing: 30) {
            // Header
            Text("Vision PAL 🐾")
                .font(.largeTitle)
                .bold()
            
            // Connection Status
            HStack {
                Circle()
                    .fill(robot.isConnected ? .green : .red)
                    .frame(width: 12, height: 12)
                Text(robot.isConnected ? "Connected" : "Disconnected")
                    .foregroundColor(.secondary)
            }
            
            // Camera Feed
            MJPEGView(url: robot.cameraURL)
                .frame(width: 640, height: 480)
                .cornerRadius(16)
                .shadow(radius: 10)
            
            // Manual Controls (for testing)
            VStack(spacing: 16) {
                Text("Manual Control")
                    .font(.headline)
                
                // Direction buttons
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
            
            // Immersive Mode Toggle
            Toggle("🎯 Head Tracking Mode", isOn: $isImmersive)
                .toggleStyle(.button)
                .onChange(of: isImmersive) { _, newValue in
                    Task {
                        if newValue {
                            await openImmersiveSpace(id: "ImmersiveControl")
                        } else {
                            await dismissImmersiveSpace()
                        }
                    }
                }
        }
        .padding(40)
    }
}
