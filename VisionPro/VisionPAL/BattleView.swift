import SwiftUI
import RealityKit
import ARKit

// MARK: - Battle Window View (2D UI)

struct BattleView: View {
    @EnvironmentObject var battle: BattleController
    @EnvironmentObject var robot: RobotController

    var body: some View {
        ZStack {
            // Background gradient based on scene
            battleBackground

            VStack(spacing: 0) {
                // Top: HP Bars
                if battle.battleActive || battle.status == .victory || battle.status == .defeat {
                    hpBarsView
                        .padding(.horizontal, 30)
                        .padding(.top, 20)
                }

                Spacer()

                // Center: Monster & Scene info
                centerContent

                Spacer()

                // Bottom: Action buttons
                bottomControls
                    .padding(.bottom, 30)
            }
        }
        .frame(width: 900, height: 600)
        .cornerRadius(24)
    }

    // MARK: - Background

    private var battleBackground: some View {
        Group {
            switch battle.status {
            case .victory:
                LinearGradient(colors: [.yellow.opacity(0.3), .orange.opacity(0.2)],
                               startPoint: .top, endPoint: .bottom)
            case .defeat:
                LinearGradient(colors: [.purple.opacity(0.3), .black.opacity(0.4)],
                               startPoint: .top, endPoint: .bottom)
            case .battle, .encounter:
                LinearGradient(colors: [.indigo.opacity(0.2), .black.opacity(0.3)],
                               startPoint: .top, endPoint: .bottom)
            default:
                Color.clear
            }
        }
        .ignoresSafeArea()
    }

    // MARK: - HP Bars

    private var hpBarsView: some View {
        VStack(spacing: 12) {
            // Monster HP
            if let monster = battle.monster {
                HStack {
                    Text("😼 \(monster.name)")
                        .font(.headline)
                        .lineLimit(1)
                    Spacer()
                    Text("\(monster.hp)/\(monster.maxHp ?? monster.hp)")
                        .font(.caption)
                        .monospacedDigit()
                }
                HPBarView(ratio: battle.monsterHPRatio, color: .red)
            }

            // Pal HP
            if let pal = battle.pal {
                HStack {
                    Text("🐾 パル")
                        .font(.headline)
                    Text("[\(pal.emotion)]")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Spacer()
                    Text("\(pal.hp)/\(pal.maxHp)")
                        .font(.caption)
                        .monospacedDigit()
                }
                HPBarView(ratio: battle.palHPRatio, color: .green)
            }
        }
    }

    // MARK: - Center Content

    @ViewBuilder
    private var centerContent: some View {
        switch battle.status {
        case .ready:
            readyView
        case .analyzing:
            analyzingView
        case .encounter:
            encounterView
        case .battle:
            battleLogView
        case .victory:
            resultView(won: true)
        case .defeat:
            resultView(won: false)
        case .error:
            errorView
        }
    }

    private var readyView: some View {
        VStack(spacing: 20) {
            Text("⚔️ 環世界バトル")
                .font(.largeTitle)
                .bold()
            Text("JetBotのカメラが映す世界から\nモンスターが現れる！")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
            Image(systemName: "camera.viewfinder")
                .font(.system(size: 60))
                .foregroundStyle(.blue)
        }
    }

