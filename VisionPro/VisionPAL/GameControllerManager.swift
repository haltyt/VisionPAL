import Foundation
import GameController
import Combine

/// DualSense等のGCController入力をJetBotのタンク操舵コマンドに変換
/// 左スティック: 差動操舵 / R2: ブースト / × (A): 一時停止トグル / ○ (B): 緊急停止
class GameControllerManager: ObservableObject {
    @Published var isConnected = false
    @Published var controllerName = ""
    @Published var isPaused = false

    private weak var robot: RobotController?
    private var sendTimer: Timer?
    private var lastDirection = "stop"
    private var lastLeft: Float = 0
    private var lastRight: Float = 0
    private var tickCount: Int = 0
    private var buttonAPressedAt: Date?

    private let baseSpeed: Float = 0.4
    private let boostSpeed: Float = 0.65
    private let deadZone: Float = 0.15
    private let sendInterval: TimeInterval = 0.1
    private let pauseHoldSeconds: TimeInterval = 0.6  // ×長押しでpause

    init(robot: RobotController) {
        self.robot = robot

        // visionOS でフォアグラウンドのみ入力を受ける (true だとシステム入力と競合)
        GCController.shouldMonitorBackgroundEvents = false

        NotificationCenter.default.addObserver(
            self, selector: #selector(controllerDidConnect),
            name: .GCControllerDidConnect, object: nil
        )
        NotificationCenter.default.addObserver(
            self, selector: #selector(controllerDidDisconnect),
            name: .GCControllerDidDisconnect, object: nil
        )

        // 検出フックを開始 (Bluetooth既存接続を拾うため)
        GCController.startWirelessControllerDiscovery {}

        if let existing = GCController.controllers().first {
            attach(existing)
        }
    }

    @objc private func controllerDidConnect(_ note: Notification) {
        guard let controller = note.object as? GCController else { return }
        attach(controller)
    }

    /// UI ボタンから呼び出して再 attach (visionOS フォーカス失効時の復旧)
    func reattachCurrentController() {
        guard let controller = GCController.controllers().first else {
            print("[GC] reattach: controller not found, restarting discovery")
            GCController.startWirelessControllerDiscovery {}
            return
        }
        print("[GC] reattach \(controller.vendorName ?? "?")")
        attach(controller)
    }

    @objc private func controllerDidDisconnect(_ note: Notification) {
        sendTimer?.invalidate()
        sendTimer = nil
        DispatchQueue.main.async {
            self.isConnected = false
            self.controllerName = ""
        }
        robot?.moveTank(left: 0, right: 0, label: "stop")
        print("[GC] Disconnected")
    }

