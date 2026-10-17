// swift-tools-version: 6.0
//
// JaegerShell: thin native macOS shell around the shared Jaeger web UI.
// Donor: AetherStudio @ ece0209 (see NOTICE). Debug builds only, via
// Scripts/build-shell.sh, into ~/.jaeger/apps/swift-build/ui-rebuild.

import PackageDescription

let package = Package(
    name: "JaegerShell",
    platforms: [.macOS(.v14)],
    targets: [
        // Pure logic (URL validation, navigation policy, hotkey config). Swift 6 mode.
        .target(name: "JaegerShellCore", path: "Sources/JaegerShellCore"),
        // AppKit shell. Swift 5 language mode so the donor code compiles unchanged.
        .executableTarget(
            name: "JaegerShell",
            dependencies: ["JaegerShellCore"],
            path: "Sources/JaegerShell",
            swiftSettings: [.swiftLanguageMode(.v5)],
            linkerSettings: [.linkedFramework("AppKit"), .linkedFramework("WebKit")]
        ),
        .testTarget(
            name: "JaegerShellCoreTests",
            dependencies: ["JaegerShellCore"],
            path: "Tests/JaegerShellCoreTests"
        ),
    ]
)
