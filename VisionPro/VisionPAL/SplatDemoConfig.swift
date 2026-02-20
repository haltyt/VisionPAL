import SwiftUI
import CompositorServices

// MARK: - ImmersiveSpace Configuration for SplatDemo

/// ContentStageConfiguration for the 3DGS immersive space
struct SplatDemoConfiguration: CompositorLayerConfiguration {
    func makeConfiguration(
        capabilities: LayerRenderer.Capabilities,
        configuration: inout LayerRenderer.Configuration
    ) {
        // Enable foveation if available
        configuration.isFoveationEnabled =
            capabilities.supportsFoveation
        
        // Use layered layout for stereo rendering
        let supportedLayouts = capabilities.supportedLayouts(options: .default)
        configuration.layout = supportedLayouts.contains(.layered) ? .layered : .dedicated
        
        // Color & depth formats
        configuration.colorFormat = .bgra8Unorm_srgb
        configuration.depthFormat = .depth32Float
    }
}
