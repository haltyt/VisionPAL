import SwiftUI
import Combine

/// MJPEGストリームをSwiftUIで表示するビュー
struct MJPEGView: View {
    let url: URL
    @StateObject private var loader = MJPEGLoader()
    
    var body: some View {
        Group {
            if let image = loader.currentFrame {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                ZStack {
                    Color.black
                    if loader.isConnecting {
                        ProgressView()
                            .tint(.white)
                    } else {
                        VStack(spacing: 8) {
                            Image(systemName: "video.slash")
                                .font(.largeTitle)
                                .foregroundColor(.gray)
                            Text("No Signal")
                                .foregroundColor(.gray)
                                .font(.caption)
                        }
                    }
                }
            }
        }
        .onAppear { loader.start(url: url) }
        .onDisappear { loader.stop() }
        .onChange(of: url) { _, newURL in
            loader.stop()
            loader.start(url: newURL)
        }
    }
}

/// URLSessionでMJPEGストリームを受信し、JPEGフレームを抽出
@MainActor
class MJPEGLoader: NSObject, ObservableObject {
    @Published var currentFrame: UIImage?
    @Published var isConnecting = false
    
    private var session: URLSession?
    private var dataTask: URLSessionDataTask?
    private var buffer = Data()
    
    // JPEG markers
    private let jpegStart = Data([0xFF, 0xD8])
    private let jpegEnd = Data([0xFF, 0xD9])
    
    func start(url: URL) {
        stop()
        isConnecting = true
        
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 3600  // 1時間（ストリームなので長めに）
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        
        // delegateQueue=nil → background
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        dataTask = session?.dataTask(with: url)
        dataTask?.resume()
    }
    
    func stop() {
        dataTask?.cancel()
        dataTask = nil
        session?.invalidateAndCancel()
        session = nil
        buffer.removeAll()
        isConnecting = false
    }
}

extension MJPEGLoader: URLSessionDataDelegate {
    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        // URLSession delegate callback — off main actor
        let jpegStart = Data([0xFF, 0xD8])
        let jpegEnd = Data([0xFF, 0xD9])
        
        // Accumulate data into a local copy, then dispatch frames to MainActor
        // We need to work with buffer on main actor since it's a property
        Task { @MainActor in
            self.buffer.append(data)
            self.isConnecting = false
            
            // 複数フレーム対応ループ
            while true {
                guard let startRange = self.buffer.range(of: jpegStart) else { break }
                guard let endRange = self.buffer.range(of: jpegEnd, in: startRange.lowerBound..<self.buffer.endIndex) else { break }
                
                let frameRange = startRange.lowerBound..<endRange.upperBound
                let frameData = self.buffer.subdata(in: frameRange)
                
                // フレームより前のゴミデータを捨てる
                self.buffer.removeSubrange(self.buffer.startIndex..<endRange.upperBound)
                
                if let image = UIImage(data: frameData) {
                    self.currentFrame = image
                }
            }
            
            // バッファ肥大防止（1MB超えたらリセット）
            if self.buffer.count > 1_000_000 {
                self.buffer.removeAll()
            }
        }
    }
    
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[MJPEG] Stream error: \(error.localizedDescription)")
        }
        // 自動再接続（3秒後）
        Task { @MainActor in
            self.isConnecting = true
            self.currentFrame = nil
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if let url = task.originalRequest?.url {
                self.start(url: url)
            }
        }
    }
}
