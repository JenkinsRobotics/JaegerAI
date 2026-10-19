import SwiftUI

public struct TasksView: View {
    public init() {}

    public var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "network.slash")
                .font(.largeTitle)
                .foregroundColor(Term.inkDim)
            Text("Scheduled Tasks & Cron")
                .font(.headline)
            Text("Native connection unsupported")
                .font(.subheadline)
            Text("Scheduled jobs belong to the runner-local WebUI scheduler. This native app does not yet have an authenticated scheduler adapter. Listing, Run Now, pause and resume are unavailable here.")
                .foregroundColor(Term.inkDim)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
