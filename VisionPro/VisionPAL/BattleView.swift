import SwiftUI
import RealityKit

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
    @State private var session = ARKitSession()
    @State private var worldTracking = WorldTrackingProvider()

    var body: some View {
        RealityView { content in
            // Create anchor 2m in front of user
            let anchor = AnchorEntity(.head)

            // Monster placeholder — a glowing sphere
            let mesh = MeshResource.generateSphere(radius: 0.3)
            var material = PhysicallyBasedMaterial()
            material.baseColor = .init(tint: monsterColor)
            material.emissiveColor = .init(color: monsterColor)
            material.emissiveIntensity = 500

            let entity = ModelEntity(mesh: mesh, materials: [material])
            entity.position = SIMD3<Float>(0, 0, -2) // 2m ahead
            monsterEntity = entity

            anchor.addChild(entity)
            content.add(anchor)

            // Add floating text
            // (RealityKit text requires MeshResource.generateText)
        } update: { content in
            // Update monster color based on HP
            if let entity = monsterEntity {
                var material = PhysicallyBasedMaterial()
                material.baseColor = .init(tint: monsterColor)
                material.emissiveColor = .init(color: monsterColor)
                material.emissiveIntensity = battle.monsterHPRatio > 0.3 ? 500 : 200

                // Scale based on HP (shrinks as damaged)
                let scale = max(0.1, battle.monsterHPRatio)
                entity.scale = SIMD3<Float>(repeating: scale * 0.3 + 0.1)
                entity.model?.materials = [material]
            }
        }
        .gesture(
            TapGesture()
                .targetedToAnyEntity()
                .onEnded { _ in
                    if battle.battleActive {
                        battle.attack()
                    }
                }
        )
        .gesture(
            LongPressGesture(minimumDuration: 0.5)
                .targetedToAnyEntity()
                .onEnded { _ in
                    if battle.battleActive {
                        battle.special()
                    }
                }
        )
    }

    private var monsterColor: UIColor {
        guard let monster = battle.monster else { return .white }
        switch monster.type {
        case "火": return .orange
        case "水": return .cyan
        case "闇": return .purple
        case "光": return .yellow
        case "風": return .green
        case "雷": return .systemYellow
        case "氷": return .systemTeal
        case "毒": return .systemPurple
        default: return .white
        }
    }
}