    private var analyzingView: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(2)
            Text(battle.analyzePhase == "monster"
                 ? "😼 モンスター生成中..."
                 : "🔍 環世界を解析中...")
                .font(.title2)
        }
    }

    private var encounterView: some View {
        VStack(spacing: 16) {
            if let monster = battle.monster {
                Text("😼 \(monster.name) が現れた！")
                    .font(.title)
                    .bold()

                Text(monster.description)
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)

                HStack(spacing: 20) {
                    Label(monster.type, systemImage: "flame.fill")
                    if let weakness = monster.weakness {
                        Label("弱点: \(weakness)", systemImage: "shield.slash")
                    }
                }
                .font(.caption)

                if let special = monster.specialMove {
                    Text("必殺技: \(special)")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            if let scene = battle.scene {
                HStack {
                    Text("📍 \(scene.environment)")
                    Text("🎭 \(scene.mood)")
                }
                .font(.caption2)
                .foregroundColor(.secondary)
            }
        }
    }

    private var battleLogView: some View {
        VStack(spacing: 8) {
            Text("ターン \(battle.currentTurn)")
                .font(.headline)

            ForEach(battle.turnLog.suffix(3), id: \.turn) { entry in
                VStack(alignment: .leading, spacing: 4) {
                    if let palMsg = entry.palMsg {
                        Text(palMsg)
                            .font(.body)
                            .foregroundStyle(.blue)
                    }
                    if let monMsg = entry.monsterMsg {
                        Text(monMsg)
                            .font(.body)
                            .foregroundStyle(.red)
                    }
                }
            }
        }
        .padding(.horizontal, 30)
    }

    private func resultView(won: Bool) -> some View {
        VStack(spacing: 16) {
            Text(won ? "🎉 勝利！" : "💀 敗北...")
                .font(.largeTitle)
                .bold()

            if let monster = battle.monster {
                Text(won
                     ? "パルは\(monster.name)を倒した！"
                     : "\(monster.name)に負けてしまった...")
                    .font(.title3)
            }

            Text("\(battle.currentTurn)ターンで決着")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }

    private var errorView: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40))
                .foregroundStyle(.yellow)
            Text(battle.lastMessage)
                .foregroundColor(.secondary)
        }
    }

    // MARK: - Bottom Controls

    private var bottomControls: some View {
        Group {
            if battle.status == .ready {
                Button {
                    battle.startBattle(emotion: "curious")
                } label: {
                    Label("バトル開始！", systemImage: "bolt.fill")
                        .font(.title3)
                        .padding(.horizontal, 30)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(.orange)
            } else if battle.status == .encounter {
                Button {
                    battle.attack() // first attack starts the battle flow
                } label: {
                    Label("戦う！", systemImage: "figure.fencing")
                        .font(.title3)
                        .padding(.horizontal, 30)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
            } else if battle.battleActive {
                battleActionButtons
            } else if battle.status == .victory || battle.status == .defeat {
                HStack(spacing: 20) {
                    Button {
                        battle.startBattle(emotion: "excited")
                    } label: {
                        Label("もう一回！", systemImage: "arrow.counterclockwise")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)

                    Button {
                        battle.reset()
                    } label: {
                        Label("終了", systemImage: "xmark")
                    }
                    .buttonStyle(.bordered)
                }
            } else if battle.status == .analyzing {
                // show nothing, ProgressView is in center
                EmptyView()
            }
        }
    }

    private var battleActionButtons: some View {
        HStack(spacing: 16) {
            Button {
                battle.attack()
            } label: {
                VStack {
                    Image(systemName: "hand.raised.fill")
                        .font(.title2)
                    Text("攻撃")
                        .font(.caption)
                }
                .frame(width: 80, height: 70)
            }
            .buttonStyle(.borderedProminent)
            .tint(.blue)

            Button {
                battle.special()
            } label: {
                VStack {
                    Image(systemName: "sparkles")
                        .font(.title2)
                    Text("必殺技")
                        .font(.caption)
                }
                .frame(width: 80, height: 70)
            }
            .buttonStyle(.borderedProminent)
            .tint(.purple)

            Button {
                battle.dodge()
            } label: {
                VStack {
                    Image(systemName: "figure.roll")
                        .font(.title2)
                    Text("回避")
                        .font(.caption)
                }
                .frame(width: 80, height: 70)
            }
            .buttonStyle(.bordered)
        }
    }
}

// MARK: - HP Bar Component

struct HPBarView: View {
    let ratio: Float
    let color: Color

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.gray.opacity(0.3))

                RoundedRectangle(cornerRadius: 6)
                    .fill(hpColor)
                    .frame(width: max(0, geo.size.width * CGFloat(ratio)))
                    .animation(.easeInOut(duration: 0.5), value: ratio)
            }
        }
        .frame(height: 14)
    }

    private var hpColor: Color {
        if ratio > 0.5 { return color }
        if ratio > 0.25 { return .yellow }
        return .red
    }
}

// MARK: - AR Battle View (Immersive Space)

struct BattleImmersiveView: View {
    @EnvironmentObject var battle: BattleController
    @State private var monsterEntity: ModelEntity?
    @State private var glowEntity: ModelEntity?
    @State private var hpBarEntity: ModelEntity?
    @State private var hpBarBg: ModelEntity?
    @State private var anchorEntity: AnchorEntity?
    @State private var loadedUSDZ: String?

    // Map monster type to USDZ file
    private static let usdzMap: [String: String] = [
        "火": "fire_cat", "炎": "fire_cat", "fire": "fire_cat",
        "氷": "ice_cat", "水": "ice_cat", "ice": "ice_cat", "cold": "ice_cat",
        "雷": "thunder_cat", "電": "thunder_cat", "thunder": "thunder_cat", "lightning": "thunder_cat",
        "闇": "shadow_cat", "影": "shadow_cat", "shadow": "shadow_cat", "dark": "shadow_cat",
    ]

