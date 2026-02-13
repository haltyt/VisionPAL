import Foundation
import Speech
import AVFoundation
import Combine

/// 音声認識でStreamDiffusionのスタイルを操作
class VoiceStyleController: ObservableObject {
    // MARK: - Published State
    @Published var isListening = false
    @Published var recognizedText = ""
    @Published var currentStyle = "none"
    @Published var lastCommand = ""
    @Published var errorMessage: String?
    @Published var isStreamDiffusionEnabled = false
    
    // MARK: - Configuration
    /// StreamDiffusion APIサーバーURL（ハルトのPC）
    var streamDiffusionHost = "192.168.3.5"  // 後で変更可能
    var streamDiffusionPort = 8555
    
    var streamDiffusionBaseURL: URL {
        URL(string: "http://\(streamDiffusionHost):\(streamDiffusionPort)")!
    }
    
    /// 変換済みMJPEGストリームURL
    var transformedStreamURL: URL {
        streamDiffusionBaseURL.appendingPathComponent("stream")
    }
    
    // MARK: - Available Styles
    /// スタイル名 → APIプリセット名のマッピング（日本語対応）
    static let styleMap: [(keywords: [String], preset: String, display: String)] = [
        (["ジブリ", "宮崎", "ghibli"],           "ghibli",     "🎨 ジブリ風"),
        (["サイバーパンク", "サイバー", "cyber"],    "cyberpunk",  "🌃 サイバーパンク"),
        (["水彩", "watercolor"],                  "watercolor", "💧 水彩画"),
        (["スケッチ", "鉛筆", "sketch", "pencil"], "sketch",     "✏️ スケッチ"),
        (["油絵", "oil"],                         "oil",        "🖼️ 油絵"),
        (["ピクセル", "ドット", "pixel"],           "pixel",      "👾 ピクセルアート"),
        (["浮世絵", "ukiyo"],                     "ukiyoe",     "🏯 浮世絵"),
        (["パステル", "pastel"],                   "pastel",     "🌸 パステル"),
    ]
    
    // MARK: - Private
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "ja-JP"))
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private let audioEngine = AVAudioEngine()
    
    // コマンド検出用: 最後に処理したテキスト長（重複防止）
    private var lastProcessedLength = 0
    
    // MARK: - Authorization
    
    /// マイク＋音声認識の権限リクエスト
    func requestPermissions() {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                switch status {
                case .authorized:
                    self?.errorMessage = nil
                case .denied:
                    self?.errorMessage = "音声認識が許可されていません"
                case .restricted:
                    self?.errorMessage = "音声認識が制限されています"
                case .notDetermined:
                    self?.errorMessage = "音声認識の許可待ち"
                @unknown default:
                    break
                }
            }
        }
    }
    
    // MARK: - Listening Control
    
    func toggleListening() {
        if isListening {
            stopListening()
        } else {
            startListening()
        }
    }
    
    func startListening() {
        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            errorMessage = "音声認識が利用できません"
            return
        }
        
        // 前回のタスクをクリーンアップ
        stopListening()
        
        do {
            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            request.requiresOnDeviceRecognition = true  // オンデバイス（低遅延）
            
            let inputNode = audioEngine.inputNode
            let format = inputNode.outputFormat(forBus: 0)
            
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                request.append(buffer)
            }
            
            audioEngine.prepare()
            try audioEngine.start()
            
            recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                guard let self = self else { return }
                
                if let result = result {
                    let text = result.bestTranscription.formattedString
                    DispatchQueue.main.async {
                        self.recognizedText = text
                        self.processCommand(text)
                    }
                    
                    // 最終結果 → 自動リスタート（連続認識）
                    if result.isFinal {
                        self.restartListening()
                    }
                }
                
                if let error = error {
                    print("[Voice] Recognition error: \(error)")
                    DispatchQueue.main.async {
                        // タイムアウトなどの一時的エラーはリトライ
                        self.restartListening()
                    }
                }
            }
            
            self.recognitionRequest = request
            
            DispatchQueue.main.async {
                self.isListening = true
                self.lastProcessedLength = 0
                self.errorMessage = nil
            }
            
            print("[Voice] Listening started")
            
        } catch {
            errorMessage = "オーディオ開始エラー: \(error.localizedDescription)"
        }
    }
    
    func stopListening() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionTask?.cancel()
        recognitionRequest?.endAudio()
        recognitionTask = nil
        recognitionRequest = nil
        
        DispatchQueue.main.async {
            self.isListening = false
            self.recognizedText = ""
        }
        
        print("[Voice] Listening stopped")
    }
    
    private func restartListening() {
        stopListening()
        // 少し待ってリスタート
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            guard let self = self, self.isListening == false else { return }
            self.startListening()
        }
    }
    
    // MARK: - Command Processing
    
    private func processCommand(_ text: String) {
        // 新しい部分だけ処理（部分認識の重複防止）
        guard text.count > lastProcessedLength else { return }
        let newPart = String(text.suffix(text.count - lastProcessedLength))
        lastProcessedLength = text.count
        
        let lower = newPart.lowercased()
        
        // スタイル変更コマンド検出
        for style in Self.styleMap {
            for keyword in style.keywords {
                if lower.contains(keyword) {
                    applyStyle(style.preset, display: style.display)
                    return
                }
            }
        }
        
        // 特殊コマンド
        if lower.contains("オフ") || lower.contains("ノーマル") || lower.contains("元に戻") || lower.contains("リセット") {
            disableStyleTransform()
        } else if lower.contains("オン") || lower.contains("変換開始") {
            enableStyleTransform()
        }
    }
    
    // MARK: - StreamDiffusion API
    
    private func applyStyle(_ preset: String, display: String) {
        lastCommand = display
        currentStyle = preset
        
        // StreamDiffusion APIにスタイル変更リクエスト
        let url = streamDiffusionBaseURL.appendingPathComponent("style")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body: [String: Any] = ["style": preset]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.errorMessage = "スタイル変更失敗: \(error.localizedDescription)"
                    return
                }
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self?.isStreamDiffusionEnabled = true
                    self?.errorMessage = nil
                    print("[Style] Changed to: \(preset)")
                } else {
                    self?.errorMessage = "スタイル変更失敗（サーバーエラー）"
                }
            }
        }.resume()
    }
    
    private func enableStyleTransform() {
        lastCommand = "🟢 変換ON"
        isStreamDiffusionEnabled = true
    }
    
    private func disableStyleTransform() {
        lastCommand = "⚪ 変換OFF"
        currentStyle = "none"
        isStreamDiffusionEnabled = false
    }
}
