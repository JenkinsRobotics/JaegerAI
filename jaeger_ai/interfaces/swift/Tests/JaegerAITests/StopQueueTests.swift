import XCTest
@testable import JaegerAI

@MainActor
private final class QueueControlFixture: SessionControlClient {
    var status = "running"
    var reads = 0
    var onRead: (() async -> Void)?
    func getSessionControl(id: String) async throws -> GatewayClient.Session {
        reads += 1
        if let onRead { await onRead() }
        return .init(session_id: id, title: nil, profile: nil, workspace: nil, status: status, agent_id: nil,
                     latest_request: .init(session_id: id, request_id: "A", status: status))
    }
    func cancelTurn(sessionID: String, requestID: String) async throws -> GatewayClient.RequestState {
        XCTFail("No cancellation belongs in queue observation")
        return .init(session_id: sessionID, request_id: requestID, status: "cancelling")
    }
}

@MainActor
private final class QueueDispatcherFixture: DispatcherConversationClient {
    var run = QueueDispatcherFixture.run("A", status: "running")
    var sent: [String] = []
    var nextSendStatus = "completed"
    static func run(_ id: String, status: String) -> DispatcherClient.Run {
        .init(tools: nil, run_id: id, status: status, error: nil, output: "",
              active: status == "running", execution_unknown: status == "execution_unknown", created_at: nil, approvals: nil)
    }
    func snapshot() async throws -> DispatcherClient.Snapshot {
        .init(reports: [], messages: [], revision: "fixture", run: run)
    }
    func send(_ text: String, requestID: String) async throws -> DispatcherClient.Run {
        sent.append(text)
        run = Self.run(requestID, status: nextSendStatus)
        return run
    }
    func request(_ action: String, body: [String: String]?) async throws -> Data {
        XCTFail("These fixtures do not execute dispatcher controls")
        return Data()
    }
}

final class StopQueueTests: XCTestCase {
    @MainActor
    func testQueueWaitsForOverlappingPollInsteadOfStranding() async {
        let fixture = QueueControlFixture()
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "s", controlGateway: fixture, startBackgroundObservers: false)
        await model.refreshTurnControl()
        await model.send("retained")
        XCTAssertEqual(model.pendingSends.count, 1)
        let reading = expectation(description: "periodic poll in flight")
        var release: CheckedContinuation<Void, Never>?
        fixture.onRead = {
            await withCheckedContinuation { continuation in
                release = continuation
                reading.fulfill()
            }
        }
        let poll = Task { await model.refreshTurnControl() }
        await fulfillment(of: [reading], timeout: 1)
        let drain = Task { await model.drainQueuedMessages() }
        await Task.yield()
        XCTAssertEqual(model.pendingSends.count, 1)
        fixture.status = "completed"
        fixture.onRead = nil
        release?.resume()
        _ = await poll.value
        await drain.value
        // The unconnected AgentBridge returns a local transport error; no
        // server/model exists in this fixture. The follow-up was not stranded.
        XCTAssertEqual(model.pendingSends.count, 0)
        XCTAssertFalse(model.queuePausedByStop)
    }

    @MainActor
    func testDispatcherNormalCompletionDrainsViaDispatcherControl() async {
        let control = QueueControlFixture()
        let dispatcher = QueueDispatcherFixture()
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "dispatcher", controlGateway: control,
                                  startBackgroundObservers: false, dispatcherClient: dispatcher)
        await model.refreshTurnControl()
        await model.send("dispatcher follow-up")
        XCTAssertEqual(model.pendingSends.count, 1)
        dispatcher.run = QueueDispatcherFixture.run("A", status: "completed")
        await model.drainQueuedMessages()
        XCTAssertEqual(dispatcher.sent, ["dispatcher follow-up"])
        XCTAssertEqual(model.pendingSends.count, 0)
        XCTAssertEqual(control.reads, 0)
    }

    @MainActor
    func testCancelledDispatcherSubmissionDoesNotFallBackToNative() async {
        let dispatcher = QueueDispatcherFixture()
        dispatcher.run = QueueDispatcherFixture.run("old", status: "completed")
        dispatcher.nextSendStatus = "cancelled"
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "dispatcher", controlGateway: QueueControlFixture(),
                                  startBackgroundObservers: false, dispatcherClient: dispatcher)
        await model.refreshTurnControl()
        await model.send("one scoped submission")
        XCTAssertEqual(dispatcher.sent, ["one scoped submission"])
        XCTAssertTrue(model.messages.isEmpty, "Native fallback would append a second local user/answer pair")
        XCTAssertTrue(model.queuePausedByStop)
    }

    @MainActor
    func testDispatcherStopPausePersistsAndExplicitResumeWorks() async {
        let control = QueueControlFixture()
        let dispatcher = QueueDispatcherFixture()
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "dispatcher", controlGateway: control,
                                  startBackgroundObservers: false, dispatcherClient: dispatcher)
        await model.refreshTurnControl()
        await model.send("keep after Stop")
        dispatcher.run = QueueDispatcherFixture.run("A", status: "cancelled")
        await model.drainQueuedMessages()
        XCTAssertTrue(model.queuePausedByStop)
        XCTAssertEqual(model.pendingSends.count, 1)
        XCTAssertTrue(dispatcher.sent.isEmpty)
        XCTAssertTrue(model.canResumeQueue)
        await model.refreshTurnControl() // A second observation must not resume.
        XCTAssertTrue(model.queuePausedByStop)
        await model.resumeQueuedMessages()
        XCTAssertEqual(dispatcher.sent, ["keep after Stop"])
        XCTAssertFalse(model.queuePausedByStop)
        XCTAssertEqual(model.pendingSends.count, 0)
        XCTAssertEqual(control.reads, 0)
    }
}
