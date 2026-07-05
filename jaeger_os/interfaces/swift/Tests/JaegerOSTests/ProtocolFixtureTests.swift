//
//  ProtocolFixtureTests.swift
//  JaegerOSTests
//
//  The cross-language protocol contract: every frame in
//  ``jaeger_os/interfaces/protocol_v1_fixtures.json`` must decode into the
//  Swift ``ProtocolFrame`` it claims to be. pytest asserts the Python
//  BUILDERS produce these exact shapes (test_bridge.py::
//  test_fixture_frames_match_builders); this suite asserts the Swift
//  DECODER parses them — so a frame change breaks both sides loudly.
//

import XCTest
@testable import JaegerOS

final class ProtocolFixtureTests: XCTestCase {

    // Fixtures live beside protocol.py (two directories up from the swift
    // package: Tests file → repo navigation via #filePath keeps the single
    // source of truth without copying).
    private func fixtures() throws -> [String: Data] {
        let here = URL(fileURLWithPath: #filePath)
        let interfaces = here                       // …/interfaces/swift/Tests/JaegerOSTests/x.swift
            .deletingLastPathComponent()            // JaegerOSTests
            .deletingLastPathComponent()            // Tests
            .deletingLastPathComponent()            // swift
            .deletingLastPathComponent()            // interfaces
        let url = interfaces.appendingPathComponent("protocol_v1_fixtures.json")
        let root = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)) as? [String: Any]
        let proto = root?["proto"] as? String
        XCTAssertEqual(proto, ProtocolV1.version,
                       "fixture proto version drifted from the shell's")
        let frames = root?["frames"] as? [String: Any] ?? [:]
        var out: [String: Data] = [:]
        for (name, obj) in frames {
            out[name] = try JSONSerialization.data(withJSONObject: obj)
        }
        return out
    }

    private func decode(_ name: String) throws -> ProtocolFrame {
        let all = try fixtures()
        guard let data = all[name] else {
            XCTFail("fixture \(name) missing"); throw NSError(domain: "fx", code: 1)
        }
        guard let frame = ProtocolFrame.decode(data) else {
            XCTFail("fixture \(name) did not decode"); throw NSError(domain: "fx", code: 2)
        }
        return frame
    }

    func testEveryFixtureFrameDecodes() throws {
        for (name, data) in try fixtures() {
            XCTAssertNotNil(ProtocolFrame.decode(data),
                            "fixture frame \(name) failed to decode")
        }
    }

    func testReadyCarriesVersionCapabilitiesAndAgentState() throws {
        guard case .ready(let r) = try decode("ready") else {
            return XCTFail("wrong case")
        }
        XCTAssertEqual(r.proto, "1")
        XCTAssertEqual(r.instance, "jros-dev")
        XCTAssertEqual(r.agent, "booting")
        XCTAssertTrue(r.capabilities.contains("agent_state"))
        XCTAssertTrue(r.capabilities.contains("sessions"))

        guard case .ready(let warm) = try decode("ready_warm") else {
            return XCTFail("wrong case")
        }
        XCTAssertEqual(warm.agent, "ready")
        XCTAssertEqual(warm.character, "Jarvis")
    }

    func testAgentStateLifecycle() throws {
        guard case .agentState(.booting) = try decode("agent_state_booting") else {
            return XCTFail("booting")
        }
        guard case .agentState(.ready(let model, let character, _)) =
                try decode("agent_state_ready") else {
            return XCTFail("ready")
        }
        XCTAssertEqual(model, "gemma-4-E4B-it-Q4_K_M.gguf")
        XCTAssertEqual(character, "Jarvis")
        guard case .agentState(.failed(let reason)) =
                try decode("agent_state_failed") else {
            return XCTFail("failed")
        }
        XCTAssertEqual(reason, "model file missing")
    }

    func testTurnFrames() throws {
        guard case .state(let busy) = try decode("state_busy") else {
            return XCTFail("state")
        }
        XCTAssertTrue(busy)
        guard case .reply(let text, let error) = try decode("reply") else {
            return XCTFail("reply")
        }
        XCTAssertEqual(text, "It's 3:48 PM PDT.")
        XCTAssertNil(error)
        guard case .reply(_, let err2) = try decode("reply_error") else {
            return XCTFail("reply_error")
        }
        XCTAssertEqual(err2, "model exploded")
        guard case .tool(let name, let phase, let elapsed) = try decode("tool") else {
            return XCTFail("tool")
        }
        XCTAssertEqual(name, "web_search")
        XCTAssertEqual(phase, "done")
        XCTAssertEqual(elapsed, 1.25, accuracy: 0.001)
    }

    func testResultRequestFatalBye() throws {
        guard case .result(let id, let ok, _, let data) = try decode("result") else {
            return XCTFail("result")
        }
        XCTAssertEqual(id, "r1")
        XCTAssertTrue(ok)
        XCTAssertNotNil(data)   // payload survives re-serialization

        guard case .request(let req) = try decode("request_approval") else {
            return XCTFail("request")
        }
        XCTAssertEqual(req.id, "perm1")
        XCTAssertEqual(req.kind, "approval")
        XCTAssertEqual(req.options, ["allow", "deny"])

        guard case .fatal(_, let kind) = try decode("fatal_locked") else {
            return XCTFail("fatal_locked")
        }
        XCTAssertEqual(kind, "locked")
        guard case .fatal(_, let bootKind) = try decode("fatal_boot") else {
            return XCTFail("fatal_boot")
        }
        XCTAssertEqual(bootKind, "boot")
        // v1 additive: first-run — no instance on disk yet. The shell
        // routes this kind to onboarding instead of a generic error.
        guard case .fatal(let noInstErr, let noInstKind) =
                try decode("fatal_no_instance") else {
            return XCTFail("fatal_no_instance")
        }
        XCTAssertEqual(noInstKind, "no_instance")
        XCTAssertTrue(noInstErr.contains("first-run"))

        guard case .bye = try decode("bye") else { return XCTFail("bye") }
    }

    func testSpeakCommandOpFixtureMatchesWhatTheShellSends() throws {
        // The speaker button routes through BridgeProcess.command("speak",
        // args: ["text": …]) — assert the cross-language fixture pins the
        // exact shape that call serializes, so a Python-side rename breaks
        // here too.
        let here = URL(fileURLWithPath: #filePath)
        let url = here
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("protocol_v1_fixtures.json")
        let root = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)) as? [String: Any]
        let ops = root?["ops"] as? [String: Any]
        guard let speak = ops?["command_speak"] as? [String: Any] else {
            return XCTFail("command_speak op fixture missing")
        }
        XCTAssertEqual(speak["op"] as? String, "command")
        XCTAssertEqual(speak["cmd"] as? String, "speak")
        let args = speak["args"] as? [String: Any]
        XCTAssertEqual(args?["text"] as? String, "Good day.")
    }

    func testOnboardingOpFixturesMatchWhatTheShellSends() throws {
        // First-run onboarding rides three additive v1 values:
        // query "instance_exists", query "setup_defaults", and command
        // "create_instance". Pin the shapes the shell serializes via
        // BridgeProcess.query/command so a Python-side rename breaks here.
        let here = URL(fileURLWithPath: #filePath)
        let url = here
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("protocol_v1_fixtures.json")
        let root = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)) as? [String: Any]
        let ops = root?["ops"] as? [String: Any]

        guard let exists = ops?["query_instance_exists"] as? [String: Any] else {
            return XCTFail("query_instance_exists op fixture missing")
        }
        XCTAssertEqual(exists["op"] as? String, "query")
        XCTAssertEqual(exists["what"] as? String, "instance_exists")

        guard let defaults = ops?["query_setup_defaults"] as? [String: Any] else {
            return XCTFail("query_setup_defaults op fixture missing")
        }
        XCTAssertEqual(defaults["op"] as? String, "query")
        XCTAssertEqual(defaults["what"] as? String, "setup_defaults")

        guard let create = ops?["command_create_instance"] as? [String: Any] else {
            return XCTFail("command_create_instance op fixture missing")
        }
        XCTAssertEqual(create["op"] as? String, "command")
        XCTAssertEqual(create["cmd"] as? String, "create_instance")
        let args = create["args"] as? [String: Any]
        XCTAssertEqual(args?["character_id"] as? String, "jarvis")
        XCTAssertEqual(args?["permission_mode"] as? String, "confirm")
    }

    func testUnknownFrameTypeIsSkippedNotFatal() {
        let unknown = #"{"type":"telemetry_v9","payload":{}}"#.data(using: .utf8)!
        XCTAssertNil(ProtocolFrame.decode(unknown))
    }

    func testFrameStreamSplitsPartials() {
        let framer = FrameStream()
        let part1 = #"{"type":"state","bu"#.data(using: .utf8)!
        let part2 = #"sy":true,"session":""}"#.data(using: .utf8)! + Data([0x0A])
        XCTAssertTrue(framer.feed(part1).isEmpty)
        let frames = framer.feed(part2)
        XCTAssertEqual(frames.count, 1)
        guard case .state(let busy)? = ProtocolFrame.decode(frames[0]) else {
            return XCTFail("stitched frame did not decode")
        }
        XCTAssertTrue(busy)
    }
}
