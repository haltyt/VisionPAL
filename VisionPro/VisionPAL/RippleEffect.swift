import Foundation
import Metal
import simd

/// Single ripple instance
struct Ripple {
    var center: SIMD3<Float>       // World position of tap
    var startTime: TimeInterval    // CACurrentMediaTime() at creation
    var speed: Float = 0.8         // Expansion speed (world units/sec)
    var width: Float = 0.06        // Ring thickness
    var duration: Float = 2.0      // Total lifetime (seconds)
    
    var isExpired: Bool {
        Float(CACurrentMediaTime() - startTime) > duration
    }
    
    var fade: Float {
        let t = Float(CACurrentMediaTime() - startTime) / duration
        // Ease-out fade
        return max(0, 1.0 - t * t)
    }
    
    var time: Float {
        Float(CACurrentMediaTime() - startTime)
    }
}

/// GPU-side ripple uniforms (must match Metal struct exactly)
struct RippleUniforms {
    var inverseViewProjection: simd_float4x4
    var rippleCenter: SIMD3<Float>
    var rippleTime: Float
    var rippleSpeed: Float
    var rippleWidth: Float
    var rippleFade: Float
    var screenSize: SIMD2<Float>
    var nearPlane: Float
    var farPlane: Float
}

struct RippleArrayUniforms {
    var ripples: (RippleUniforms, RippleUniforms, RippleUniforms, RippleUniforms, RippleUniforms)
    var activeCount: Int32
    var _padding: (Int32, Int32, Int32) = (0, 0, 0)  // Align to 16 bytes
}

/// Manages ripple lifecycle and GPU resources
class RippleEffectManager {
    static let maxRipples = 5
    
    private(set) var activeRipples: [Ripple] = []
    
    private var device: MTLDevice
    private var pipelineState: MTLRenderPipelineState?
    private var uniformBuffer: MTLBuffer?
    
    init(device: MTLDevice, colorPixelFormat: MTLPixelFormat = .bgra8Unorm) {
        self.device = device
        setupPipeline(colorPixelFormat: colorPixelFormat)
        
        uniformBuffer = device.makeBuffer(
            length: MemoryLayout<RippleArrayUniforms>.size,
            options: .storageModeShared
        )
    }
    
    private func setupPipeline(colorPixelFormat: MTLPixelFormat) {
        guard let library = device.makeDefaultLibrary() else {
            print("[Ripple] Failed to create Metal library")
            return
        }
        
        guard let vertexFunc = library.makeFunction(name: "rippleVertexShader"),
              let fragmentFunc = library.makeFunction(name: "rippleFragmentShader") else {
            print("[Ripple] Failed to find ripple shader functions")
            return
        }
        
        let descriptor = MTLRenderPipelineDescriptor()
        descriptor.vertexFunction = vertexFunc
        descriptor.fragmentFunction = fragmentFunc
        descriptor.colorAttachments[0].pixelFormat = colorPixelFormat
        
        // Additive blending
        descriptor.colorAttachments[0].isBlendingEnabled = true
        descriptor.colorAttachments[0].sourceRGBBlendFactor = .one
        descriptor.colorAttachments[0].destinationRGBBlendFactor = .one
        descriptor.colorAttachments[0].rgbBlendOperation = .add
        descriptor.colorAttachments[0].sourceAlphaBlendFactor = .one
        descriptor.colorAttachments[0].destinationAlphaBlendFactor = .one
        descriptor.colorAttachments[0].alphaBlendOperation = .max
        
        // No depth write for post-process
        descriptor.depthAttachmentPixelFormat = .depth32Float
        
        do {
            pipelineState = try device.makeRenderPipelineState(descriptor: descriptor)
            print("[Ripple] Pipeline created successfully")
        } catch {
            print("[Ripple] Pipeline creation failed: \(error)")
        }
    }
    
    // MARK: - Ripple Management
    
    /// Add a new ripple at the given world position
    func addRipple(at worldPosition: SIMD3<Float>, speed: Float = 0.8, duration: Float = 2.0) {
        let ripple = Ripple(
            center: worldPosition,
            startTime: CACurrentMediaTime(),
            speed: speed,
            width: 0.06,
            duration: duration
        )
        
        activeRipples.append(ripple)
        
        // Evict oldest if over limit
        if activeRipples.count > Self.maxRipples {
            activeRipples.removeFirst()
        }
        
        print("[Ripple] Added at \(worldPosition), active: \(activeRipples.count)")
    }
    
    /// Remove expired ripples
    func update() {
        activeRipples.removeAll { $0.isExpired }
    }
    
    // MARK: - Rendering
    
    /// Encode ripple post-process pass
    func encode(
        commandBuffer: MTLCommandBuffer,
        renderPassDescriptor: MTLRenderPassDescriptor,
        colorTexture: MTLTexture,
        depthTexture: MTLTexture,
        viewProjectionMatrix: simd_float4x4,
        screenSize: SIMD2<Float>
    ) {
        update()
        
        guard !activeRipples.isEmpty,
              let pipelineState = pipelineState,
              let uniformBuffer = uniformBuffer else { return }
        
        // Build uniform data
        let inverseVP = viewProjectionMatrix.inverse
        
        var uniforms = RippleArrayUniforms(
            ripples: (makeRippleUniforms(0, inverseVP, screenSize),
                      makeRippleUniforms(1, inverseVP, screenSize),
                      makeRippleUniforms(2, inverseVP, screenSize),
                      makeRippleUniforms(3, inverseVP, screenSize),
                      makeRippleUniforms(4, inverseVP, screenSize)),
            activeCount: Int32(activeRipples.count)
        )
        
        memcpy(uniformBuffer.contents(), &uniforms, MemoryLayout<RippleArrayUniforms>.size)
        
        // Encode
        guard let encoder = commandBuffer.makeRenderCommandEncoder(descriptor: renderPassDescriptor) else { return }
        
        encoder.setRenderPipelineState(pipelineState)
        encoder.setFragmentTexture(colorTexture, index: 0)
        encoder.setFragmentTexture(depthTexture, index: 1)
        encoder.setFragmentBuffer(uniformBuffer, offset: 0, index: 0)
        
        // Draw full-screen triangle
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        encoder.endEncoding()
    }
    
    private func makeRippleUniforms(_ index: Int, _ inverseVP: simd_float4x4, _ screenSize: SIMD2<Float>) -> RippleUniforms {
        if index < activeRipples.count {
            let r = activeRipples[index]
            return RippleUniforms(
                inverseViewProjection: inverseVP,
                rippleCenter: r.center,
                rippleTime: r.time,
                rippleSpeed: r.speed,
                rippleWidth: r.width,
                rippleFade: r.fade,
                screenSize: screenSize,
                nearPlane: 0.01,
                farPlane: 100.0
            )
        } else {
            return RippleUniforms(
                inverseViewProjection: .init(1),
                rippleCenter: .zero,
                rippleTime: 0,
                rippleSpeed: 0,
                rippleWidth: 0,
                rippleFade: 0,
                screenSize: screenSize,
                nearPlane: 0.01,
                farPlane: 100.0
            )
        }
    }
}
