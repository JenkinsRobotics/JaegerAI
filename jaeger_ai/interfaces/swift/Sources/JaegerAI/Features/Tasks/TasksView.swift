import SwiftUI

public struct TasksView: View {
    @State private var client = NativePanelClient()
    @State private var jobs: [CronRow] = []
    @State private var error: String?
    @State private var busy = false
    @State private var history: CronHistory?
    @State private var editing: CronRow?
    @State private var showEditor = false
    @State private var name = ""
    @State private var prompt = ""
    @State private var schedule = "0 9 * * *"
    @State private var confirmation: CronRow?
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Scheduled Tasks").font(.headline); Spacer()
                Button("New schedule") { editing = nil; name = ""; prompt = ""; schedule = "0 9 * * *"; showEditor = true }.disabled(busy)
                Button("Refresh") { Task { await refresh() } }.disabled(busy)
            }
            Text("Jaeger scheduler · Times use this Mac’s time zone").font(.caption).foregroundColor(.secondary)
            if busy { ProgressView() }
            if let error { Text(error).foregroundColor(.orange).textSelection(.enabled) }
            if !busy && jobs.isEmpty && error == nil { Text("No scheduled jobs.") }
            List(jobs) { job in
                VStack(alignment: .leading, spacing: 5) {
                    Text(job.name ?? job.id).font(.headline)
                    Text(job.prompt ?? "").lineLimit(3)
                    Text("\(job.schedule_display ?? "") · \(job.state ?? "unknown")").font(.caption)
                    HStack {
                        Button("Edit") { editing = job; name = job.id; prompt = job.prompt ?? ""; schedule = job.schedule_display ?? ""; showEditor = true }
                        Button(job.enabled == false ? "Resume schedule" : "Pause schedule") { Task { await act(job.enabled == false ? "resume" : "pause", ["job_id": job.id]) } }
                        Button("Run once") { confirmation = job }
                        Button("History") { Task { await loadHistory(job.id) } }
                        Button("Delete", role: .destructive) { Task { await act("delete", ["job_id": job.id]) } }
                    }.disabled(busy).buttonStyle(.borderless)
                }.padding(.vertical, 5)
            }
            if let history {
                Text("Execution history").font(.headline)
                ForEach(history.tasks) { task in
                    Text("\(task.state) · \(task.goal)").font(.caption)
                    if let error = task.error { Text(error).foregroundColor(.orange) }
                    ForEach(task.run_history, id: \.run_id) { run in Text("\(run.run_id) · \(run.status)").font(.caption) }
                }
                ForEach(history.requests, id: \.request_id) { request in Text("\(request.request_id) · \(request.status)").font(.caption) }
                if history.tasks.isEmpty && history.requests.isEmpty { Text("No recorded executions.") }
            }
            Text("Run once submits work to Jaeger. Accepted or queued work is not a completed result; tool approvals still apply.").font(.caption).foregroundColor(.secondary)
        }.padding(20).task { await refresh() }
        .confirmationDialog("Run this schedule once?", isPresented: Binding(get: { confirmation != nil }, set: { if !$0 { confirmation = nil } })) {
            if let job = confirmation { Button("Run once") { Task { await act("run", ["job_id": job.id]) } } }
        }
        .sheet(isPresented: $showEditor) {
            VStack(alignment: .leading, spacing: 12) {
                Text(editing == nil ? "Create schedule" : "Edit schedule").font(.headline)
                TextField("Name (optional)", text: $name).disabled(editing != nil)
                TextField("Cron expression", text: $schedule)
                TextEditor(text: $prompt).frame(minHeight: 120)
                Text("Saving an active schedule authorizes future runs of this prompt. Tools still use Jaeger’s normal approval policy.").font(.caption)
                HStack {
                    Button("Cancel") { showEditor = false }; Spacer()
                    Button("Save") {
                        let body = ["name": name, "job_id": editing?.id ?? "", "prompt": prompt, "schedule": schedule]
                        let action = editing == nil ? "create" : "update"
                        showEditor = false
                        Task { await act(action, body) }
                    }.disabled(prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || schedule.isEmpty)
                }
            }.padding(24).frame(width: 480)
        }
    }
    private func act(_ action: String, _ body: [String: Any]) async {
        guard !busy else { return }; busy = true; error = nil
        do { try await client.schedule(action, body: body, operationID: UUID().uuidString) }
        catch { self.error = error.localizedDescription }
        busy = false
        await refresh(clearError: false)
    }
    private func refresh(clearError: Bool = true) async {
        guard !busy else { return }; busy = true
        if clearError { error = nil }
        defer { busy = false }
        do { let result: CronCatalog = try await client.get("v1/schedules"); jobs = result.jobs }
        catch { self.error = error.localizedDescription; jobs = [] }
    }
    private func loadHistory(_ id: String) async {
        guard !busy else { return }; busy = true; error = nil; defer { busy = false }
        var parts = URLComponents(); parts.queryItems = [URLQueryItem(name: "job_id", value: id)]
        do { history = try await client.get("v1/schedules/history?" + (parts.percentEncodedQuery ?? "")) }
        catch { self.error = error.localizedDescription }
    }
}
