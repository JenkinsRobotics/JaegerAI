// swift-tools-version:5.9
//
// JaegerAI-Avatar — Mac-native renderer for the JaegerAI animation node.
// See ../../dev_docs/0.5.0_swift_renderer_plan.md for the
// architecture + phased delivery plan.

import PackageDescription

let package = Package(
    name: "JaegerAIAvatar",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "JaegerAIAvatar", targets: ["JaegerAIAvatar"]),
    ],
    targets: [
        .executableTarget(
            name: "JaegerAIAvatar",
            path: "Sources/JaegerAIAvatar"
        ),
        .testTarget(
            name: "JaegerAIAvatarTests",
            dependencies: ["JaegerAIAvatar"],
            path: "Tests/JaegerAIAvatarTests"
        ),
    ]
)
