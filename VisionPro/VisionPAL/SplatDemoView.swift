import SwiftUI
import CompositorServices
import Metal
import MetalSplatter
import SplatIO
import ARKit
import simd

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
                    .init(filenameExtension: "ply")!,
                    .init(filenameExtension: "splat")!,
                    .init(filenameExtension: "spz")!,
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
    
    let arSession = ARKitSession()
    let worldTracking = WorldTrackingProvider()
    
    init(_ layerRenderer: LayerRenderer) {
        self.layerRenderer = layerRenderer
        self.device = layerRenderer.device
        self.commandQueue = device.makeCommandQueue()!
    }
    
    static func startRendering(_ layerRenderer: LayerRenderer) {
        let renderer = SplatDemoRenderer(layerRenderer)
        Task {
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
    private func createProceduralSplats() -> [SplatIO.SplatScenePoint] {
        var points: [SplatIO.SplatScenePoint] = []
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
                    
                    // Color based on position
                    let r = Float(x) / Float(gridSize)
                    let g = Float(y) / Float(gridSize)
                    let b = Float(z) / Float(gridSize)
                    
                    var point = SplatIO.SplatScenePoint()
                    point.position = position
                    point.color = SIMD3<Float>(r, g, b)
                    point.opacity = 0.8
                    point.scale = SIMD3<Float>(repeating: 0.02)
                    points.append(point)
                }
            }
        }
        return points
    }
    
    func startRenderLoop() {
        Task(executorPreference: RendererTaskExecutor.shared) {
            do {
                try await arSession.run([worldTracking])
            } catch {
                print("[SplatDemo] ARKit error: \(error)")
            }
            renderLoop()
        }
    }
    
    private func renderLoop() {
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
    
    private func renderFrame() {
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
        
        // Update rotation
        let now = CACurrentMediaTime()
        if lastUpdateTime > 0 {
            let dt = Float(now - lastUpdateTime)
            rotation += dt * 0.12  // ~7 degrees/sec
        }
        lastUpdateTime = now
        
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
    
    private func makeViewports(
        drawable: LayerRenderer.Drawable,
        deviceAnchor: DeviceAnchor?
    ) -> [ModelRendererViewportDescriptor] {
        let rotationMatrix = matrix4x4_rotation(radians: rotation, axis: SIMD3<Float>(0, 1, 0))
        let translationMatrix = matrix4x4_translation(0, 0, -3)  // 3m in front
        // Flip upside-down splats (common in most .ply files)
        let flipMatrix = matrix4x4_rotation(radians: .pi, axis: SIMD3<Float>(0, 0, 1))
        
        let simdDeviceAnchor = deviceAnchor?.originFromAnchorTransform ?? matrix_identity_float4x4
        
        return drawable.views.enumerated().map { (index, view) in
            let viewMatrix = (simdDeviceAnchor * view.transform).inverse
            let projectionMatrix = drawable.computeProjection(viewIndex: index)
            let screenSize = SIMD2(
                x: Int(view.textureMap.viewport.width),
                y: Int(view.textureMap.viewport.height)
            )
            return ModelRendererViewportDescriptor(
                viewport: view.textureMap.viewport,
                projectionMatrix: projectionMatrix,
                viewMatrix: viewMatrix * translationMatrix * rotationMatrix * flipMatrix,
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

// MARK: - ViewportDescriptor extension for MetalSplatter

struct ModelRendererViewportDescriptor {
    var viewport: MTLViewport
    var projectionMatrix: simd_float4x4
    var viewMatrix: simd_float4x4
    var screenSize: SIMD2<Int>
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
