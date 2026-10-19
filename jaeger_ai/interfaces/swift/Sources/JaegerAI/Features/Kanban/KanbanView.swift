import SwiftUI

public struct KanbanView: View {
    @State private var client = NativePanelClient()
    @State private var tasks: [NativeTask] = []
    @State private var error: String?
    @State private var busy = false
    @State private var editor = false
    @State private var editing: NativeTask?
    @State private var goal = ""
    @State private var run: NativeTask?
    private let columns: [(String, [String])] = [
        ("Proposed", ["paused"]), ("Queued", ["queued"]), ("Running", ["running"]),
        ("Needs attention", ["needs_owner", "blocked", "failed"]),
        ("Finished", ["completed", "completed_verified", "cancelled"])
    ]
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Tasks & Board").font(.headline); Spacer()
                Button("New task") { editing = nil; goal = ""; editor = true }.disabled(busy)
                Button("Refresh") { Task { await refresh() } }.disabled(busy)
            }
            if busy { ProgressView() }
            if let error { Text(error).foregroundColor(.orange).textSelection(.enabled) }
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: 16) {
                    ForEach(columns, id: \.0) { column in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(column.0).font(.headline)
                            let cards = tasks.filter { column.1.contains($0.state) }
                            if cards.isEmpty { Text("No tasks").foregroundColor(.secondary) }
                            ForEach(cards) { task in
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(task.goal).font(.headline).textSelection(.enabled)
                                    Text("\(task.state) · \(task.agent_id) · \(task.runner)").font(.caption)
                                    Text(task.task_id).font(.caption2).textSelection(.enabled)
                                    if let error = task.error { Text(error).foregroundColor(.orange) }
                                    ForEach(task.run_history, id: \.run_id) { record in
                                        Text("Run \(record.run_id): \(record.status)").font(.caption)
                                        if let error = record.error { Text(error).font(.caption).foregroundColor(.orange) }
                                    }
                                    if task.editable {
                                        Button("Edit proposal") { editing = task; goal = task.goal; editor = true }
                                        Button("Approve & queue") { run = task }
                                    }
                                    if ["paused", "queued", "running"].contains(task.state) {
                                        Button("Cancel", role: .destructive) { Task { await action("v1/tasks/\(task.id)/cancel", [:]) } }
                                    }
                                }.padding(10).frame(width: 250, alignment: .leading)
                                    .background(Color.secondary.opacity(0.1)).cornerRadius(8)
                            }
                        }.frame(width: 270, alignment: .leading)
                    }
                }
            }.disabled(busy)
            Text("These are Gateway-owned tasks. Only verified completion counts as verified work. Proposed tasks run only after approval; uncertain work is not retried here.").font(.caption).foregroundColor(.secondary)
        }.padding(20).task { await refresh() }
        .confirmationDialog("Approve and queue this task?", isPresented: Binding(get: { run != nil }, set: { if !$0 { run = nil } })) {
            if let task = run { Button("Approve & queue") { Task { await action("v1/tasks/\(task.id)/approve", ["expected_updated_at": task.updated_at]) } } }
        }
        .sheet(isPresented: $editor) {
            VStack(alignment: .leading, spacing: 12) {
                Text(editing == nil ? "New task proposal" : "Edit proposal").font(.headline)
                TextEditor(text: $goal).frame(minHeight: 150)
                Text("Saving creates a paused proposal. It does not run the task.").font(.caption)
                HStack {
                    Button("Cancel") { editor = false }; Spacer()
                    Button("Save proposal") {
                        let text = goal; let task = editing; editor = false
                        Task {
                            if let task { await action("v1/tasks/\(task.id)", ["goal": text, "expected_updated_at": task.updated_at], method: "PATCH") }
                            else { await create(text) }
                        }
                    }.disabled(goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }.padding(24).frame(width: 480)
        }
    }
    private func create(_ text: String) async {
        guard !busy else { return }; busy = true; error = nil
        let id = UUID().uuidString
        do {
            _ = try await client.gateway.request(path: "v1/sessions", method: "POST", jsonBody: ["session_id": "native:task-board", "title": "Task board", "profile": "jaeger"])
            try await client.mutate("v1/tasks", body: ["session_id": "native:task-board", "goal": text, "request_id": id, "proposal": true])
        } catch { self.error = "\(error.localizedDescription) Refresh to reconcile before submitting again." }
        busy = false; await refresh(clearError: false)
    }
    private func action(_ path: String, _ body: [String: Any], method: String = "POST") async {
        guard !busy else { return }; busy = true; error = nil
        do { try await client.mutate(path, body: body, method: method) }
        catch { self.error = "\(error.localizedDescription) Refresh to inspect the current result." }
        busy = false; await refresh(clearError: false)
    }
    private func refresh(clearError: Bool = true) async {
        guard !busy else { return }; busy = true; if clearError { error = nil }; defer { busy = false }
        do { let payload: NativeTasks = try await client.get("v1/tasks"); tasks = payload.tasks }
        catch { self.error = error.localizedDescription; tasks = [] }
    }
}
