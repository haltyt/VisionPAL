import SwiftUI
import RealityKit
import Foundation

/// 湾曲スクリーン: MJPEG映像を円筒内面に投影して没入感を出す
struct CurvedScreenView: View {
    let url: URL
    @State private var screenEntity: ModelEntity?
    @State private var mjpegLoader = CurvedMJPEGLoader()
    
    // スクリーン設定
    var arcDegrees: Float = 140      // 視野角（度）
    var radius: Float = 3.0          // 円筒の半径（m）
    var height: Float = 2.0          // スクリーンの高さ（m）
    var segments: Int = 64           // メッシュの分割数
    
    var body: some View {
        RealityView { content in
            let entity = createCurvedScreen()
            // ユーザーの正面、少し前方に配置
            entity.position = SIMD3<Float>(0, 1.2, 0)  // 目の高さ
            content.add(entity)
            screenEntity = entity
            
            // MJPEGストリーム開始
            mjpegLoader.start(url: url) { cgImage in
                Task { @MainActor in
                    updateTexture(cgImage: cgImage)
                }
            }
        } update: { content in
            // URL変更時の対応
        }
        .onDisappear {
            mjpegLoader.stop()
        }
    }
    
    /// 円筒内面メッシュを生成
    private func createCurvedScreen() -> ModelEntity {
        let arc = arcDegrees * .pi / 180.0
        let halfArc = arc / 2.0
        let cols = segments
        let rows = 1  // 縦方向は1セグメントで十分
        
        var positions: [SIMD3<Float>] = []
        var texCoords: [SIMD2<Float>] = []
        var indices: [UInt32] = []
        
        let halfHeight = height / 2.0
        
        for col in 0...cols {
            let u = Float(col) / Float(cols)
            let angle = -halfArc + arc * u  // 左から右へ
            
            // 円筒の内面（ユーザーに向かって凹む）
            let x = radius * sin(angle)
            let z = -radius * cos(angle) + radius  // 正面が原点になるようオフセット
            
            // 上と下の頂点
            positions.append(SIMD3<Float>(x, halfHeight, z))
            positions.append(SIMD3<Float>(x, -halfHeight, z))
            
            // テクスチャ座標（左右反転なし）
            texCoords.append(SIMD2<Float>(u, 0))  // 上
            texCoords.append(SIMD2<Float>(u, 1))  // 下
        }
        
        // 三角形インデックス（内面 = 反時計回り）
        for col in 0..<cols {
            let topLeft = UInt32(col * 2)
            let bottomLeft = topLeft + 1
            let topRight = topLeft + 2
            let bottomRight = topLeft + 3
            
            // 内側を向く面（反時計回り）
            indices.append(contentsOf: [topLeft, topRight, bottomLeft])
            indices.append(contentsOf: [bottomLeft, topRight, bottomRight])
        }
        
        // 法線（内向き）
        var normals: [SIMD3<Float>] = []
        for col in 0...cols {
            let u = Float(col) / Float(cols)
            let angle = -halfArc + arc * u
            let nx = -sin(angle)
            let nz = cos(angle)
            let normal = SIMD3<Float>(nx, 0, nz)
            normals.append(normal)  // 上
            normals.append(normal)  // 下
        }
        
        // MeshResource生成
        var descriptor = MeshDescriptor(name: "CurvedScreen")
        descriptor.positions = MeshBuffers.Positions(positions)
        descriptor.textureCoordinates = MeshBuffers.TextureCoordinates(texCoords)
        descriptor.normals = MeshBuffers.Normals(normals)
        descriptor.primitives = .triangles(indices)
        
        let mesh = try! MeshResource.generate(from: [descriptor])
        
        // 初期マテリアル（黒）
        var material = UnlitMaterial()
        material.color = .init(tint: .black)
        
        let entity = ModelEntity(mesh: mesh, materials: [material])
        return entity
    }
    
