import SwiftUI

public struct KanbanView: View {
    public init() {}

    public var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "network.slash")
                .font(.largeTitle)
                .foregroundColor(Term.inkDim)
            Text("Kanban")
                .font(.headline)
            Text("Native connection unsupported")
                .font(.subheadline)
            Text("Boards belong to the WebUI Kanban service. This native app does not yet have an authenticated board adapter. Board loading, edits and dispatch are unavailable here.")
                .foregroundColor(Term.inkDim)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
