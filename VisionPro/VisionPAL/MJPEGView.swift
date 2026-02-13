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
                    .aspectRatio(contentMode: .fill)
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
            loader.switchURL(newURL)
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
    private var receivedData = Data()
    private var intentionallyStopped = false
    private var activeURL: URL?
    
    // JPEG markers
    private static let jpegStart = Data([0xFF, 0xD8])
    private static let jpegEnd = Data([0xFF, 0xD9])
    
    // データ受信用の専用キュー（順序保証）
    private let processingQueue = DispatchQueue(label: "mjpeg.processing")
    private var processingBuffer = Data()
    
    func start(url: URL) {
        stop()
        intentionallyStopped = false
        activeURL = url
        isConnecting = true
        print("[MJPEG] Connecting to: \(url.absoluteString)")
        
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 0  // 無制限（ストリーム）
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        
        // delegate用のシリアルキュー
        let delegateQueue = OperationQueue()
        delegateQueue.maxConcurrentOperationCount = 1
        delegateQueue.qualityOfService = .userInteractive
        
        session = URLSession(configuration: config, delegate: self, delegateQueue: delegateQueue)
        dataTask = session?.dataTask(with: url)
        dataTask?.resume()
    }
    
    func stop() {
        intentionallyStopped = true
        dataTask?.cancel()
        dataTask = nil
        session?.invalidateAndCancel()
        session = nil
        processingQueue.sync {
            processingBuffer.removeAll()
        }
        isConnecting = false
    }
    
    /// URL切り替え（再接続抑止付き）
    func switchURL(_ newURL: URL) {
        guard newURL != activeURL else { return }
        print("[MJPEG] Switching to: \(newURL.absoluteString)")
        stop()
        // 少し待ってから新URLに接続（前のセッション完全終了を待つ）
        Task {
            try? await Task.sleep(nanoseconds: 100_000_000) // 0.1秒
            start(url: newURL)
        }
    }
    
    private func reconnect() {
        guard !intentionallyStopped, let url = activeURL else { return }
        isConnecting = true
        currentFrame = nil
        print("[MJPEG] Reconnecting in 3s...")
        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !intentionallyStopped else { return }
            start(url: url)
        }
    }
}

extension MJPEGLoader: URLSessionDataDelegate {
    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                                 didReceive response: URLResponse,
                                 completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        let mime = response.mimeType ?? "unknown"
        let status = (response as? HTTPURLResponse)?.statusCode ?? -1
        print("[MJPEG] Response: \(mime) status: \(status)")
        completionHandler(.allow)
    }
    
    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                                 didReceive data: Data) {
        // シリアルキューでバッファ操作（順序保証、ロックフリー）
        processingQueue.async { [weak self] in
            guard let self = self else { return }
            self.processingBuffer.append(data)
            
            // 複数フレーム抽出ループ
            var latestImage: UIImage? = nil
            while true {
                guard let startRange = self.processingBuffer.range(of: MJPEGLoader.jpegStart) else { break }
                guard let endRange = self.processingBuffer.range(of: MJPEGLoader.jpegEnd,
                    in: startRange.lowerBound..<self.processingBuffer.endIndex) else { break }
                
                let frameData = self.processingBuffer.subdata(
                    in: startRange.lowerBound..<endRange.upperBound)
                self.processingBuffer.removeSubrange(
                    self.processingBuffer.startIndex..<endRange.upperBound)
                
                if let img = UIImage(data: frameData) {
                    latestImage = img  // 最新フレームだけ使う（スキップ可）
                }
            }
            
            // バッファ肥大防止
            if self.processingBuffer.count > 1_000_000 {
                self.processingBuffer.removeAll()
            }
            
            // 最新フレームだけUIに反映
            if let image = latestImage {
                DispatchQueue.main.async {
                    self.currentFrame = image
                    self.isConnecting = false
                }
            }
        }
    }
    
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                 didCompleteWithError error: Error?) {
        if let error = error {
            let nsError = error as NSError
            // 意図的キャンセルはログ出さない
            if nsError.code == NSURLErrorCancelled {
                print("[MJPEG] Stream cancelled (intentional)")
                return
            }
            print("[MJPEG] Stream error: \(error.localizedDescription)")
        } else {
            print("[MJPEG] Stream ended")
        }
        
        DispatchQueue.main.async { [weak self] in
            self?.reconnect()
        }
    }
}
