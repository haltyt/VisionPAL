import SwiftUI
import Foundation

/// MJPEG ストリームをSwiftUIで表示するビュー
struct MJPEGView: View {
    let url: URL
    @StateObject private var stream = MJPEGStream()
    
    var body: some View {
        Group {
            if let image = stream.currentImage {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                ZStack {
                    Color.black
                    VStack {
                        ProgressView()
                            .scaleEffect(2)
                            .padding()
                        Text("Connecting to JetBot camera...")
                            .foregroundColor(.white)
                    }
                }
            }
        }
        .onAppear {
            stream.start(url: url)
        }
        .onDisappear {
            stream.stop()
        }
    }
}

/// MJPEG ストリームパーサー
class MJPEGStream: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var currentImage: UIImage?
    
    private var session: URLSession?
    private var dataTask: URLSessionDataTask?
    private var buffer = Data()
    
    // JPEG マーカー
    private let jpegStart = Data([0xFF, 0xD8])
    private let jpegEnd = Data([0xFF, 0xD9])
    
    func start(url: URL) {
        let config = URLSessionConfiguration.default
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 30
        
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        
        dataTask = session?.dataTask(with: request)
        dataTask?.resume()
        
        print("[MJPEG] Connecting to \(url)")
    }
    
    func stop() {
        dataTask?.cancel()
        session?.invalidateAndCancel()
        print("[MJPEG] Stopped")
    }
    
    // URLSessionDataDelegate - データ受信時
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        
        // バッファからJPEGフレームを抽出
        while let frame = extractJPEG() {
            if let image = UIImage(data: frame) {
                DispatchQueue.main.async {
                    self.currentImage = image
                }
            }
        }
        
        // バッファが大きくなりすぎたらリセット
        if buffer.count > 5_000_000 {
            buffer.removeAll()
        }
    }
    
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[MJPEG] Error: \(error.localizedDescription)")
        }
    }
    
    private func extractJPEG() -> Data? {
        guard let startRange = buffer.range(of: jpegStart) else { return nil }
        guard let endRange = buffer.range(of: jpegEnd, in: startRange.lowerBound..<buffer.endIndex) else { return nil }
        
        let jpegData = buffer[startRange.lowerBound..<endRange.upperBound]
        buffer.removeSubrange(buffer.startIndex..<endRange.upperBound)
        
        return Data(jpegData)
    }
}
