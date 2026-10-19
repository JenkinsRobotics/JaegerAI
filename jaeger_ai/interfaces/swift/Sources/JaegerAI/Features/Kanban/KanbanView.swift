import SwiftUI

public struct KanbanView: View {
    @State private var client = NativePanelClient()
    @State private var boards: [BoardCatalog.Board] = []
    @State private var selected = ""
    @State private var snapshot: BoardSnapshot?
    @State private var error: String?
    @State private var loading = false
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Kanban").font(.headline); Spacer()
                NativePanelWebUIAccess()
                Button("Refresh") { Task { await refresh() } }.disabled(loading)
            }
            if loading { ProgressView("Loading boards…") }
            if let error { Text(error).foregroundColor(.orange) }
            if !boards.isEmpty {
                Picker("Board", selection: $selected) {
                    ForEach(boards) { board in Text(board.name ?? board.slug).tag(board.slug) }
                }.disabled(loading).onChange(of: selected) { _, _ in Task { await loadBoard() } }
            } else if !loading && error == nil { Text("No boards available.") }
            if let snapshot {
                Text("Profile: \(client.context?.profile ?? "unknown") · \(snapshot.read_only == true ? "Read-only backend" : "Backend board snapshot")").font(.caption)
                ScrollView(.horizontal) {
                    HStack(alignment: .top, spacing: 16) {
                        ForEach(snapshot.columns) { column in
                            VStack(alignment: .leading, spacing: 10) {
                                Text("\(column.name.capitalized) (\(column.tasks.count))").font(.headline)
                                if column.tasks.isEmpty { Text("No cards").foregroundColor(.secondary) }
                                ForEach(column.tasks) { card in
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(card.title).font(.headline)
                                        if let description = card.description { Text(description).lineLimit(5) }
                                        Text("\(card.status) · \(card.assignee ?? "Unassigned")").font(.caption)
                                    }.padding(10).frame(width: 230, alignment: .leading)
                                        .background(Color.secondary.opacity(0.1)).cornerRadius(8)
                                }
                            }.frame(width: 250, alignment: .leading)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
            Text("Board edits, dependencies and worker dispatch require a control and approval flow not connected here. Manage these in WebUI. Refresh reads persisted state; card movement is not simulated.").font(.caption).foregroundColor(.secondary)
        }.padding(20).task { await refresh() }
    }
    private func refresh() async {
        guard !loading else { return }
        loading = true; error = nil; snapshot = nil; boards = []
        defer { loading = false }
        do {
            try await client.connect()
            let catalog: BoardCatalog = try await client.get("/api/kanban/boards")
            boards = catalog.boards
            selected = boards.contains(where: { $0.slug == selected }) ? selected : (boards.contains(where: { $0.slug == catalog.current }) ? catalog.current : (boards.first?.slug ?? ""))
            if !boards.isEmpty { snapshot = try await client.get("/api/kanban/board", query: [URLQueryItem(name: "board", value: selected)]) }
        } catch { self.error = error.localizedDescription }
    }
    private func loadBoard() async {
        guard !loading, !selected.isEmpty else { return }
        loading = true; error = nil; snapshot = nil
        defer { loading = false }
        do { snapshot = try await client.get("/api/kanban/board", query: [URLQueryItem(name: "board", value: selected)]) }
        catch { self.error = error.localizedDescription }
    }
}
