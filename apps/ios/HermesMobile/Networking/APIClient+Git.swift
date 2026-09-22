import Foundation

// Workspace Git calls. Every call is scoped to a chat session via `session_id`; the
// server resolves the workspace path itself, mirroring `APIClient+Workspace.swift`.
extension APIClient {
    func gitInfo(sessionID: String) async throws -> GitInfoResponse {
        try await send(endpoint: .gitInfo(sessionID: sessionID), method: "GET")
    }

    func gitStatus(sessionID: String) async throws -> GitStatusResponse {
        try await send(endpoint: .gitStatus(sessionID: sessionID), method: "GET")
    }

    func gitBranches(sessionID: String) async throws -> GitBranchesResponse {
        try await send(endpoint: .gitBranches(sessionID: sessionID), method: "GET")
    }

    func gitDiff(sessionID: String, path: String, kind: String = "unstaged") async throws -> GitDiffResponse {
        try await send(
            endpoint: .gitDiff(sessionID: sessionID, path: path, kind: kind),
            method: "GET"
        )
    }

    func gitFetch(sessionID: String) async throws -> GitRemoteActionResponse {
        try await send(endpoint: .gitFetch, method: "POST", body: GitSessionRequest(sessionID: sessionID))
    }

    func gitPull(sessionID: String) async throws -> GitRemoteActionResponse {
        try await send(endpoint: .gitPull, method: "POST", body: GitSessionRequest(sessionID: sessionID))
    }

    func gitPush(sessionID: String) async throws -> GitRemoteActionResponse {
        try await send(endpoint: .gitPush, method: "POST", body: GitSessionRequest(sessionID: sessionID))
    }

    func gitCheckout(sessionID: String, target: GitCheckoutTarget) async throws -> GitCheckoutResponse {
        try await send(
            endpoint: .gitCheckout,
            method: "POST",
            body: GitCheckoutRequest(sessionID: sessionID, target: target, includesDirtyMode: true)
        )
    }

    func gitStashCheckout(sessionID: String, target: GitCheckoutTarget) async throws -> GitCheckoutResponse {
        try await send(
            endpoint: .gitStashCheckout,
            method: "POST",
            body: GitCheckoutRequest(sessionID: sessionID, target: target, includesDirtyMode: false)
        )
    }

    // MARK: - Commit flow (issue #315, Slice C)

    func gitStage(sessionID: String, paths: [String]) async throws -> GitMutationResponse {
        try await send(endpoint: .gitStage, method: "POST", body: GitPathsRequest(sessionID: sessionID, paths: paths))
    }

    func gitUnstage(sessionID: String, paths: [String]) async throws -> GitMutationResponse {
        try await send(endpoint: .gitUnstage, method: "POST", body: GitPathsRequest(sessionID: sessionID, paths: paths))
    }

    func gitDiscard(sessionID: String, paths: [String], deleteUntracked: Bool = false) async throws -> GitMutationResponse {
        try await send(
            endpoint: .gitDiscard,
            method: "POST",
            body: GitDiscardRequest(sessionID: sessionID, paths: paths, deleteUntracked: deleteUntracked)
        )
    }

    func gitCommit(sessionID: String, message: String) async throws -> GitCommitResponse {
        try await send(endpoint: .gitCommit, method: "POST", body: GitCommitRequest(sessionID: sessionID, message: message))
    }

    func gitCommitSelected(sessionID: String, message: String, paths: [String]) async throws -> GitCommitResponse {
        try await send(
            endpoint: .gitCommitSelected,
            method: "POST",
            body: GitCommitSelectedRequest(sessionID: sessionID, message: message, paths: paths)
        )
    }

    /// Generate a commit message from the staged diff. Not gated by the destructive flag.
    /// Generation runs an LLM server-side, so it gets a wider timeout than other calls.
    func gitCommitMessage(sessionID: String) async throws -> GitCommitMessageResponse {
        try await send(
            endpoint: .gitCommitMessage,
            method: "POST",
            body: GitSessionRequest(sessionID: sessionID),
            timeout: Self.commitMessageTimeout
        )
    }

    /// Generate a commit message from the selected paths' diff. Not gated by the destructive flag.
    func gitCommitMessageSelected(sessionID: String, paths: [String]) async throws -> GitCommitMessageResponse {
        try await send(
            endpoint: .gitCommitMessageSelected,
            method: "POST",
            body: GitPathsRequest(sessionID: sessionID, paths: paths),
            timeout: Self.commitMessageTimeout
        )
    }

    /// LLM commit-message generation can take far longer than the 60s session default,
    /// especially over a cold tunnel; allow up to two minutes before timing out.
    private static let commitMessageTimeout: TimeInterval = 120
}

private struct GitSessionRequest: Encodable {
    let sessionID: String
}

private struct GitPathsRequest: Encodable {
    let sessionID: String
    let paths: [String]
}

private struct GitDiscardRequest: Encodable {
    let sessionID: String
    let paths: [String]
    let deleteUntracked: Bool
}

private struct GitCommitRequest: Encodable {
    let sessionID: String
    let message: String
}

private struct GitCommitSelectedRequest: Encodable {
    let sessionID: String
    let message: String
    let paths: [String]
}

private struct GitCheckoutRequest: Encodable {
    let sessionID: String
    let ref: String
    let mode: String
    let newBranch: String?
    let track: Bool?
    let dirtyMode: String?

    init(sessionID: String, target: GitCheckoutTarget, includesDirtyMode: Bool) {
        self.sessionID = sessionID
        ref = target.ref
        // Creating a brand-new local branch must use the server's "new" mode. The
        // "local" mode only switches to an existing branch and ignores `new_branch`
        // entirely, so sending it for a create silently switches to `ref` instead
        // (a no-op when already on it). Remote checkouts keep "remote" — that mode
        // creates a tracking branch itself.
        mode = (target.mode == .local && target.newBranch != nil) ? "new" : target.mode.rawValue
        newBranch = target.newBranch
        track = target.track ? true : nil
        dirtyMode = includesDirtyMode ? "block" : nil
    }
}