    var body: some View {
        RealityView { content in
            let anchor = AnchorEntity(.head)
            anchorEntity = anchor
            content.add(anchor)

            createMonsterSphere(in: anchor)
            createHPBar(in: anchor)
        } update: { content in
            updateMonster()
            updateHPBar()
        }
        .onChange(of: battle.monster?.name) { _, _ in
            tryLoadUSDZ()
        }
        .gesture(
            TapGesture()
                .targetedToAnyEntity()
                .onEnded { _ in
                    if battle.battleActive {
                        battle.attack()
                        animateHit()
                    }
                }
        )
        .gesture(
            LongPressGesture(minimumDuration: 0.5)
                .targetedToAnyEntity()
                .onEnded { _ in
                    if battle.battleActive {
                        battle.special()
                        animateSpecial()
                    }
                }
        )
        .overlay(alignment: .bottom) {
            battleInfoOverlay
                .padding(.bottom, 60)
        }
    }

    // MARK: - Monster Sphere (Fallback)

    private func createMonsterSphere(in anchor: AnchorEntity) {
        let mesh = MeshResource.generateSphere(radius: 0.3)
        var material = PhysicallyBasedMaterial()
        material.baseColor = .init(tint: monsterColor)
        material.emissiveColor = .init(color: monsterColor)
        material.emissiveIntensity = 500

        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = SIMD3<Float>(0, -0.2, -2)
        entity.generateCollisionShapes(recursive: false)
        entity.components.set(InputTargetComponent())
        monsterEntity = entity
        anchor.addChild(entity)

        // Glow aura
        let glowMesh = MeshResource.generateSphere(radius: 0.5)
        var glowMat = UnlitMaterial()
        glowMat.color = .init(tint: monsterColor.withAlphaComponent(0.12))
        let glow = ModelEntity(mesh: glowMesh, materials: [glowMat])
        glow.position = entity.position
        glowEntity = glow
        anchor.addChild(glow)
    }

    // MARK: - HP Bar (3D)

    private func createHPBar(in anchor: AnchorEntity) {
        let bgMesh = MeshResource.generateBox(size: SIMD3<Float>(0.6, 0.04, 0.02), cornerRadius: 0.01)
        var bgMat = UnlitMaterial()
        bgMat.color = .init(tint: .darkGray)
        let bg = ModelEntity(mesh: bgMesh, materials: [bgMat])
        bg.position = SIMD3<Float>(0, 0.4, -2)
        hpBarBg = bg
        anchor.addChild(bg)

        let fillMesh = MeshResource.generateBox(size: SIMD3<Float>(0.6, 0.04, 0.025), cornerRadius: 0.01)
        var fillMat = UnlitMaterial()
        fillMat.color = .init(tint: .systemGreen)
        let fill = ModelEntity(mesh: fillMesh, materials: [fillMat])
        fill.position = SIMD3<Float>(0, 0.4, -2)
        hpBarEntity = fill
        anchor.addChild(fill)
    }

    // MARK: - USDZ Loading

    private func tryLoadUSDZ() {
        guard let monster = battle.monster else { return }
        let type = monster.type.lowercased()

        var usdzName: String?
        for (key, value) in Self.usdzMap {
            if type.contains(key) || monster.type == key {
                usdzName = value
                break
            }
        }

        guard let fileName = usdzName, fileName != loadedUSDZ else { return }

        Task {
            do {
                let entity = try await Entity(named: fileName)
                await MainActor.run {
                    monsterEntity?.removeFromParent()
                    entity.position = SIMD3<Float>(0, -0.5, -2)
                    entity.scale = SIMD3<Float>(repeating: 0.4)
                    entity.generateCollisionShapes(recursive: true)
                    entity.components.set(InputTargetComponent(allowedInputTypes: .all))
                    anchorEntity?.addChild(entity)
                    loadedUSDZ = fileName
                    print("[BattleAR] Loaded USDZ: \(fileName)")
                }
            } catch {
                print("[BattleAR] USDZ \(fileName) not found, keeping sphere: \(error)")
            }
        }
    }

    // MARK: - Update

