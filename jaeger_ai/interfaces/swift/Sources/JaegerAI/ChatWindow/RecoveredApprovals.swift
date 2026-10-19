import SwiftUI

struct RecoveredApproval: Decodable, Identifiable {
    struct Context: Decodable {
        let tool: String?; let target: String?; let summary: String?; let reason: String?
        let task_id: String?; let handoff_id: String?
    }
    let approval_id: String; let session_id: String?; let request_id: String?
    let kind: String; let prompt: String; let options: [String]; let status: String
    let decision: String?; let metadata: Context?
    var id: String { approval_id }
}
struct ApprovalDecisionReceipt: Decodable {
    let approval_id: String; let resolved: Bool; let decision: String
}
@MainActor
protocol RecoveredApprovalClient {
    func pendingApprovals(session: String, request: String) async throws -> [RecoveredApproval]
    func approval(id: String) async throws -> RecoveredApproval
    func decideApproval(id: String, choice: String, session: String, request: String, profile: String) async throws -> ApprovalDecisionReceipt
}
extension GatewayClient: RecoveredApprovalClient {
    func pendingApprovals(session: String, request: String) async throws -> [RecoveredApproval] {
        struct Catalog: Decodable { let approvals: [RecoveredApproval] }
        var query = URLComponents()
        query.queryItems = [URLQueryItem(name:"session_id", value:session), URLQueryItem(name:"request_id", value:request)]
        let data = try await self.request(path:"v1/approvals?" + (query.percentEncodedQuery ?? ""))
        return try JSONDecoder().decode(Catalog.self, from:data).approvals
    }
    func approval(id: String) async throws -> RecoveredApproval {
        let data = try await request(path:"v1/approvals/\(id)")
        return try JSONDecoder().decode(RecoveredApproval.self, from:data)
    }
    func decideApproval(id: String, choice: String, session: String, request: String, profile: String) async throws -> ApprovalDecisionReceipt {
        let data = try await self.request(path:"v1/approvals/\(id)/decision", method:"POST", jsonBody:[
            "decision":choice, "approved":choice != "deny", "expected_session_id":session,
            "expected_request_id":request, "expected_profile":profile])
        return try JSONDecoder().decode(ApprovalDecisionReceipt.self, from:data)
    }
}

@MainActor
final class RecoveredApprovalState: ObservableObject {
    @Published private(set) var cards: [RecoveredApproval] = []
    @Published private(set) var notice: String?
    @Published private(set) var busy = false
    @Published private(set) var context: [GatewayClient.ConversationSnapshot.Activity] = []
    private var identity: String?
    private var session = "", request = "", profile = ""
    private var uncertain: Set<String> = []
    private var active = false
    var profileLabel: String { profile }
    private let client: any RecoveredApprovalClient
    init(client: any RecoveredApprovalClient = GatewayClient.fromEnvironment()) { self.client = client }
    func bind(session: String, request: GatewayClient.RequestState?, profile: String?, context: [GatewayClient.ConversationSnapshot.Activity] = []) {
        let next = session + "/" + (request?.request_id ?? "") + "/" + (profile ?? "")
        if identity != next { cards = []; notice = nil }
        identity = next
        self.session = session; self.request = request?.request_id ?? ""; self.profile = profile ?? ""
        active = ["admitted", "running", "awaiting_approval"].contains(request?.status ?? "") && !self.profile.isEmpty
        self.context = context
        if !active {
            cards = []
            if request?.isActive == true && self.profile.isEmpty {
                notice = "Approval profile is unavailable. Refresh or update Gateway before deciding."
            }
        }
        Task { await refresh() }
    }
    func observeControl(session: String, request: GatewayClient.RequestState?, stopRequested: Bool = false) {
        if stopRequested || self.session != session || self.request != request?.request_id ||
            !["admitted", "running", "awaiting_approval"].contains(request?.status ?? "") { clear() }
    }
    func clear() {
        identity = nil; active = false; cards = []; context = []; notice = nil
    }
    func canDecide(_ card: RecoveredApproval) -> Bool {
        active && !busy && !uncertain.contains(card.id) && matches(card)
    }
    private func matches(_ card: RecoveredApproval) -> Bool {
        card.session_id == session && card.request_id == request && card.status == "pending"
    }
    func refresh() async {
        guard active else { return }
        let captured = identity, selected = session, rid = request
        do {
            let pending = try await client.pendingApprovals(session:selected, request:rid)
            guard captured == identity, active else { return }
            cards = pending.filter(matches)
        } catch {
            guard captured == identity else { return }
            notice = "Pending approvals could not be refreshed. " + error.localizedDescription
        }
    }
    func decide(_ card: RecoveredApproval, choice: String) async {
        guard canDecide(card), card.options.contains(choice), Self.labels[choice] != nil else { return }
        let captured = identity, selected = session, rid = request, boundProfile = profile
        busy = true
        defer { busy = false }
        var submitted = false
        do {
            let fresh = try await client.approval(id:card.id)
            guard captured == identity, active else { return }
            guard matches(fresh), fresh.options.contains(choice), fresh.prompt == card.prompt else {
                notice = "This approval expired, was resolved, or changed. No decision was sent."
                await refresh(); return
            }
            uncertain.insert(card.id) // no duplicate POST after an uncertain result
            submitted = true
            let receipt = try await client.decideApproval(id:card.id, choice:choice, session:selected, request:rid, profile:boundProfile)
            guard captured == identity else { return }
            guard receipt.resolved, receipt.approval_id == card.id, receipt.decision == choice else {
                notice = "Decision outcome unconfirmed. Refresh observes status; this decision will not be resent."
                await refresh(); return
            }
            notice = "Decision recorded — waiting for the runtime; this is not proof the tool completed."
            await refresh()
        } catch {
            guard captured == identity else { return }
            if submitted, let failure = error as? GatewayClient.Failure, [403,404,409].contains(failure.statusCode ?? 0) {
                notice = "Approval denied or stale; no permission was granted by this response. " + error.localizedDescription
            } else {
                notice = submitted ? "Decision outcome unconfirmed; it will not be resent. " + error.localizedDescription : "Approval status unavailable; no decision was sent. " + error.localizedDescription
            }
            await refresh()
        }
    }
    static let labels = ["deny":"Deny", "once":"Approve once", "session":"Allow for this session", "always":"Always allow", "allow":"Approve", "yes":"Approve"]
}

