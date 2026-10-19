import SwiftUI

public struct TasksView: View {
    @State private var client = NativePanelClient()
    @State private var catalog: CronCatalog?
    @State private var error: String?
    @State private var loading = false
    @State private var running: [String: Double] = [:]
    @State private var history: CronHistory?
    @State private var historyJob: String?
    @State private var historyLoading = false
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Scheduled Tasks & Cron").font(.headline); Spacer()
                NativePanelWebUIAccess()
                Button("Refresh") { Task { await refresh() } }.disabled(loading || historyLoading)
            }
            if loading { ProgressView("Loading scheduler…") }
            if let error { Text(error).foregroundColor(.orange) }
            if let catalog {
                Text("Profile: \(client.context?.profile ?? "unknown") · Runner-local scheduler").font(.caption)
                if catalog.cron_unavailable == true { Text("The connected runner does not provide the scheduler.") }
                else if catalog.jobs.isEmpty { Text("No scheduled jobs in this profile.") }
                if let hidden = catalog.other_profile_count, hidden > 0 {
                    Text("\(hidden) jobs in other profiles are hidden.").font(.caption)
                }
                List(catalog.jobs) { job in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(job.name ?? job.id).font(.headline)
                        Text(job.schedule_display ?? "Schedule not provided")
                        if let elapsed = running[job.id] { Text("Running · \(Int(elapsed)) seconds at last refresh").foregroundColor(.orange) }
                        Text("\(job.enabled == false ? "Paused" : (job.state ?? "State unknown")) · Last run: \(job.last_status ?? "unknown")").font(.caption)
                    Button("Run history") { Task { await loadHistory(job.id) } }.disabled(historyLoading)
                    }.padding(.vertical, 5)
                }
            }
            if historyLoading { ProgressView("Loading run history…") }
            if let history {
                Text("Run history · \(historyJob ?? "") (\(history.total) records)").font(.headline)
                if history.runs.isEmpty { Text("No stored run output.") }
                ForEach(history.runs.prefix(10)) { run in
                    Text("\(run.filename) · \(Date(timeIntervalSince1970: run.modified).formatted())").font(.caption)
                }
                Text("Output records are not proof of successful completion.").font(.caption).foregroundColor(.secondary)
            }
            Spacer(minLength: 0)
            Text("Run, edit, pause and resume require the scheduler control and approval flow, which is not connected in this native panel. Manage these in WebUI.").font(.caption).foregroundColor(.secondary)
        }.padding(20).task { await refresh() }
    }
    private func loadHistory(_ id: String) async {
        guard !loading, !historyLoading else { return }
        historyLoading = true; history = nil; historyJob = id; error = nil
        defer { historyLoading = false }
        do { history = try await client.get("/api/crons/history", query: [URLQueryItem(name: "job_id", value: id), URLQueryItem(name: "limit", value: "10")]) }
        catch { self.error = error.localizedDescription }
    }
    private func refresh() async {
        guard !loading else { return }
        loading = true; error = nil; catalog = nil; running = [:]; history = nil
        defer { loading = false }
        do {
            try await client.connect()
            let jobs: CronCatalog = try await client.get("/api/crons")
            catalog = jobs
            if jobs.cron_unavailable != true {
                let status: CronRunning = try await client.get("/api/crons/status")
                running = status.running
            }
        }
        catch { self.error = error.localizedDescription }
    }
}
