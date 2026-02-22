import Foundation
import Combine
import CocoaMQTT

// MARK: - Battle Data Models

struct BattleMonster: Codable {
    var name: String
    var nameEn: String?
    var type: String
    var description: String
    var hp: Int
    var maxHp: Int?
    var attack: Int
    var defense: Int
    var specialMove: String?
    var specialDesc: String?
    var weakness: String?
    var personality: String?

    enum CodingKeys: String, CodingKey {
        case name, type, description, hp, attack, defense, weakness, personality
        case nameEn = "name_en"
        case maxHp = "max_hp"
        case specialMove = "special_move"
        case specialDesc = "special_desc"
    }
}

struct BattlePal: Codable {
    var hp: Int
    var maxHp: Int
    var emotion: String
    var attack: Int
    var defense: Int
    var speed: Int?
    var luck: Int?

    enum CodingKeys: String, CodingKey {
        case hp, emotion, attack, defense, speed, luck
        case maxHp = "max_hp"
    }
}

struct BattleScene: Codable {
    var environment: String
    var mood: String
    var elements: [String]?
    var dangerLevel: Int?
    var colorTheme: String?

    enum CodingKeys: String, CodingKey {
        case environment, mood, elements
        case dangerLevel = "danger_level"
        case colorTheme = "color_theme"
    }
}

struct TurnEntry: Codable {
    var turn: Int
    var palAction: String?
    var palMsg: String?
    var monsterMsg: String?

    enum CodingKeys: String, CodingKey {
        case turn
        case palAction = "pal_action"
        case palMsg = "pal_msg"
        case monsterMsg = "monster_msg"
    }
}

enum BattleStatus: String, Codable {
    case ready, analyzing, encounter, battle, victory, defeat, error
}

// MARK: - Battle Controller

class BattleController: ObservableObject {
    // State
    @Published var status: BattleStatus = .ready
    @Published var isConnected = false
    @Published var battleActive = false

    // Battle data
    @Published var monster: BattleMonster?
    @Published var pal: BattlePal?
    @Published var scene: BattleScene?
    @Published var turnLog: [TurnEntry] = []
    @Published var currentTurn = 0
    @Published var lastMessage = ""
    @Published var analyzePhase = ""

    // Monster image
    @Published var monsterImagePath: String?

    // MQTT
    private var mqtt: CocoaMQTT?
    private let commandTopic = "vision_pal/battle/command"
    private let stateTopic = "vision_pal/battle/state"
    private let encounterTopic = "vision_pal/battle/encounter"
    private let monsterImgTopic = "vision_pal/battle/monster_image"
    private let sceneTopic = "vision_pal/battle/scene"

    let mqttHost: String
    let mqttPort: UInt16

    init(mqttHost: String = "192.168.3.5", mqttPort: UInt16 = 1883) {
        self.mqttHost = mqttHost
        self.mqttPort = mqttPort
        setupMQTT()
    }

    // MARK: - MQTT Setup

    private func setupMQTT() {
        let clientID = "VisionPAL-Battle-\(ProcessInfo.processInfo.processIdentifier)"
        mqtt = CocoaMQTT(clientID: clientID, host: mqttHost, port: mqttPort)
        mqtt?.keepAlive = 30
        mqtt?.autoReconnect = true

        mqtt?.didConnectAck = { [weak self] _, ack in
            if ack == .accept {
                DispatchQueue.main.async { self?.isConnected = true }
                self?.mqtt?.subscribe(self?.stateTopic ?? "", qos: .qos1)
                self?.mqtt?.subscribe(self?.encounterTopic ?? "", qos: .qos1)
                self?.mqtt?.subscribe(self?.monsterImgTopic ?? "", qos: .qos1)
                self?.mqtt?.subscribe(self?.sceneTopic ?? "", qos: .qos1)
                print("[Battle] MQTT connected")
            }
        }

        mqtt?.didDisconnect = { [weak self] _, _ in
            DispatchQueue.main.async { self?.isConnected = false }
        }

        mqtt?.didReceiveMessage = { [weak self] _, message, _ in
            self?.handleMessage(topic: message.topic, payload: message.string ?? "")
        }

        _ = mqtt?.connect()
    }

    private func handleMessage(topic: String, payload: String) {
        guard let data = payload.data(using: .utf8) else { return }

        DispatchQueue.main.async { [self] in
            if topic == stateTopic || topic == encounterTopic {
                parseState(data)
            } else if topic == monsterImgTopic {
                if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let path = dict["path"] as? String {
                    monsterImagePath = path
                }
            }
        }
    }

    private func parseState(_ data: Data) {
        // Parse status first
        if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let statusStr = dict["status"] as? String,
               let newStatus = BattleStatus(rawValue: statusStr) {
                status = newStatus
            }
            battleActive = (dict["battle_active"] as? Bool) ?? false
            currentTurn = (dict["turn"] as? Int) ?? currentTurn

            if let phase = dict["phase"] as? String {
                analyzePhase = phase
            }
            if let msg = dict["message"] as? String {
                lastMessage = msg
            }
        }

        // Parse monster
        if let decoded = try? JSONDecoder().decode(EncounterPayload.self, from: data) {
            if let m = decoded.monster { monster = m }
            if let p = decoded.pal { pal = p }
            if let s = decoded.scene { scene = s }
            if let log = decoded.log { turnLog = log }
        }
    }

    // MARK: - Commands

    func startBattle(emotion: String = "curious", imagePath: String? = nil) {
        var cmd: [String: Any] = ["action": "start", "emotion": emotion]
        if let img = imagePath { cmd["image"] = img }
        sendCommand(cmd)
    }

    func attack() {
        sendCommand(["action": "attack"])
    }

    func special() {
        sendCommand(["action": "special"])
    }

    func dodge() {
        sendCommand(["action": "dodge"])
    }

    func reset() {
        sendCommand(["action": "reset"])
        status = .ready
        battleActive = false
        monster = nil
        pal = nil
        scene = nil
        turnLog = []
        currentTurn = 0
    }

    private func sendCommand(_ cmd: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: cmd),
              let json = String(data: data, encoding: .utf8) else { return }
        mqtt?.publish(commandTopic, withString: json, qos: .qos1)
    }

    // MARK: - Helpers

    var palHPRatio: Float {
        guard let p = pal, p.maxHp > 0 else { return 1.0 }
        return Float(p.hp) / Float(p.maxHp)
    }

    var monsterHPRatio: Float {
        guard let m = monster, let maxHp = m.maxHp, maxHp > 0 else { return 1.0 }
        return Float(m.hp) / Float(maxHp)
    }

    func disconnect() {
        mqtt?.disconnect()
    }

    deinit { disconnect() }
}

// Helper for decoding nested optional fields
private struct EncounterPayload: Codable {
    var monster: BattleMonster?
    var pal: BattlePal?
    var scene: BattleScene?
    var log: [TurnEntry]?
}
