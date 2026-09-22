import SwiftUI

struct SessionActionConfirmations: ViewModifier {
    @Bindable var viewModel: SessionListViewModel
    @Binding var sessionPendingDeletion: SessionSummary?
    @Binding var projectPendingDeletion: ProjectSummary?

    let deleteSession: (SessionSummary) -> Void
    let deleteProject: (ProjectSummary) -> Void

    func body(content: Content) -> some View {
        content
            .alert(
                "Session Action Failed",
                isPresented: Binding(
                    get: { viewModel.actionErrorMessage != nil },
                    set: { isPresented in
                        if !isPresented {
                            viewModel.clearActionError()
                        }
                    }
                )
            ) {
                Button("OK") {
                    viewModel.clearActionError()
                }
            } message: {
                Text(viewModel.actionErrorMessage ?? "")
            }
            .alert(
                "Delete Session?",
                isPresented: Binding(
                    get: { sessionPendingDeletion != nil },
                    set: { isPresented in
                        if !isPresented {
                            sessionPendingDeletion = nil
                        }
                    }
                )
            ) {
                Button("Cancel", role: .cancel) {
                    sessionPendingDeletion = nil
                }

                Button("Delete", role: .destructive) {
                    let session = sessionPendingDeletion
                    sessionPendingDeletion = nil

                    if let session {
                        deleteSession(session)
                    }
                }
            } message: {
                Text("This removes the session from the Hermes server. Use this only on a session you no longer need.")
            }
            .alert(
                "Delete Project?",
                isPresented: Binding(
                    get: { projectPendingDeletion != nil },
                    set: { isPresented in
                        if !isPresented {
                            projectPendingDeletion = nil
                        }
                    }
                )
            ) {
                Button("Cancel", role: .cancel) {
                    projectPendingDeletion = nil
                }

                Button("Delete", role: .destructive) {
                    let project = projectPendingDeletion
                    projectPendingDeletion = nil

                    if let project {
                        deleteProject(project)
                    }
                }
            } message: {
                Text("Sessions in this project will be moved to No project. The sessions themselves will not be deleted.")
            }
    }
}
