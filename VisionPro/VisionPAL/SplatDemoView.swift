import SwiftUI
import CompositorServices
import Metal
import MetalSplatter
import SplatIO
import ARKit
import simd
import UniformTypeIdentifiers
import QuartzCore

// MARK: - SplatDemoView (SwiftUI Entry Point)

/// Standalone 3DGS viewer with tap-to-ripple.
/// Usage: Add MetalSplatter SPM package, bundle a sample .ply, then open this ImmersiveSpace.
struct SplatDemoView: View {
    @State private var isPickingFile = false
    @State private var selectedURL: URL?
    @State private var isImmersiveOpen = false
    
    @Environment(\.openImmersiveSpace) var openImmersiveSpace
    @Environment(\.dismissImmersiveSpace) var dismissImmersiveSpace
    
    var body: some View {
        VStack(spacing: 20) {
            Text("3DGS Viewer 🌐")
                .font(.largeTitle)
                .bold()
            
            // Use bundled sample
            if let sampleURL = Bundle.main.url(forResource: "sample", withExtension: "ply") {
                Button("📦 Load Bundled Sample") {
                    selectedURL = sampleURL
                    openSplatSpace()
                }
                .buttonStyle(.borderedProminent)
                .tint(.cyan)
            }
            
            // File picker
            Button("📂 Open .ply File") {
                isPickingFile = true
            }
            .buttonStyle(.borderedProminent)
            .disabled(isImmersiveOpen)
            .fileImporter(
                isPresented: $isPickingFile,
                allowedContentTypes: [
                    UTType(filenameExtension: "ply") ?? .data,
                    UTType(filenameExtension: "splat") ?? .data,
                    UTType(filenameExtension: "spz") ?? .data,
                ]
            ) {
                isPickingFile = false
                if case .success(let url) = $0 {
                    _ = url.startAccessingSecurityScopedResource()
                    selectedURL = url
                    openSplatSpace()
                }
            }
            
            // Procedural splat test (no file needed)
            Button("🔮 Procedural Splat Test") {
                selectedURL = nil  // Signal procedural mode
                openSplatSpace()
            }
            .buttonStyle(.bordered)
            
            if isImmersiveOpen {
                Button("✕ Close Immersive") {
                    Task {
                        await dismissImmersiveSpace()
                        isImmersiveOpen = false
                    }
                }
                .buttonStyle(.bordered)
                .tint(.red)
            }
            
            Text("Tap the 3D scene to create ripples ✨")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(40)
    }
    
    private func openSplatSpace() {
        Task {
            // Store URL in shared state for the renderer
            SplatDemoState.shared.plyURL = selectedURL
            
            switch await openImmersiveSpace(id: "SplatDemo") {
            case .opened:
                isImmersiveOpen = true
            case .error, .userCancelled:
                break
            @unknown default:
                break
            }
        }
    }
}

// MARK: - Shared State

/// Simple shared state to pass PLY URL to the renderer
@Observable
class SplatDemoState {
    static let shared = SplatDemoState()
    var plyURL: URL?
    var rippleTapPosition: SIMD3<Float>?  // Set by gesture handler
}

// MARK: - SplatDemoRenderer

/// CompositorServices-based renderer for 3DGS with ripple post-process
final class SplatDemoRenderer: @unchecked Sendable {
    let layerRenderer: LayerRenderer
    let device: MTLDevice
    let commandQueue: MTLCommandQueue
    
    private var splatRenderer: SplatRenderer?
    private var rippleManager: RippleEffectManager?
    
    let inFlightSemaphore = DispatchSemaphore(value: 3)

    private var rotation: Float = 0
    private var lastUpdateTime: TimeInterval = 0

    // Gesture state
    private var modelScale: Float = 1.0
    private var modelRotation: simd_quatf = simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)
    private var modelOffset: SIMD3<Float> = .zero

    // Pinch tracking
    private var lastSinglePinchPos: SIMD3<Float>?
    private var lastTwoHandDistance: Float?
    private var lastTwoHandMidpoint: SIMD3<Float>?
    private var lastTwoHandDirection: SIMD3<Float>?

    let arSession = ARKitSession()
    let worldTracking = WorldTrackingProvider()
    let handTracking = HandTrackingProvider()
    
    init(_ layerRenderer: LayerRenderer) {
        self.layerRenderer = layerRenderer
        self.device = layerRenderer.device
        self.commandQueue = device.makeCommandQueue()!
    }
    
