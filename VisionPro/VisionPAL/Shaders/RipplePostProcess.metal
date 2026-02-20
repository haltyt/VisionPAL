#include <metal_stdlib>
using namespace metal;

// Ripple effect uniforms
struct RippleUniforms {
    float4x4 inverseViewProjection;  // Screen → World transform
    float3 rippleCenter;             // Tap position in world space
    float rippleTime;                // Time since tap (seconds)
    float rippleSpeed;               // Expansion speed (world units/sec)
    float rippleWidth;               // Ring thickness (world units)
    float rippleFade;                // Overall fade (1.0 → 0.0)
    float2 screenSize;               // Viewport dimensions
    float nearPlane;
    float farPlane;
};

// Up to 5 simultaneous ripples
#define MAX_RIPPLES 5

struct RippleArray {
    RippleUniforms ripples[MAX_RIPPLES];
    int activeCount;
};

// Reconstruct world position from depth buffer
float3 worldPositionFromDepth(float2 uv, float depth,
                               float4x4 inverseViewProjection) {
    // UV → NDC (visionOS: y-up)
    float4 ndc;
    ndc.x = uv.x * 2.0 - 1.0;
    ndc.y = 1.0 - uv.y * 2.0;  // Flip Y for Metal
    ndc.z = depth;
    ndc.w = 1.0;
    
    float4 worldPos = inverseViewProjection * ndc;
    return worldPos.xyz / worldPos.w;
}

// Ripple ring function
half4 computeRipple(float3 worldPos, RippleUniforms r) {
    float dist = length(worldPos - r.rippleCenter);
    float rippleRadius = r.rippleSpeed * r.rippleTime;
    
    // Distance from the ring center
    float ringDist = abs(dist - rippleRadius);
    
    // Smooth ring shape using smoothstep
    float ring = 1.0 - smoothstep(0.0, r.rippleWidth, ringDist);
    
    // Secondary thinner ring (echo)
    float echoRadius = rippleRadius * 0.7;
    float echoDist = abs(dist - echoRadius);
    float echo = 1.0 - smoothstep(0.0, r.rippleWidth * 0.5, echoDist);
    echo *= 0.3;  // Fainter
    
    // Combine
    float intensity = max(ring, echo) * r.rippleFade;
    
    // Ripple color: luminous cyan-white
    half3 rippleColor = half3(0.4, 0.85, 1.0);
    
    // Glow falloff from center
    float glow = exp(-ringDist * 3.0) * r.rippleFade * 0.5;
    
    return half4(rippleColor * half(intensity + glow), half(intensity));
}

// Full-screen post-process vertex shader
struct PostProcessVertexOut {
    float4 position [[position]];
    float2 uv;
};

vertex PostProcessVertexOut rippleVertexShader(uint vertexID [[vertex_id]]) {
    PostProcessVertexOut out;
    
    // Full-screen triangle
    out.uv.x = (vertexID == 2) ? 2.0 : 0.0;
    out.uv.y = (vertexID == 0) ? 2.0 : 0.0;
    
    out.position.x = out.uv.x * 2.0 - 1.0;
    out.position.y = 1.0 - out.uv.y * 2.0;
    out.position.z = 0.5;
    out.position.w = 1.0;
    
    return out;
}

// Ripple fragment shader — composites ripple effect over the 3DGS render
fragment half4 rippleFragmentShader(PostProcessVertexOut in [[stage_in]],
                                     texture2d<half> colorTexture [[texture(0)]],
                                     depth2d<float> depthTexture [[texture(1)]],
                                     constant RippleArray& ripples [[buffer(0)]]) {
    constexpr sampler s(mag_filter::nearest, min_filter::nearest);
    
    half4 color = colorTexture.sample(s, in.uv);
    float depth = depthTexture.sample(s, in.uv);
    
    // Skip background (no depth)
    if (depth <= 0.0 || depth >= 1.0) {
        return color;
    }
    
    // Accumulate all active ripples
    half4 totalRipple = half4(0);
    
    for (int i = 0; i < ripples.activeCount && i < MAX_RIPPLES; i++) {
        float3 worldPos = worldPositionFromDepth(in.uv, depth,
                                                   ripples.ripples[i].inverseViewProjection);
        half4 ripple = computeRipple(worldPos, ripples.ripples[i]);
        
        // Additive blend between ripples
        totalRipple.rgb += ripple.rgb * ripple.a;
        totalRipple.a = max(totalRipple.a, ripple.a);
    }
    
    // Additive composite over original color
    color.rgb += totalRipple.rgb;
    
    return color;
}
