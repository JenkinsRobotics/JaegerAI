// swift-tools-version:5.9
//
// JROS-Avatar — Mac-native renderer for the JROS animation node.
// See ../../dev_docs/0.5.0_swift_renderer_plan.md for the
// architecture + phased delivery plan.

import PackageDescription

let package = Package(
    name: "JROSAvatar",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "JROSAvatar", targets: ["JROSAvatar"]),
    ],
    targets: [
        .executableTarget(
            name: "JROSAvatar",
            path: "Sources/JROSAvatar"
        ),
        .testTarget(
            name: "JROSAvatarTests",
            dependencies: ["JROSAvatar"],
            path: "Tests/JROSAvatarTests"
        ),
    ]
)
