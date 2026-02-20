import SwiftUI
import RealityKit
import ARKit

/// 3DGS scene viewer with tap-to-ripple interaction
/// Loads .ply files via MetalSplatter and adds ripple post-process effect
struct SplatSceneView: View {
    @EnvironmentObject var robot: RobotController
    
    @State private var splatEntity: Entity?
    @State private var isLoading = false
    @State private var loadError: String?
    @State private var lastScanTime: Date?
    
    /// URL of the SHARP server (PC)
    let sharpServerURL: URL
    
    var body: some View {
        ZStack {
            // 3D Scene
            RealityView { content in
                // Ambient light
                let light = PointLight()
                light.light.intensity = 1000
                light.position = [0, 1, -1]
                content.add(light)
            } update: { content in
                // Update when splatEntity changes
                if let entity = splatEntity {
                    // Remove previous splat entities
                    content.entities
                        .filter { $0.name == "splatScene" }
                        .forEach { $0.removeFromParent() }
                    
                    entity.name = "splatScene"
                    // Position the 3DGS scene in front of user
                    entity.position = [0, 1.2, -1.5]
                    entity.scale = [0.5, 0.5, 0.5]  // Adjust based on scene size
                    content.add(entity)
                }
            }
            .gesture(
                SpatialTapGesture()
                    .targetedToAnyEntity()
                    .onEnded { value in
                        handleTap(value)
                    }
            )
            
            // UI Overlay
            VStack {
                Spacer()
                
                HStack(spacing: 20) {
                    // Scan button
                    Button {
                        Task { await performScan() }
                    } label: {
                        HStack {
                            Image(systemName: "viewfinder")
                            Text("3D Scan")
                        }
                        .padding(.horizontal, 20)
                        .padding(.vertical, 12)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.cyan)
                    .disabled(isLoading)
                    
                    // Status
                    if isLoading {
                        ProgressView()
                            .progressViewStyle(.circular)
                        Text("Generating 3DGS...")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    
                    if let time = lastScanTime {
                        Text("Last: \(time.formatted(.dateTime.hour().minute().second()))")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
                .background(.ultraThinMaterial)
                .cornerRadius(16)
                .padding(.bottom, 40)
            }
            
            // Error overlay
            if let error = loadError {
                Text("Error: \(error)")
                    .font(.caption)
                    .foregroundColor(.red)
                    .padding(8)
                    .background(.ultraThinMaterial)
                    .cornerRadius(8)
                    .transition(.opacity)
            }
        }
    }
    
    // MARK: - 3D Scan Pipeline
    
    /// Capture current JetBot camera frame → SHARP → Load .ply
    private func performScan() async {
        isLoading = true
        loadError = nil
        
        do {
            // 1. Capture snapshot from JetBot MJPEG
            let snapURL = robot.cameraURL
                .deletingLastPathComponent()
                .appendingPathComponent("snap")
            
            let (imageData, _) = try await URLSession.shared.data(from: snapURL)
            
            // 2. Send to SHARP server for 3DGS generation
            var request = URLRequest(url: sharpServerURL.appendingPathComponent("generate"))
            request.httpMethod = "POST"
            request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            request.httpBody = imageData
            request.timeoutInterval = 30  // SHARP takes ~4-6 seconds
            
            let (plyData, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                throw ScanError.serverError("SHARP server returned error")
            }
            
            // 3. Save .ply to temporary file
            let tempURL = FileManager.default.temporaryDirectory
                .appendingPathComponent("scan_\(Int(Date().timeIntervalSince1970)).ply")
            try plyData.write(to: tempURL)
            
            // 4. Load into RealityKit via MetalSplatter
            // Note: MetalSplatter integration — load the .ply as a ModelEntity
            // This requires MetalSplatter SPM package to be added to the project
            await MainActor.run {
                // Placeholder: MetalSplatter loading
                // let splatModel = try? SplatRenderer.loadPLY(url: tempURL)
                // splatEntity = splatModel?.entity
                
                lastScanTime = Date()
                isLoading = false
                print("[Scan] 3DGS generated: \(plyData.count) bytes")
            }
            
        } catch {
            await MainActor.run {
                loadError = error.localizedDescription
                isLoading = false
            }
        }
    }
    
    // MARK: - Tap Handling
    
    private func handleTap(_ value: EntityTargetValue<SpatialTapGesture.Value>) {
        // Get tap position in world coordinates
        let worldPos = value.convert(value.location3D, from: .local, to: .scene)
        
        print("[Ripple] Tap at world position: \(worldPos)")
        
        // Create ripple visual effect at tap point
        if let entity = value.entity.parent ?? value.entity.scene?.findEntity(named: "splatScene") {
            spawnRippleEntity(at: worldPos, on: entity)
        }
    }
    
    /// Spawn a visual ripple ring entity at the tap position
    private func spawnRippleEntity(at position: SIMD3<Float>, on parent: Entity) {
        // Create expanding ring using RealityKit mesh
        let ringEntity = Entity()
        ringEntity.position = position
        
        // Start with a small torus, animate to large
        let mesh = MeshResource.generateSphere(radius: 0.01)
        var material = UnlitMaterial()
        material.color = .init(tint: .init(red: 0.4, green: 0.85, blue: 1.0, alpha: 0.8))
        
        let modelComponent = ModelComponent(mesh: mesh, materials: [material])
        ringEntity.components.set(modelComponent)
        
        parent.addChild(ringEntity)
        
        // Animate: scale up + fade out
        animateRipple(entity: ringEntity, duration: 1.5)
    }
    
    /// Animate ripple expansion and fade
    private func animateRipple(entity: Entity, duration: TimeInterval) {
        Task {
            let steps = 30
            let stepDuration = duration / Double(steps)
            
            for i in 0...steps {
                let t = Float(i) / Float(steps)
                let scale = 0.01 + t * 2.0  // Expand from tiny to 2m radius
                let alpha = 1.0 - t * t      // Quadratic fade out
                
                await MainActor.run {
                    entity.scale = [scale, scale, scale]
                    
                    // Update material opacity
                    if var model = entity.components[ModelComponent.self] {
                        var material = UnlitMaterial()
                        material.color = .init(tint: .init(
                            red: 0.4, green: 0.85, blue: 1.0,
                            alpha: alpha
                        ))
                        model.materials = [material]
                        entity.components.set(model)
                    }
                }
                
                try? await Task.sleep(nanoseconds: UInt64(stepDuration * 1_000_000_000))
            }
            
            // Remove after animation
            await MainActor.run {
                entity.removeFromParent()
            }
        }
    }
}

// MARK: - Errors

enum ScanError: LocalizedError {
    case serverError(String)
    case invalidResponse
    
    var errorDescription: String? {
        switch self {
        case .serverError(let msg): return msg
        case .invalidResponse: return "Invalid response from SHARP server"
        }
    }
}

// MARK: - Preview

#Preview(windowStyle: .volumetric) {
    SplatSceneView(sharpServerURL: URL(string: "http://192.168.3.5:8080")!)
        .environmentObject(RobotController())
}