    static func startRendering(_ layerRenderer: LayerRenderer) {
        let renderer = SplatDemoRenderer(layerRenderer)
        Task { @MainActor in
            do {
                try await renderer.loadModel()
            } catch {
                print("[SplatDemo] Load error: \(error)")
            }
            renderer.startRenderLoop()
        }
    }
    
    func loadModel() async throws {
        let colorFormat = layerRenderer.configuration.colorFormat
        let depthFormat = layerRenderer.configuration.depthFormat
        let maxViewCount = layerRenderer.properties.viewCount
        
        let splat = try SplatRenderer(
            device: device,
            colorFormat: colorFormat,
            depthFormat: depthFormat,
            sampleCount: 1,
            maxViewCount: maxViewCount,
            maxSimultaneousRenders: 3
        )
        
        if let url = SplatDemoState.shared.plyURL {
            // Load .ply file
            print("[SplatDemo] Loading PLY: \(url.lastPathComponent)")
            let reader = try AutodetectSceneReader(url)
            let points = try await reader.readAll()
            let chunk = try SplatChunk(device: device, from: points)
            await splat.addChunk(chunk)
            print("[SplatDemo] Loaded \(points.count) splats")
        } else {
            // Procedural splat: create a small grid of colored splats
            print("[SplatDemo] Creating procedural splat")
            let points = createProceduralSplats()
            let chunk = try SplatChunk(device: device, from: points)
            await splat.addChunk(chunk)
        }
        
        splatRenderer = splat
        
        // Initialize ripple manager
        rippleManager = RippleEffectManager(
            device: device,
            colorPixelFormat: colorFormat
        )
        
        print("[SplatDemo] Ready to render")
    }
    