    private func attach(_ controller: GCController) {
        let name = controller.vendorName ?? "Controller"
        print("[GC] Connected: \(name)")
        print("[GC] productCategory=\(controller.productCategory)")
        print("[GC] extendedGamepad=\(controller.extendedGamepad != nil) microGamepad=\(controller.microGamepad != nil)")
        print("[GC] physicalInputProfile elements=\(controller.physicalInputProfile.elements.keys.sorted())")
        print("[GC] controllers count=\(GCController.controllers().count)")
        for (i, c) in GCController.controllers().enumerated() {
            print("[GC]  [\(i)] \(c.vendorName ?? "?") cat=\(c.productCategory)")
        }

        // ハンドラ呼び出しキューを明示 (visionOSでデフォルトが背景キューになるケース対策)
        controller.handlerQueue = .main
        // アプリの「所有コントローラー」として宣言
        controller.playerIndex = .index1

        DispatchQueue.main.async {
            self.isConnected = true
            self.controllerName = name
        }

        if let gamepad = controller.extendedGamepad {
            // × (buttonA): 長押し (>0.6s) で pause トグル — 誤押し防止
            gamepad.buttonA.pressedChangedHandler = { [weak self] _, _, pressed in
                guard let self = self else { return }
                if pressed {
                    self.buttonAPressedAt = Date()
                } else if let start = self.buttonAPressedAt {
                    let held = Date().timeIntervalSince(start)
                    self.buttonAPressedAt = nil
                    if held >= self.pauseHoldSeconds {
                        self.togglePause()
                    } else {
                        print("[GC] ×短押し (\(String(format: "%.2f", held))s) - 無視")
                    }
                }
            }
            gamepad.buttonB.pressedChangedHandler = { [weak self] _, _, pressed in
                if pressed { self?.emergencyStop() }
            }

            // event-driven: スティック/トリガー変化時にコールバック (visionOSフォーカス対策)
            gamepad.leftThumbstick.valueChangedHandler = { [weak self] _, x, y in
                print(String(format: "[GC] stick lx=%.2f ly=%.2f", x, y))
                self?.tick()
            }
            gamepad.rightTrigger.valueChangedHandler = { [weak self] _, value, _ in
                print(String(format: "[GC] R2=%.2f", value))
                self?.tick()
            }

            // 保険: gamepad全体のステート変化フック
            gamepad.valueChangedHandler = { _, element in
                print("[GC] valueChanged element=\(element.localizedName ?? "?")")
            }
        }

        // 物理入力プロファイル経由のフックも追加 (visionOSで一部requiredな場合)
        controller.physicalInputProfile.valueDidChangeHandler = { _, element in
            print("[GC] physInput changed: \(element.localizedName ?? element.aliases.first ?? "?")")
        }

        // 個別ボタン経由: Left Thumbstick Up/Down/Left/Right (extendedGamepadとは別レイヤー)
        let profile = controller.physicalInputProfile
        if let up = profile.buttons["Left Thumbstick Up"],
           let down = profile.buttons["Left Thumbstick Down"],
           let left = profile.buttons["Left Thumbstick Left"],
           let right = profile.buttons["Left Thumbstick Right"] {
            print("[GC] subscribing individual stick direction buttons")
            up.valueChangedHandler = { [weak self] _, v, _ in
                print(String(format: "[GC] LStick UP=%.2f", v))
                self?.tick()
            }
            down.valueChangedHandler = { [weak self] _, v, _ in
                print(String(format: "[GC] LStick DOWN=%.2f", v))
                self?.tick()
            }
            left.valueChangedHandler = { [weak self] _, v, _ in
                print(String(format: "[GC] LStick LEFT=%.2f", v))
                self?.tick()
            }
            right.valueChangedHandler = { [weak self] _, v, _ in
                print(String(format: "[GC] LStick RIGHT=%.2f", v))
                self?.tick()
            }
        }

        // physicalInputProfile経由でLeft Thumbstickのdpadを購読
        if let leftStickDpad = profile.dpads["Left Thumbstick"] {
            print("[GC] subscribing physInput Left Thumbstick dpad")
            leftStickDpad.valueChangedHandler = { [weak self] _, x, y in
                print(String(format: "[GC] physLStick x=%.2f y=%.2f", x, y))
                self?.tick()
            }
        }

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.sendTimer?.invalidate()
            self.sendTimer = Timer.scheduledTimer(withTimeInterval: self.sendInterval, repeats: true) { [weak self] _ in
                self?.tick()
            }
        }
    }

    private func togglePause() {
        isPaused.toggle()
        if isPaused {
            robot?.moveTank(left: 0, right: 0, label: "stop")
        }
        print("[GC] paused=\(isPaused)")
    }

    private func emergencyStop() {
        isPaused = true
        robot?.moveTank(left: 0, right: 0, label: "stop")
        print("[GC] EMERGENCY STOP")
    }

    private func tick() {
        tickCount += 1

        guard let controller = GCController.controllers().first,
              let gamepad = controller.extendedGamepad else {
            if tickCount % 10 == 0 { print("[GC] tick: コントローラー未検出") }
            return
        }

        let lx = gamepad.leftThumbstick.xAxis.value
        let ly = gamepad.leftThumbstick.yAxis.value  // +1=up=forward
        let r2 = gamepad.rightTrigger.value          // 0..1

        // 1秒に1回、生のスティック値を出力 (デバッグ)
        if tickCount % 10 == 0 {
            print(String(format: "[GC] tick lx=%.2f ly=%.2f r2=%.2f paused=%@",
                         lx, ly, r2, isPaused ? "Y" : "N"))
        }

        if isPaused { return }

        let fx: Float = abs(lx) > deadZone ? lx : 0
        let fy: Float = abs(ly) > deadZone ? ly : 0

        let speed = baseSpeed + (boostSpeed - baseSpeed) * r2
        let leftSpeed = max(-1.0, min(1.0, speed * (fy + fx)))
        let rightSpeed = max(-1.0, min(1.0, speed * (fy - fx)))

        var label = "stop"
        if abs(fy) > 0.15 && abs(fx) > 0.15 {
            label = fy > 0 ? (fx < 0 ? "forward-left" : "forward-right")
                          : (fx < 0 ? "backward-left" : "backward-right")
        } else if abs(fy) > abs(fx) {
            label = fy > 0 ? "forward" : "backward"
        } else if abs(fx) > 0 {
            label = fx < 0 ? "left" : "right"
        }

        let movingNow = abs(leftSpeed) > 0.01 || abs(rightSpeed) > 0.01
        let movingBefore = abs(lastLeft) > 0.01 || abs(lastRight) > 0.01
        if label != lastDirection || movingNow || movingBefore {
            robot?.moveTank(left: leftSpeed, right: rightSpeed, label: label)
            lastLeft = leftSpeed
            lastRight = rightSpeed
            lastDirection = label
        }
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
        sendTimer?.invalidate()
    }
}
