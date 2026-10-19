import SwiftUI

/// Uses the same WebKit store as the native adapters, including HttpOnly login cookies.
struct NativePanelWebUIAccess: View {
    @State private var presented = false
    var body: some View {
        Button("Open WebUI / Sign in") { presented = true }
            .sheet(isPresented: $presented) {
                VStack(spacing: 0) {
                    HStack {
                        Text("WebUI session · Close and refresh the native panel after signing in")
                        Spacer()
                        Button("Close") { presented = false }
                    }.padding()
                    WebUIChatContainer()
                }.frame(minWidth: 820, minHeight: 620)
            }
    }
}