    /// Create a simple procedural splat scene for testing without .ply
    private func createProceduralSplats() -> [SplatIO.SplatPoint] {
        var points: [SplatIO.SplatPoint] = []
        let gridSize = 10
        let spacing: Float = 0.15
        let offset = Float(gridSize - 1) * spacing / 2

        for x in 0..<gridSize {
            for y in 0..<gridSize {
                for z in 0..<gridSize {
                    let position = SIMD3<Float>(
                        Float(x) * spacing - offset,
                        Float(y) * spacing - offset,
                        Float(z) * spacing - offset
                    )

                    // Color based on position (convert to UInt8 0-255)
                    let r = UInt8(Float(x) / Float(gridSize) * 255)
                    let g = UInt8(Float(y) / Float(gridSize) * 255)
                    let b = UInt8(Float(z) / Float(gridSize) * 255)

                    let point = SplatIO.SplatPoint(
                        position: position,
                        color: .sRGBUInt8(SIMD3<UInt8>(r, g, b)),
                        opacity: .linearFloat(0.8),
                        scale: .linearFloat(SIMD3<Float>(repeating: 0.02)),
                        rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)
                    )
                    points.append(point)
                }
            }
        }
        return points
    }
    
    nonisolated func startRenderLoop() {
        Task(executorPreference: RendererTaskExecutor.shared) {
            do {
                try await self.arSession.run([self.worldTracking, self.handTracking])
            } catch {
                print("[SplatDemo] ARKit error: \(error)")
            }
            self.renderLoop()
        }
    }

    // MARK: - Pinch Gesture Detection

    private static let pinchThreshold: Float = 0.025  // 2.5cm

    nonisolated private func pinchPosition(for hand: HandAnchor) -> SIMD3<Float>? {
        guard hand.isTracked,
              let thumbTip = hand.handSkeleton?.joint(.thumbTip),
              let indexTip = hand.handSkeleton?.joint(.indexFingerTip),
              thumbTip.isTracked, indexTip.isTracked else { return nil }

        let thumbPos = (hand.originFromAnchorTransform * thumbTip.anchorFromJointTransform).columns.3
        let indexPos = (hand.originFromAnchorTransform * indexTip.anchorFromJointTransform).columns.3

        let thumb3 = SIMD3<Float>(thumbPos.x, thumbPos.y, thumbPos.z)
        let index3 = SIMD3<Float>(indexPos.x, indexPos.y, indexPos.z)
        let dist = simd_distance(thumb3, index3)

        if dist < Self.pinchThreshold {
            // Return midpoint between thumb and index as pinch position
            return (thumb3 + index3) * 0.5
        }
        return nil
    }

    nonisolated private func processHandGestures() {
        let leftAnchor = handTracking.latestAnchors.leftHand
        let rightAnchor = handTracking.latestAnchors.rightHand

        let leftPinch: SIMD3<Float>? = leftAnchor.flatMap { pinchPosition(for: $0) }
        let rightPinch: SIMD3<Float>? = rightAnchor.flatMap { pinchPosition(for: $0) }

        // Two-hand pinch → Rotate (tilt) + Scale (distance)
        if let lp = leftPinch, let rp = rightPinch {
            let currentDist = simd_distance(lp, rp)
            let currentMid = (lp + rp) * 0.5
            let currentDir = simd_normalize(rp - lp)

            if let lastDist = lastTwoHandDistance,
               let lastDir = lastTwoHandDirection {
                // Scale: distance change
                let ratio = currentDist / lastDist
                modelScale *= ratio
                modelScale = max(0.1, min(10.0, modelScale))

                // Rotate: direction change between hands
                let cross = simd_cross(lastDir, currentDir)
                let dot = simd_dot(lastDir, currentDir)
                let angle = atan2(simd_length(cross), dot)
                if angle > 0.001 {
                    let axis = simd_normalize(cross)
                    let q = simd_quatf(angle: angle * 3.0, axis: axis)
                    modelRotation = q * modelRotation
                }
            }

            lastTwoHandDistance = currentDist
            lastTwoHandMidpoint = currentMid
            lastTwoHandDirection = currentDir
            // Reset single-hand state
            lastSinglePinchPos = nil
            return
        }
        lastTwoHandDistance = nil
        lastTwoHandMidpoint = nil
        lastTwoHandDirection = nil

        // Single-hand pinch → Move model
        let singlePinch = leftPinch ?? rightPinch
        if let pos = singlePinch {
            if let lastPos = lastSinglePinchPos {
                let delta = pos - lastPos
                modelOffset += delta * 2.0
            }
            lastSinglePinchPos = pos
        } else {
            lastSinglePinchPos = nil
        }
    }
    
    nonisolated private func renderLoop() {
        while true {
            switch layerRenderer.state {
            case .paused:
                layerRenderer.waitUntilRunning()
                continue
            case .running:
                renderFrame()
            case .invalidated:
                return
            @unknown default:
                return
            }
        }
    }
    
    nonisolated private func renderFrame() {
        guard let frame = layerRenderer.queryNextFrame() else { return }
        
        frame.startUpdate()
        // Check for ripple taps
        if let tapPos = SplatDemoState.shared.rippleTapPosition {
            rippleManager?.addRipple(at: tapPos)
            SplatDemoState.shared.rippleTapPosition = nil
        }
        frame.endUpdate()
        
        guard let timing = frame.predictTiming() else { return }
        LayerRenderer.Clock().wait(until: timing.optimalInputTime)
        
        let drawables = frame.queryDrawables()
        guard !drawables.isEmpty else { return }
        
        guard let splatRenderer, splatRenderer.isReadyToRender else {
            // Submit empty frame to avoid crash
            frame.startSubmission()
            for drawable in drawables {
                guard let cb = commandQueue.makeCommandBuffer() else { continue }
                drawable.encodePresent(commandBuffer: cb)
                cb.commit()
            }
            frame.endSubmission()
            return
        }
        
        _ = inFlightSemaphore.wait(timeout: .distantFuture)
        
        frame.startSubmission()

        let now = CACurrentMediaTime()
        lastUpdateTime = now

        // Process hand gestures for scale/rotation
        processHandGestures()
        
        let primaryDrawable = drawables[0]
        let time = LayerRenderer.Clock.Instant.epoch
            .duration(to: primaryDrawable.frameTiming.presentationTime)
            .timeInterval
        let deviceAnchor = worldTracking.queryDeviceAnchor(atTimestamp: time)
        
        for (index, drawable) in drawables.enumerated() {
            guard let commandBuffer = commandQueue.makeCommandBuffer() else { continue }
            
            drawable.deviceAnchor = deviceAnchor
            
            if index == drawables.count - 1 {
                let sem = inFlightSemaphore
                commandBuffer.addCompletedHandler { _ in sem.signal() }
            }
            
            let viewports = makeViewports(drawable: drawable, deviceAnchor: deviceAnchor)
            
            do {
                try splatRenderer.render(
                    viewports: viewports,
                    colorTexture: drawable.colorTextures[0],
                    colorStoreAction: .store,
                    depthTexture: drawable.depthTextures[0],
                    rasterizationRateMap: drawable.rasterizationRateMaps.first,
                    renderTargetArrayLength: layerRenderer.configuration.layout == .layered
                        ? drawable.views.count : 1,
                    to: commandBuffer
                )
                
                // TODO: Ripple post-process pass would go here
                // rippleManager?.encode(...)
                
            } catch {
                print("[SplatDemo] Render error: \(error)")
            }
            
            drawable.encodePresent(commandBuffer: commandBuffer)
            commandBuffer.commit()
        }
        
        frame.endSubmission()
    }
    
    nonisolated private func makeViewports(
        drawable: LayerRenderer.Drawable,
        deviceAnchor: DeviceAnchor?
    ) -> [SplatRenderer.ViewportDescriptor] {
        // Base position: 3m in front
        let baseTranslation = matrix4x4_translation(0, 0, -3)
        // Hand drag offset
        let offsetTranslation = matrix4x4_translation(modelOffset.x, modelOffset.y, modelOffset.z)
        // Flip upside-down splats (common in most .ply files)
        let flipMatrix = matrix4x4_rotation(radians: .pi, axis: SIMD3<Float>(0, 0, 1))
        // Hand gesture rotation & scale
        let gestureRotationMatrix = simd_float4x4(modelRotation)
        let s = modelScale
        let scaleMatrix = simd_float4x4(diagonal: SIMD4<Float>(s, s, s, 1))

        // Model transform: translate to position, then apply offset, scale, rotation, flip
        let modelTransform = baseTranslation * offsetTranslation * scaleMatrix * gestureRotationMatrix * flipMatrix

        let simdDeviceAnchor = deviceAnchor?.originFromAnchorTransform ?? matrix_identity_float4x4

        return drawable.views.enumerated().map { (index, view) in
            let viewMatrix = (simdDeviceAnchor * view.transform).inverse
            let projectionMatrix = drawable.computeProjection(viewIndex: index)
            let screenSize = SIMD2(
                x: Int(view.textureMap.viewport.width),
                y: Int(view.textureMap.viewport.height)
            )
            return SplatRenderer.ViewportDescriptor(
                viewport: view.textureMap.viewport,
                projectionMatrix: projectionMatrix,
                viewMatrix: viewMatrix * modelTransform,
                screenSize: screenSize
            )
        }
    }
}

