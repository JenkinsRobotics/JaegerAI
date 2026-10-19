import XCTest
@testable import JaegerAI

@MainActor
private final class ControlFixture: SessionControlClient {
    var session: GatewayClient.Session
    var onRead: (() async -> Void)?
    var cancellations: [String] = []
    init(_ requestID: String, status: String = "running") {
        session = Self.session(requestID, status: status)
    }
    static func session(_ requestID: String, status: String) -> GatewayClient.Session {
        GatewayClient.Session(session_id: "s", title: nil, profile: nil, workspace: nil,
                              status: status, agent_id: nil,
                              latest_request: .init(session_id: "s", request_id: requestID, status: status))
    }
    func getSessionControl(id: String) async throws -> GatewayClient.Session {
        if let onRead { await onRead() }
        return session
    }
    func cancelTurn(sessionID: String, requestID: String) async throws -> GatewayClient.RequestState {
        cancellations.append(requestID)
        return .init(session_id: sessionID, request_id: requestID, status: "cancelling")
    }
}

@MainActor
private final class VoiceFixture: VoiceGatewayClient {
    struct Admission {
        let session: String
        let request: String
        let continuation: CheckedContinuation<GatewayClient.TurnAccepted, Error>
    }
    var admissions: [Admission] = []
    var cancellations: [String] = []
    var streams: [String] = []
    var onSend: (() -> Void)?
    var onCancel: (() -> Void)?
    func sendTurn(sessionID: String, text: String, requestID: String?) async throws -> GatewayClient.TurnAccepted {
        try await withCheckedThrowingContinuation { continuation in
            admissions.append(Admission(session: sessionID, request: requestID!, continuation: continuation))
            onSend?()
        }
    }
    func accept(_ index: Int) {
        let admission = admissions[index]
        admission.continuation.resume(returning: .init(session_id: admission.session, turn_id: "t", request_id: admission.request, status: "admitted", replayed: nil))
    }
    func cancelTurn(sessionID: String, requestID: String) async throws -> GatewayClient.RequestState {
        cancellations.append(requestID)
        onCancel?()
        return .init(session_id: sessionID, request_id: requestID, status: "cancelling")
    }
    func streamEvents(sessionID: String, lastEventID: Int) -> AsyncThrowingStream<GatewayClient.StreamEvent, Error> {
        streams.append(sessionID)
        return AsyncThrowingStream { $0.finish() }
    }
    func listNotifications(since: Int, limit: Int) async throws -> GatewayClient.ProactiveFeed {
        .init(notifications: [], cursor: since)
    }
}

final class StopRaceTests: XCTestCase {
    @MainActor
    func testStopDoesNotRetargetSuccessorDuringRefresh() async {
        let fixture = ControlFixture("A")
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "s", controlGateway: fixture, startBackgroundObservers: false)
        await model.refreshTurnControl()
        let refreshing = expectation(description: "Stop is refreshing A")
        var release: CheckedContinuation<Void, Never>?
        fixture.onRead = {
            await withCheckedContinuation { continuation in
                release = continuation
                refreshing.fulfill()
            }
        }
        let stop = Task { await model.stopCurrentTurn() }
        await fulfillment(of: [refreshing], timeout: 1)
        fixture.session = ControlFixture.session("B", status: "running")
        release?.resume()
        await stop.value
        XCTAssertTrue(fixture.cancellations.isEmpty)
        XCTAssertEqual(model.controlledRequest?.request_id, "B")
        XCTAssertTrue(model.stopNotice?.contains("successor was not stopped") == true)
    }

    @MainActor
    func testExternalStopPausesQueueUntilExplicitResume() async {
        let fixture = ControlFixture("A")
        let model = ChatViewModel(agent: AgentBridge(), sessionKey: "s", controlGateway: fixture, startBackgroundObservers: false)
        await model.refreshTurnControl()
        await model.send("Retain this follow-up") // queues behind externally running A
        XCTAssertEqual(model.pendingSends.count, 1)
        fixture.session = ControlFixture.session("A", status: "cancelled")
        await model.drainQueuedMessages()
        XCTAssertTrue(model.queuePausedByStop)
        XCTAssertEqual(model.pendingSends.count, 1)
        XCTAssertTrue(model.canResumeQueue)
        fixture.session = ControlFixture.session("B", status: "completed")
        await model.drainQueuedMessages()
        XCTAssertTrue(model.queuePausedByStop)
        XCTAssertEqual(model.pendingSends.count, 1)
        fixture.session = ControlFixture.session("B", status: "execution_unknown")
        await model.refreshTurnControl()
        XCTAssertFalse(model.canResumeQueue)
    }

    @MainActor
    func testLateVoiceAdmissionCannotOverwriteNewTurnOrCancelIt() async {
        let fixture = VoiceFixture()
        let loop = AmbientLoop(gateway: fixture, tts: TTSManager(), detector: SpeechEnergyDetector())
        loop.attach(sessionID: "old-session")
        let oldStarted = expectation(description: "old admission pending")
        fixture.onSend = { oldStarted.fulfill() }
        let old = Task { await loop.send("old") }
        await fulfillment(of: [oldStarted], timeout: 1)
        loop.handleSpeechOnset() // Stop the still-pending old request
        loop.attach(sessionID: "new-session")
        let newStarted = expectation(description: "new admission pending")
        fixture.onSend = { newStarted.fulfill() }
        let newer = Task { await loop.send("new") }
        await fulfillment(of: [newStarted], timeout: 1)
        fixture.accept(1)
        await newer.value
        await Task.yield()
        fixture.accept(0)
        await old.value
        XCTAssertEqual(fixture.cancellations, [fixture.admissions[0].request])
        XCTAssertEqual(fixture.streams, ["new-session"])
        XCTAssertEqual(loop.state, .thinking)
        XCTAssertNil(loop.lastError)
        let newCancelled = expectation(description: "new request independently stopped")
        fixture.onCancel = { newCancelled.fulfill() }
        loop.handleSpeechOnset()
        await fulfillment(of: [newCancelled], timeout: 1)
        XCTAssertEqual(fixture.cancellations, fixture.admissions.map(\.request))
        loop.stop()
    }
}
