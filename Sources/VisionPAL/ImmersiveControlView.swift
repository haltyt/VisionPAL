import SwiftUI
import RealityKit
import ARKit

struct ImmersiveControlView: View {
    @EnvironmentObject var robot: RobotController
    @State private var session = ARKitSession()
    @State private var worldTracking = WorldTrackingProvider()
    @State private var isTracking = false
    
    var body: some View {
        RealityView { content in
            // 空間にステータス表示用のアンカーを配置
            let anchor = AnchorEntity(.head)
            content.add(anchor)
        }
        .task {
            await startHeadTracking()
        }
        .onDisappear {
            robot.move(direction: .stop)
        }
    }
    
    private func startHeadTracking() async {
        do {
            try await session.run([worldTracking])
            isTracking = true
            print("[AR] Head tracking started")
            
            // トラッキングループ
            while isTracking {
                if let deviceAnchor = worldTracking.queryDeviceAnchor(atTimestamp: CACurrentMediaTime()) {
                    let transform = deviceAnchor.originFromAnchorTransform
                    
                    // 回転行列からyaw（左右）とpitch（上下）を抽出
                    let column2 = transform.columns.2
                    let yaw = atan2(column2.x, column2.z)    // 左右の向き
                    let pitch = asin(-column2.y)              // 上下の向き
                    
                    await MainActor.run {
                        robot.updateFromHeadTracking(yaw: yaw, pitch: pitch)
                    }
                }
                
                // 10Hz でポーリング（100ms間隔）
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
        } catch {
            print("[AR] Head tracking failed: \(error)")
        }
    }
}