// MARK: - Matrix Utilities

func matrix4x4_rotation(radians: Float, axis: SIMD3<Float>) -> simd_float4x4 {
    let normalizedAxis = normalize(axis)
    let ct = cosf(radians)
    let st = sinf(radians)
    let ci = 1 - ct
    let x = normalizedAxis.x, y = normalizedAxis.y, z = normalizedAxis.z
    
    return simd_float4x4(columns: (
        SIMD4<Float>(ct + x * x * ci,     y * x * ci + z * st, z * x * ci - y * st, 0),
        SIMD4<Float>(x * y * ci - z * st, ct + y * y * ci,     z * y * ci + x * st, 0),
        SIMD4<Float>(x * z * ci + y * st, y * z * ci - x * st, ct + z * z * ci,     0),
        SIMD4<Float>(0, 0, 0, 1)
    ))
}

func matrix4x4_translation(_ tx: Float, _ ty: Float, _ tz: Float) -> simd_float4x4 {
    return simd_float4x4(columns: (
        SIMD4<Float>(1, 0, 0, 0),
        SIMD4<Float>(0, 1, 0, 0),
        SIMD4<Float>(0, 0, 1, 0),
        SIMD4<Float>(tx, ty, tz, 1)
    ))
}

// MARK: - RendererTaskExecutor (for render loop)

/// Custom task executor to keep render loop on a dedicated thread
final class RendererTaskExecutor: TaskExecutor, @unchecked Sendable {
    static let shared = RendererTaskExecutor()
    
    func enqueue(_ job: consuming ExecutorJob) {
        let unownedJob = UnownedJob(job)
        Thread.detachNewThread {
            unownedJob.runSynchronously(on: self.asUnownedTaskExecutor())
        }
    }
}

// MARK: - LayerRenderer.Clock.Instant.Duration extension

extension LayerRenderer.Clock.Instant.Duration {
    var timeInterval: TimeInterval {
        let nanoseconds = TimeInterval(components.attoseconds / 1_000_000_000)
        return TimeInterval(components.seconds) + (nanoseconds / TimeInterval(NSEC_PER_SEC))
    }
}
