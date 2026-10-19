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
}
