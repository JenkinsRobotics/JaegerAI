import XCTest
@testable import JaegerAI

@MainActor
private final class ApprovalFixture: RecoveredApprovalClient {
    var pending: [RecoveredApproval] = []
    var fresh: RecoveredApproval!
    var posts: [String] = []
    var uncertain = false
    var beforeRead: (() async -> Void)?
    func pendingApprovals(session: String, request: String) async throws -> [RecoveredApproval] { pending }
    func approval(id: String) async throws -> RecoveredApproval {
        if let beforeRead { await beforeRead() }
        return fresh
    }
    func decideApproval(id: String, choice: String, session: String, request: String, profile: String) async throws -> ApprovalDecisionReceipt {
        posts.append([id,choice,session,request,profile].joined(separator:"/"))
        if uncertain { throw NSError(domain:"uncertain fixture",code:1) }
        pending = []
        return ApprovalDecisionReceipt(approval_id:id,resolved:true,decision:choice)
    }
    func card(session: String = "s", request: String = "r", status: String = "pending") throws -> RecoveredApproval {
        let data = try JSONSerialization.data(withJSONObject:["approval_id":"a", "session_id":session, "request_id":request, "kind":"tool_confirm", "prompt":"Allow fixture tool?", "options":["once","deny"], "status":status])
        return try JSONDecoder().decode(RecoveredApproval.self,from:data)
    }
}
@MainActor
private final class SuspendedStopFixture: SessionControlClient {
    var beforeRead: (() async -> Void)?
    var onCancel: (() -> Void)?
    func getSessionControl(id: String) async throws -> GatewayClient.Session {
        if let beforeRead { await beforeRead() }
        return .init(session_id:"s",title:nil,profile:"jaeger",workspace:nil,status:"running",agent_id:nil,
                     latest_request:.init(session_id:"s",request_id:"r",status:"running"))
    }
    func cancelTurn(sessionID: String, requestID: String) async throws -> GatewayClient.RequestState {
        onCancel?()
        return .init(session_id:sessionID,request_id:requestID,status:"cancelling")
    }
}

final class RecoveredApprovalTests: XCTestCase {
    @MainActor
    func testOnlyMatchingCardAndOfferedChoiceCanBeSubmitted() async throws {
        let client = ApprovalFixture(); let card = try client.card()
        client.pending = [card, try client.card(session:"other")]; client.fresh = card
        let state = RecoveredApprovalState(client:client)
        state.bind(session:"s",request:.init(session_id:"s",request_id:"r",status:"awaiting_approval"),profile:"jaeger")
        await state.refresh()
        XCTAssertEqual(state.cards.count,1)
        await state.decide(card,choice:"always")
        XCTAssertTrue(client.posts.isEmpty)
        await state.decide(card,choice:"once")
        XCTAssertEqual(client.posts,["a/once/s/r/jaeger"])
        XCTAssertTrue(state.cards.isEmpty)
    }
    @MainActor
    func testExpiredCardIsNotSent() async throws {
        let client = ApprovalFixture(); let card = try client.card()
        client.pending = [card]; client.fresh = try client.card(status:"resolved")
        let state = RecoveredApprovalState(client:client)
        state.bind(session:"s",request:.init(session_id:"s",request_id:"r",status:"running"),profile:"jaeger")
        await state.refresh(); client.pending = []
        await state.decide(card,choice:"once")
        XCTAssertTrue(client.posts.isEmpty)
        XCTAssertTrue(state.notice?.contains("expired") == true)
    }
    @MainActor
    func testUncertainDecisionIsNeverResent() async throws {
        let client = ApprovalFixture(); let card = try client.card()
        client.pending = [card]; client.fresh = card; client.uncertain = true
        let state = RecoveredApprovalState(client:client)
        state.bind(session:"s",request:.init(session_id:"s",request_id:"r",status:"running"),profile:"jaeger")
        await state.refresh()
        await state.decide(card,choice:"once")
        await state.refresh()
        await state.decide(card,choice:"once")
        XCTAssertEqual(client.posts.count,1)
        XCTAssertFalse(state.canDecide(card))
    }
    @MainActor
    func testSwitchDuringPreflightCannotSubmitOldCard() async throws {
        let client = ApprovalFixture(); let card = try client.card()
        client.pending = [card]; client.fresh = card
        let state = RecoveredApprovalState(client:client)
        state.bind(session:"s",request:.init(session_id:"s",request_id:"r",status:"running"),profile:"jaeger")
        await state.refresh()
        let waiting = expectation(description:"preflight suspended")
        var release: CheckedContinuation<Void,Never>?
        client.beforeRead = { await withCheckedContinuation { release = $0; waiting.fulfill() } }
        let decision = Task { await state.decide(card,choice:"once") }
        await fulfillment(of:[waiting],timeout:1)
        state.clear()
        release?.resume(); await decision.value
        XCTAssertTrue(client.posts.isEmpty)
    }
    @MainActor
    func testStopClickInvalidatesCardBeforeSuspendedRefreshAndPreflight() async throws {
        let client = ApprovalFixture(); let card = try client.card()
        client.pending = [card]; client.fresh = card
        let state = RecoveredApprovalState(client:client)
        let control = SuspendedStopFixture()
        let model = ChatViewModel(agent:AgentBridge(),sessionKey:"s",controlGateway:control,
                                  startBackgroundObservers:false,recoveredApprovalState:state)
        await model.refreshTurnControl()
        state.bind(session:"s",request:model.controlledRequest,profile:"jaeger")
        await state.refresh()
        let preflightWaiting = expectation(description:"approval preflight suspended")
        var releasePreflight: CheckedContinuation<Void,Never>?
        client.beforeRead = { await withCheckedContinuation { releasePreflight = $0; preflightWaiting.fulfill() } }
        let decision = Task { await state.decide(card,choice:"once") }
        await fulfillment(of:[preflightWaiting],timeout:1)
        let stopWaiting = expectation(description:"Stop refresh suspended")
        let cancelled = expectation(description:"correct cancellation dispatched")
        var releaseStop: CheckedContinuation<Void,Never>?
        control.beforeRead = { await withCheckedContinuation { releaseStop = $0; stopWaiting.fulfill() } }
        control.onCancel = { cancelled.fulfill() }
        model.requestStopCurrentTurn()
        XCTAssertTrue(state.cards.isEmpty) // no Task/network yield is needed to disable actions
        XCTAssertFalse(state.canDecide(card))
        await fulfillment(of:[stopWaiting],timeout:1)
        await state.decide(card,choice:"once")
        state.bind(session:"s",request:model.controlledRequest,profile:"jaeger") // stale refresh cannot reopen it
        XCTAssertFalse(state.canDecide(card))
        releasePreflight?.resume(); await decision.value
        XCTAssertTrue(client.posts.isEmpty)
        releaseStop?.resume()
        await fulfillment(of:[cancelled],timeout:1)
        XCTAssertTrue(client.posts.isEmpty)
    }

}