    private func updateMonster() {
        guard let entity = monsterEntity else { return }

        var material = PhysicallyBasedMaterial()
        material.baseColor = .init(tint: monsterColor)
        material.emissiveColor = .init(color: monsterColor)
        material.emissiveIntensity = battle.battleActive ? (battle.monsterHPRatio > 0.3 ? 500 : 800) : 200
        entity.model?.materials = [material]

        if battle.battleActive {
            let hpScale = max(0.15, battle.monsterHPRatio)
            let pulse = 1.0 + sin(Float(Date().timeIntervalSince1970) * 3) * 0.03
            entity.scale = SIMD3<Float>(repeating: 0.3 * hpScale * pulse)
        } else if battle.status == .ready {
            entity.scale = SIMD3<Float>(repeating: 0.15)
            material.emissiveIntensity = 100
            entity.model?.materials = [material]
        }

        if let glow = glowEntity {
            var glowMat = UnlitMaterial()
            glowMat.color = .init(tint: monsterColor.withAlphaComponent(battle.battleActive ? 0.15 : 0.05))
            glow.model?.materials = [glowMat]
            let glowPulse = 1.0 + sin(Float(Date().timeIntervalSince1970) * 2) * 0.1
            glow.scale = SIMD3<Float>(repeating: glowPulse)
        }
    }

    private func updateHPBar() {
        guard let fill = hpBarEntity else { return }
        let ratio = battle.monsterHPRatio
        fill.scale = SIMD3<Float>(max(0.01, ratio), 1, 1)
        fill.position.x = -0.3 * (1 - ratio)

        var mat = UnlitMaterial()
        if ratio > 0.5 { mat.color = .init(tint: .systemGreen) }
        else if ratio > 0.25 { mat.color = .init(tint: .systemYellow) }
        else { mat.color = .init(tint: .systemRed) }
        fill.model?.materials = [mat]

        fill.isEnabled = battle.battleActive
        hpBarBg?.isEnabled = battle.battleActive
    }

    // MARK: - Animations

    private func animateHit() {
        guard let entity = monsterEntity else { return }
        let originalScale = entity.scale
        entity.scale = originalScale * 0.7
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            entity.scale = originalScale
        }
    }

    private func animateSpecial() {
        guard let entity = monsterEntity, let glow = glowEntity else { return }
        let originalScale = entity.scale
        glow.scale = SIMD3<Float>(repeating: 2.0)
        entity.scale = originalScale * 0.5
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            entity.scale = originalScale
            glow.scale = SIMD3<Float>(repeating: 1.0)
        }
    }

    // MARK: - Info Overlay

    private var battleInfoOverlay: some View {
        Group {
            if battle.battleActive, let monster = battle.monster {
                VStack(spacing: 8) {
                    Text("😼 \(monster.name)")
                        .font(.title2)
                        .bold()
                    HStack(spacing: 16) {
                        Label(monster.type, systemImage: "flame.fill")
                            .foregroundColor(Color(monsterColor))
                        Text("HP: \(monster.hp)/\(monster.maxHp ?? monster.hp)")
                        Text("ATK: \(monster.attack)")
                    }
                    .font(.caption)
                    HStack(spacing: 20) {
                        Button("⚔️ Attack") { battle.attack(); animateHit() }
                            .buttonStyle(.borderedProminent)
                        Button("✨ Special") { battle.special(); animateSpecial() }
                            .buttonStyle(.bordered)
                        Button("🛡️ Dodge") { battle.dodge() }
                            .buttonStyle(.bordered)
                    }
                }
                .padding(16)
                .background(.ultraThinMaterial)
                .cornerRadius(16)
            } else if battle.status == .victory {
                Text("🎉 勝利！")
                    .font(.largeTitle).bold()
                    .padding()
                    .background(.ultraThinMaterial)
                    .cornerRadius(16)
            } else if battle.status == .defeat {
                Text("💀 敗北...")
                    .font(.largeTitle).bold()
                    .padding()
                    .background(.ultraThinMaterial)
                    .cornerRadius(16)
            } else {
                Text("⚔️ Battle Windowからバトル開始！")
                    .font(.caption)
                    .padding(12)
                    .background(.ultraThinMaterial)
                    .cornerRadius(12)
            }
        }
    }

    // MARK: - Color

    private var monsterColor: UIColor {
        guard let monster = battle.monster else { return .gray }
        let type = monster.type
        if type.contains("火") || type.contains("炎") { return .orange }
        if type.contains("水") || type.contains("氷") { return .cyan }
        if type.contains("闇") || type.contains("影") || type.contains("暗") { return .purple }
        if type.contains("光") || type.contains("聖") { return .yellow }
        if type.contains("風") || type.contains("嵐") { return .green }
        if type.contains("雷") || type.contains("電") { return .systemYellow }
        if type.contains("毒") || type.contains("酸") { return .systemPurple }
        if type.contains("静") || type.contains("無") { return .systemTeal }
        let hash = abs(type.hashValue)
        let colors: [UIColor] = [.systemOrange, .systemCyan, .systemPurple, .systemYellow, .systemTeal, .systemPink, .systemIndigo]
        return colors[hash % colors.count]
    }
}
