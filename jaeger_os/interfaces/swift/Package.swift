// swift-tools-version: 6.0
//
// JaegerOS — native macOS desktop app for JROS.
//
// The 0.2.x menu-bar tray (rumps + AppleScript shell-spawn) hit a hard
// architectural ceiling; this is the Apple-native replacement. Single
// process owns the tray icon (NSStatusItem via SwiftUI's MenuBarExtra),
// the chat window (SwiftUI), and the voice loop (AVAudioEngine + CoreML
// Whisper). Talks to the existing Python daemon over a Unix socket using
// the chat.send / chat.subscribe verbs the daemon already exposes.
//
// Reference architecture: Ollama Desktop (Swift UI + Go/C++ backend over
// localhost). Same shape — only our backend is the Python jaeger_os daemon.
//
// See dev_docs/odysseus_review_and_0.3.0_plan.md for the full pivot and
// the 0.3.0/0.3.1/0.3.2/0.3.3 release ladder.

import PackageDescription

let package = Package(
    name: "JaegerOS",
    platforms: [
        // macOS 14 is the floor — SwiftUI's modern ``onChange(of:_:)``
        // two-arg closure form, ``ScrollViewReader`` autoscroll
        // niceties, and Observation-friendly view bindings all need
        // it. Apple-Silicon-first JROS operators are on 14+ anyway.
        .macOS(.v14),
    ],
    targets: [
        .executableTarget(
            name: "JaegerOS",
            path: "Sources/JaegerOS",
            resources: [
                // Bundle the J icons. SwiftPM exposes them via
                // ``Bundle.module``; load with ``NSImage(named:)``
                // or ``Image("jaeger_icon_22", bundle: .module)``.
                .process("Resources"),
            ]
        ),
        // The boundary's regression net: decodes every frame in
        // ../../../contract/protocol_v1_fixtures.json — the SAME file pytest
        // asserts the Python builders against. Change a frame shape → both
        // suites fail.
        .testTarget(
            name: "JaegerOSTests",
            dependencies: ["JaegerOS"],
            path: "Tests/JaegerOSTests"
        ),
    ]
)
