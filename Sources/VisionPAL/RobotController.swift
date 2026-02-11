import Foundation
import Combine
import CocoaMQTT

enum MoveDirection: String {
    case forward, backward, left, right, stop
}

class RobotController: ObservableObject {
    @Published var isConnected = false
    @Published var currentDirection: MoveDirection = .stop
    @Published var currentSpeed: Float = 0.0
    
    // Configuration - ローカルネットワーク
    let mqttHost = "192.168.3.5"
    let mqttPort: UInt16 = 1883
    let cameraURL = URL(string: "http://192.168.3.8:8554/stream")!
    
    private var mqtt: CocoaMQTT?
    private let moveTopic = "vision_pal/move"
    private let statusTopic = "vision_pal/status"
    
    // Head tracking thresholds
    let yawDeadZone: Float = 0.1    // ±0.1 rad (~6°) = forward
    let yawTurnZone: Float = 0.3    // ±0.3 rad (~17°) = turn
    let pitchStopZone: Float = -0.3 // 下を向いたら停止
    
    init() {
        setupMQTT()
    }
    
    private func setupMQTT() {
        let clientID = "VisionPAL-\(ProcessInfo.processInfo.processIdentifier)"
        mqtt = CocoaMQTT(clientID: clientID, host: mqttHost, port: mqttPort)
        mqtt?.keepAlive = 30
        mqtt?.autoReconnect = true
        
        mqtt?.didConnectAck = { [weak self] _, ack in
            if ack == .accept {
                DispatchQueue.main.async {
                    self?.isConnected = true
                }
                self?.mqtt?.subscribe(self?.statusTopic ?? "")
                print("[MQTT] Connected!")
            }
        }
        
        mqtt?.didDisconnect = { [weak self] _, _ in
            DispatchQueue.main.async {
                self?.isConnected = false
            }
            print("[MQTT] Disconnected")
        }
        
        mqtt?.didReceiveMessage = { _, message, _ in
            print("[MQTT] Received: \(message.topic) = \(message.string ?? "")")
        }
        
        _ = mqtt?.connect()
    }
    
    /// 移動コマンド送信
    func move(direction: MoveDirection, speed: Float = 0.5) {
        currentDirection = direction
        currentSpeed = speed
        
        let payload: [String: Any] = [
            "direction": direction.rawValue,
            "speed": speed
        ]
        
        if let data = try? JSONSerialization.data(withJSONObject: payload),
           let json = String(data: data, encoding: .utf8) {
            mqtt?.publish(moveTopic, withString: json, qos: .qos0)
        }
    }
    
    /// ヘッドトラッキングからの方向変換
    func updateFromHeadTracking(yaw: Float, pitch: Float) {
        // 下を向いたら停止（安全装置）
        if pitch < pitchStopZone {
            if currentDirection != .stop {
                move(direction: .stop)
            }
            return
        }
        
        // Yaw（左右の首振り）で方向決定
        let direction: MoveDirection
        let speed: Float
        
        if abs(yaw) < yawDeadZone {
            // 正面 → 前進
            direction = .forward
            speed = 0.4
        } else if yaw > yawDeadZone {
            // 左を向いている → 左旋回
            direction = .left
            speed = min(abs(yaw) / yawTurnZone, 1.0) * 0.5
        } else {
            // 右を向いている → 右旋回
            direction = .right
            speed = min(abs(yaw) / yawTurnZone, 1.0) * 0.5
        }
        
        // 前回と同じなら送らない（MQTTスパム防止）
        if direction != currentDirection || abs(speed - currentSpeed) > 0.1 {
            move(direction: direction, speed: speed)
        }
    }
    
    func disconnect() {
        move(direction: .stop)
        mqtt?.disconnect()
    }
    
    deinit {
        disconnect()
    }
}
