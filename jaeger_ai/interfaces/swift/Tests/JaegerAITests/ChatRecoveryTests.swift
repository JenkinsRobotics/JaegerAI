import XCTest
@testable import JaegerAI

@MainActor
private final class RecoveryFixture: ChatRecoveryClient {
    var snapshots: [String: GatewayClient.ConversationSnapshot] = [:]
    var streams: [String: AsyncThrowingStream<GatewayClient.StreamEvent, Error>.Continuation] = [:]
    var onRead: ((String) async -> Void)?
    var onStream: (() -> Void)?
    func createConversation(id: String) async throws {
        let object: [String: Any] = ["session_id": id, "status":"idle", "messages":[], "event_cursor":0, "partial_text":""]
        snapshots[id] = try JSONDecoder().decode(GatewayClient.ConversationSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }
    func conversationSnapshot(id: String) async throws -> GatewayClient.ConversationSnapshot {
        if let onRead { await onRead(id) }
        return snapshots[id]!
    }
    func streamEvents(sessionID: String, lastEventID: Int) -> AsyncThrowingStream<GatewayClient.StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            streams[sessionID] = continuation
            onStream?()
        }
    }
    func snapshot(_ id: String, partial: String = "A", status: String = "running", cursor: Int = 10) throws {
        let object: [String: Any] = ["session_id": id, "status": status,
            "messages": [["role":"user", "content":"Question " + id, "timestamp":1]],
            "latest_request": ["session_id":id, "request_id":"r", "status":status],
            "event_cursor":cursor, "partial_text":partial]
        snapshots[id] = try JSONDecoder().decode(GatewayClient.ConversationSnapshot.self, from: JSONSerialization.data(withJSONObject: object))
    }
    func emit(_ id: String, event: String = "turn.delta", cursor: Int, request: String = "r", delta: String = "B") throws {
        streams[id]?.yield(.init(eventID: cursor, sessionID: id, event: event,
            data: try JSONSerialization.data(withJSONObject: ["request_id":request,"delta":delta]), timestamp:nil))
    }
}

