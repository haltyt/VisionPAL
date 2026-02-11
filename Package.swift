// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VisionPAL",
    platforms: [.visionOS(.v1)],
    dependencies: [
        .package(url: "https://github.com/emqx/CocoaMQTT.git", from: "2.1.6"),
    ],
    targets: [
        .executableTarget(
            name: "VisionPAL",
            dependencies: ["CocoaMQTT"]
        ),
    ]
)