    /// テクスチャを更新
    @MainActor
    private func updateTexture(cgImage: CGImage) {
        guard let entity = screenEntity else { return }
        
        do {
            let texture = try TextureResource.generate(from: cgImage, options: .init(semantic: .color))
            var material = UnlitMaterial()
            material.color = .init(texture: .init(texture))
            entity.model?.materials = [material]
        } catch {
            // テクスチャ生成失敗は無視（次フレームで再試行）
        }
    }
}

/// MJPEGストリームからCGImageを取得するローダー
class CurvedMJPEGLoader: NSObject, URLSessionDataDelegate {
    private var session: URLSession?
    private var dataTask: URLSessionDataTask?
    private var buffer = Data()
    private var onFrame: ((CGImage) -> Void)?
    private var isRunning = false
    private let processingQueue = DispatchQueue(label: "curved.mjpeg.processing")
    
    func start(url: URL, onFrame: @escaping (CGImage) -> Void) {
        self.onFrame = onFrame
        isRunning = true
        
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 0  // 無制限
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        dataTask = session?.dataTask(with: request)
        dataTask?.resume()
    }
    
    func stop() {
        isRunning = false
        dataTask?.cancel()
        session?.invalidateAndCancel()
    }
    
    // MARK: - URLSessionDataDelegate
    
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        processingQueue.async { [weak self] in
            guard let self = self, self.isRunning else { return }
            self.buffer.append(data)
            
            // バッファオーバーフロー防止
            if self.buffer.count > 2 * 1024 * 1024 {
                // 最後のJPEGだけ残す
                if let lastStart = self.findLastJPEGStart() {
                    self.buffer = Data(self.buffer[lastStart...])
                } else {
                    self.buffer.removeAll()
                }
            }
            
            self.extractFrames()
        }
    }
    
    private func extractFrames() {
        while true {
            guard let range = findJPEGRange() else { break }
            guard range.lowerBound >= 0 && range.upperBound <= buffer.count else {
                buffer.removeAll()
                break
            }
            let jpegData = Data(buffer[range])
            
            if range.upperBound < buffer.count {
                buffer = Data(buffer[range.upperBound...])
            } else {
                buffer.removeAll()
            }
            
            // 最新フレームだけ処理（古いのはスキップ）
            if findJPEGStart() != nil { continue }
            
            guard let dataProvider = CGDataProvider(data: jpegData as CFData),
                  let cgImage = CGImage(
                    jpegDataProviderSource: dataProvider,
                    decode: nil,
                    shouldInterpolate: true,
                    intent: .defaultIntent
                  ) else { continue }
            
            onFrame?(cgImage)
        }
    }
    
    private func findJPEGStart() -> Int? {
        guard buffer.count >= 2 else { return nil }
        for i in 0..<(buffer.count - 1) {
            if buffer[i] == 0xFF && buffer[i + 1] == 0xD8 {
                return i
            }
        }
        return nil
    }
    
    private func findLastJPEGStart() -> Int? {
        guard buffer.count >= 2 else { return nil }
        for i in stride(from: buffer.count - 2, through: 0, by: -1) {
            if buffer[i] == 0xFF && buffer[i + 1] == 0xD8 {
                return i
            }
        }
        return nil
    }
    
    private func findJPEGRange() -> Range<Int>? {
        guard let start = findJPEGStart() else { return nil }
        guard start + 2 < buffer.count else { return nil }
        for i in (start + 2)..<(buffer.count - 1) {
            if buffer[i] == 0xFF && buffer[i + 1] == 0xD9 {
                return start..<(i + 2)
            }
        }
        return nil
    }
    
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard isRunning else { return }
        if let error = error as? URLError, error.code == .cancelled { return }
        // 再接続
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) { [weak self] in
            guard let self = self, self.isRunning else { return }
            if let url = task.originalRequest?.url {
                self.buffer.removeAll()
                var request = URLRequest(url: url)
                request.cachePolicy = .reloadIgnoringLocalCacheData
                self.dataTask = self.session?.dataTask(with: request)
                self.dataTask?.resume()
            }
        }
    }
}
