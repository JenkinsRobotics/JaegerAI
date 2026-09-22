import Foundation

extension APIClient {
    func projects() async throws -> ProjectsResponse {
        try await send(endpoint: .projects, method: "GET")
    }

    func createProject(name: String, color: String?) async throws -> ProjectMutationResponse {
        try await send(
            endpoint: .createProject,
            method: "POST",
            body: CreateProjectRequest(name: name, color: color)
        )
    }

    func renameProject(id: String, name: String, color: String?) async throws -> ProjectMutationResponse {
        try await send(
            endpoint: .renameProject,
            method: "POST",
            body: RenameProjectRequest(projectId: id, name: name, color: color)
        )
    }

    func deleteProject(id: String) async throws -> ProjectMutationResponse {
        try await send(
            endpoint: .deleteProject,
            method: "POST",
            body: ProjectIDRequest(projectId: id)
        )
    }
}

private struct CreateProjectRequest: Encodable {
    let name: String
    let color: String?
}

private struct RenameProjectRequest: Encodable {
    let projectId: String
    let name: String
    let color: String?
}

private struct ProjectIDRequest: Encodable {
    let projectId: String
}