final class ChatRecoveryTests: XCTestCase {
    @MainActor
    func testDelegationIsVisibleWithoutApprovalAndOldRequestIsIgnored() async throws {
        let gateway = RecoveryFixture(); try gateway.snapshot("s")
        let attached = expectation(description: "activity stream attached")
        gateway.onStream = { attached.fulfill() }
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers: false, recoveryGateway: gateway)
        _ = await model.loadSession("s")
        await fulfillment(of: [attached], timeout: 1)
        for (cursor, request) in [(11, "wrong"), (12, "r")] {
            let body: [String: Any] = ["request_id": request, "handoff": [
                "from_agent_id": "native:jaeger", "to_agent_id": "worker", "parent_run_id": "r",
                "child_run_id": "child", "status": "execution_unknown"]]
            gateway.streams["s"]?.yield(.init(eventID: cursor, sessionID: "s", event: "agent.handoff.finished",
                data: try JSONSerialization.data(withJSONObject: body), timestamp: nil))
        }
        for _ in 0..<100 { await Task.yield() }
        XCTAssertEqual(model.conversationActivity.count, 1)
        XCTAssertEqual(model.conversationActivity.first?.status, "execution_unknown")
        XCTAssertEqual(model.conversationActivity.first?.to_agent_id, "worker")
        XCTAssertEqual(model.conversationActivity.first?.child_run_id, "child")
        gateway.onStream = nil
        await model.newChat()
        XCTAssertTrue(model.conversationActivity.isEmpty)
    }

    @MainActor
    func testFailedRecoveryRemainsVisibleAfterTranscriptReplacement() async throws {
        let gateway = RecoveryFixture(); try gateway.snapshot("failed", partial: "", status: "failed")
        let attached = expectation(description: "failed recovery attached")
        gateway.onStream = { attached.fulfill() }
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers: false, recoveryGateway: gateway)
        _ = await model.loadSession("failed")
        await fulfillment(of: [attached], timeout: 1)
        XCTAssertTrue(model.turnControlLabel.contains("failed"))
        XCTAssertFalse(model.hasActiveTurn)
        XCTAssertFalse(model.canStopTurn)
        gateway.onStream = nil
        await model.newChat()
    }

    @MainActor
    func testLatestConversationSelectionWinsDelayedHistoryRead() async throws {
        let gateway = RecoveryFixture()
        try gateway.snapshot("old"); try gateway.snapshot("new")
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers:false, recoveryGateway:gateway)
        let waiting = expectation(description:"old history suspended")
        var release: CheckedContinuation<Void, Never>?
        gateway.onRead = { id in
            if id == "old" { await withCheckedContinuation { release = $0; waiting.fulfill() } }
        }
        let old = Task { await model.loadSession("old") }
        await fulfillment(of:[waiting], timeout:1)
        let loadedNew = await model.loadSession("new")
        XCTAssertTrue(loadedNew)
        release?.resume()
        let loadedOld = await old.value
        XCTAssertFalse(loadedOld)
        XCTAssertEqual(model.sessionKey,"new")
        XCTAssertEqual(model.messages.first?.text,"Question new")
        gateway.onStream = nil
        await model.newChat()
    }
    @MainActor
    func testRecoveredStreamIgnoresDuplicatesAndWrongRequestThenDetachesOnNewChat() async throws {
        let gateway = RecoveryFixture(); try gateway.snapshot("s")
        let attached = expectation(description:"attached")
        gateway.onStream = { attached.fulfill() }
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers:false, recoveryGateway:gateway)
        let loaded = await model.loadSession("s"); XCTAssertTrue(loaded)
        await fulfillment(of:[attached], timeout:1)
        try gateway.emit("s",cursor:11)
        try gateway.emit("s",cursor:11)
        try gateway.emit("s",cursor:12,request:"wrong",delta:"WRONG")
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(model.messages.last?.text,"AB")
        gateway.onStream = nil
        await model.newChat()
        try gateway.emit("s",cursor:13,delta:"LATE")
        for _ in 0..<50 { await Task.yield() }
        XCTAssertTrue(model.messages.isEmpty)
        XCTAssertNotEqual(model.sessionKey,"s")
    }
    @MainActor
    func testExternalCancelRetainsPartialAndNeverDrainsQueue() async throws {
        let gateway = RecoveryFixture(); try gateway.snapshot("s")
        let attached = expectation(description:"attached")
        gateway.onStream = { attached.fulfill() }
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers:false, recoveryGateway:gateway)
        _ = await model.loadSession("s")
        await fulfillment(of:[attached], timeout:1)
        await model.send("Keep queued")
        XCTAssertEqual(model.pendingSends.count,1)
        try gateway.snapshot("s",partial:"Partial at cancellation",status:"cancelled",cursor:11)
        try gateway.emit("s",event:"turn.cancelled",cursor:11)
        for _ in 0..<100 { await Task.yield() }
        XCTAssertTrue(model.queuePausedByStop)
        XCTAssertEqual(model.pendingSends.count,1)
        XCTAssertTrue(model.messages.contains { $0.text == "Partial at cancellation" })
        XCTAssertEqual(model.controlledRequest?.status,"cancelled")
        gateway.onStream = nil
        await model.newChat()
    }

    @MainActor
    func testDroppedStreamRebasesPartialWithoutReplayingSubmission() async throws {
        let gateway = RecoveryFixture(); try gateway.snapshot("s")
        let attached = expectation(description:"first stream")
        let reattached = expectation(description:"reconnected stream")
        var connections = 0
        gateway.onStream = {
            connections += 1
            if connections == 1 { attached.fulfill() } else if connections == 2 { reattached.fulfill() }
        }
        let model = ChatViewModel(agent: AgentBridge(), startBackgroundObservers:false, recoveryGateway:gateway)
        _ = await model.loadSession("s")
        await fulfillment(of:[attached], timeout:1)
        try gateway.emit("s",cursor:11)
        for _ in 0..<50 { await Task.yield() }
        try gateway.snapshot("s",partial:"ABC",cursor:12)
        gateway.streams["s"]?.finish(throwing:NSError(domain:"fixture",code:1))
        await fulfillment(of:[reattached], timeout:4)
        XCTAssertEqual(model.messages.last?.text,"ABC")
        try gateway.emit("s",cursor:13,delta:"D")
        for _ in 0..<50 { await Task.yield() }
        XCTAssertEqual(model.messages.last?.text,"ABCD")
        gateway.onStream = nil
        await model.newChat()
    }

}
