import Foundation

/// アプリ全体の設定値。優先順位: 環境変数 > バンドル内 .env > フォールバック既定値。
enum AppConfig {
    // JetBot (MQTT broker + USB カメラ MJPEG)
    static let mqttHost: String = string("MQTT_HOST", default: "192.168.3.12")
    static let mqttPort: UInt16 = uint16("MQTT_PORT", default: 1883)
    static let cameraURL: URL = url("CAMERA_URL", default: "http://192.168.3.12:8554/stream")

    // StreamDiffusion (PC GPU)
    static let streamDiffusionHost: String = string("STREAM_DIFFUSION_HOST", default: "192.168.3.7")
    static let streamDiffusionPort: Int = int("STREAM_DIFFUSION_PORT", default: 8555)

    // 認知エンジン (旧 Jetson ホスト)
    static let cognitionHost: String = string("COGNITION_HOST", default: "192.168.3.5")
    static let cognitionPort: UInt16 = uint16("COGNITION_PORT", default: 1883)

    // 3DGS sharp server
    static let sharpServerURL: URL = url("SHARP_SERVER_URL", default: "http://192.168.3.5:8080")

    // MARK: - Internal

    private static let env: [String: String] = loadEnvFile()

    private static func raw(_ key: String) -> String? {
        ProcessInfo.processInfo.environment[key] ?? env[key]
    }

    private static func string(_ key: String, default fallback: String) -> String {
        raw(key) ?? fallback
    }

    private static func int(_ key: String, default fallback: Int) -> Int {
        raw(key).flatMap(Int.init) ?? fallback
    }

    private static func uint16(_ key: String, default fallback: UInt16) -> UInt16 {
        raw(key).flatMap(UInt16.init) ?? fallback
    }

    private static func url(_ key: String, default fallback: String) -> URL {
        URL(string: raw(key) ?? fallback) ?? URL(string: fallback)!
    }

    private static func loadEnvFile() -> [String: String] {
        guard let fileURL = Bundle.main.url(forResource: ".env", withExtension: nil),
              let text = try? String(contentsOf: fileURL, encoding: .utf8) else {
            print("[AppConfig] .env not found in bundle — using defaults")
            return [:]
        }
        var result: [String: String] = [:]
        for line in text.split(whereSeparator: \.isNewline) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
            guard let eq = trimmed.firstIndex(of: "=") else { continue }
            let key = trimmed[..<eq].trimmingCharacters(in: .whitespaces)
            var value = trimmed[trimmed.index(after: eq)...].trimmingCharacters(in: .whitespaces)
            if (value.hasPrefix("\"") && value.hasSuffix("\""))
                || (value.hasPrefix("'") && value.hasSuffix("'")) {
                value = String(value.dropFirst().dropLast())
            }
            result[key] = value
        }
        print("[AppConfig] loaded .env: \(result.keys.sorted())")
        return result
    }
}
