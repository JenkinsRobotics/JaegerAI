import XCTest
@testable import JaegerAI

/// Explicit opt-in: exercises the production desktop view model and real model.
/// Adds a labeled verification exchange; never grants tool permissions.
final class DispatcherLiveTests: XCTestCase {
    @MainActor
    func testLiveDesktopContinuation() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let word = environment["JAEGER_CONTINUITY_WORD"] else {
            throw XCTSkip("Set JAEGER_CONTINUITY_WORD after the browser verification turn")
        }
        let agent = AgentBridge.shared
        try await agent.connect(instance: "jaeger")
        let chat = ChatViewModel(agent: agent)
        await chat.refreshDispatcher()
        for _ in 0..<30 where !chat.messages.contains(where: { $0.text.contains(word) }) {
            try await Task.sleep(for: .milliseconds(250))
            await chat.refreshDispatcher()
        }
        XCTAssertEqual(chat.sessionKey, "dispatcher")
        XCTAssertTrue(chat.messages.contains { $0.text.contains(word) }, chat.dispatcherStatus)
        let originalIDs = chat.messages.map(\.id)
        await chat.refreshDispatcher()
        XCTAssertEqual(chat.messages.map(\.id), originalIDs)
        await chat.send("Continuation verification from the Mac app. What is the newest HANDOFF identifier I gave you in this conversation? Reply with that identifier and MAC-CONFIRMED. No tools or memory writes.")
        XCTAssertTrue(chat.messages.contains { $0.author == .assistant && $0.text.contains(word) && $0.text.contains("MAC-CONFIRMED") }, chat.dispatcherStatus)
        XCTAssertFalse(chat.isSending)
        print("PASS: production Mac view model loaded browser history, preserved message identities and continued the same conversation")
        await agent.disconnect()
    }
    @MainActor
    func testLiveReconnectAfterBackendRestart() async throws {
        guard ProcessInfo.processInfo.environment["JAEGER_CONTINUITY_RESTART"] == "1" else {
            throw XCTSkip("Opt-in restart of the idle Jaeger bridge and adapter")
        }
        let agent = AgentBridge.shared
        try await agent.connect(instance: "jaeger")
        let chat = ChatViewModel(agent: agent)
        for _ in 0..<20 where chat.messages.isEmpty {
            await chat.refreshDispatcher()
            try await Task.sleep(for: .milliseconds(250))
        }
        let ids = chat.messages.map(\.id)
        let text = chat.messages.map(\.text)
        XCTAssertFalse(ids.isEmpty)
        for label in ["jaeger-bridge", "jaeger-hermes-adapter"] {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            process.arguments = ["kickstart", "-k", "gui/\(getuid())/com.jenkinsrobotics.\(label)"]
            try process.run()
            process.waitUntilExit()
            XCTAssertEqual(process.terminationStatus, 0)
        }
        // Disconnect this observer explicitly too, then let the production
        // view model reacquire its bridge and native HTTP connection.
        await agent.disconnect()
        for _ in 0..<40 {
            await chat.refreshDispatcher()
            if chat.dispatcherConnected && agent.isConnected { break }
            try await Task.sleep(for: .seconds(1))
        }
        XCTAssertTrue(chat.dispatcherConnected, chat.dispatcherStatus)
        XCTAssertTrue(agent.isConnected)
        XCTAssertEqual(chat.messages.map(\.id), ids)
        XCTAssertEqual(chat.messages.map(\.text), text)
        print("PASS: backend restart retained transcript, desktop identities and automatic reconnection")
        await agent.disconnect()
    }

}