struct RecoveredApprovalCards: View {
    @ObservedObject var state: RecoveredApprovalState
    var body: some View {
        VStack(alignment:.leading, spacing:8) {
            if let notice = state.notice { Text(notice).font(.caption).foregroundColor(.orange) }
            ForEach(state.cards) { card in
                VStack(alignment:.leading, spacing:8) {
                    Text("Pending permission · \(card.kind)").font(.headline)
                    Text(card.prompt).textSelection(.enabled)
                    if let tool = card.metadata?.tool { Text("Tool: " + tool).font(.caption) }
                    if let target = card.metadata?.target { Text("Target: " + target).font(.caption).textSelection(.enabled) }
                    if let summary = card.metadata?.summary { Text(summary).font(.caption) }
                    if let reason = card.metadata?.reason { Text("Reason: " + reason).font(.caption) }
                    if let task = card.metadata?.task_id { Text("Task: " + task).font(.caption) }
                    if let handoff = card.metadata?.handoff_id { Text("Handoff: " + handoff).font(.caption) }
                    ForEach(Array(state.context.enumerated()), id:\.offset) { _, item in
                        Text([item.event, item.tool, item.status, item.text, item.child_run_id, item.task_id].compactMap { $0 }.joined(separator:" · ")).font(.caption)
                    }
                    Text("Profile: \(state.profileLabel)").font(.caption2)
                    Text("Session: \(card.session_id ?? "unknown") · Request: \(card.request_id ?? "unknown")").font(.caption2)
                    if card.options.allSatisfy({ RecoveredApprovalState.labels[$0] == nil }) {
                        Text("This permission uses choices unsupported by this app.").font(.caption).foregroundColor(.orange)
                    }
                    HStack {
                        ForEach(card.options.filter { RecoveredApprovalState.labels[$0] != nil }, id:\.self) { option in
                            Button(RecoveredApprovalState.labels[option]!) { Task { await state.decide(card, choice:option) } }.disabled(!state.canDecide(card))
                        }
                        Button("Refresh status") { Task { await state.refresh() } }
                    }
                }.padding(12).background(Color.secondary.opacity(0.1)).cornerRadius(8)
            }
        }.padding(state.cards.isEmpty && state.notice == nil ? 0 : 10)
    }
}
