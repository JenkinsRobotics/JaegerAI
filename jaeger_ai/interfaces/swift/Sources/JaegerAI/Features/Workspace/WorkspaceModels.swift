//
//  WorkspaceModels.swift
//  JaegerAI / Features / Workspace
//
//  Git and Workspace data models ported from Hermex architecture.
//

import Foundation
import SwiftUI

public enum GitFileStatus: String, CaseIterable, Codable, Sendable {
    case modified = "modified"
    case added = "added"
    case deleted = "deleted"
    case untracked = "untracked"

    public var badge: String {
        switch self {
        case .modified: return "M"
        case .added: return "A"
        case .deleted: return "D"
        case .untracked: return "U"
        }
    }

    public var color: Color {
        switch self {
        case .modified: return Color.orange
        case .added: return Color.green
        case .deleted: return Color.red
        case .untracked: return Color.blue
        }
    }
}

public struct GitFileChange: Identifiable, Hashable, Codable, Sendable {
    public var id: String { path }
    public let path: String
    public let status: GitFileStatus
    public let additions: Int
    public let deletions: Int
    public let diff: String

    public init(path: String, status: GitFileStatus, additions: Int = 0, deletions: Int = 0, diff: String = "") {
        self.path = path
        self.status = status
        self.additions = additions
        self.deletions = deletions
        self.diff = diff
    }
}

public struct GitCommitInfo: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public let message: String
    public let author: String
    public let timestamp: String

    public init(id: String, message: String, author: String = "Jaeger", timestamp: String = "Just now") {
        self.id = id
        self.message = message
        self.author = author
        self.timestamp = timestamp
    }
}

public struct WorkspaceSnapshot: Sendable {
    public var branch: String
    public var repoName: String
    public var changes: [GitFileChange]
    public var recentCommits: [GitCommitInfo]

    public static var sample: WorkspaceSnapshot {
        WorkspaceSnapshot(
            branch: "main",
            repoName: "JaegerAI",
            changes: [
                GitFileChange(
                    path: "jaeger_ai/core/frameworks/native_runs.py",
                    status: .modified,
                    additions: 18,
                    deletions: 4,
                    diff: """
                    @@ -613,6 +613,18 @@
                     if kind == "delta":
                    +    raw_text = frame.get("text", "")
                    +    tool_info = parse_tool_line(raw_text)
                    +    if tool_info:
                    +        run.emit("tool.completed", tool=tool_info.get("name"))
                    +    cleaned = clean_transcript_text(raw_text)
                    +    if cleaned:
                    +        run.emit("message.delta", delta=cleaned)
                    """
                ),
                GitFileChange(
                    path: "jaeger_ai/features/roundtable/service.py",
                    status: .modified,
                    additions: 12,
                    deletions: 2,
                    diff: """
                    @@ -215,3 +215,11 @@
                    +    text = clean_transcript_text(snapshot.get('output') or '')
                    +    if is_benign_stderr(err_str) and text.strip():
                    +        outcome['status'] = 'completed'
                    """
                ),
                GitFileChange(
                    path: "apps/macos/Sources/JaegerAI/Features/Kanban/KanbanView.swift",
                    status: .added,
                    additions: 140,
                    deletions: 0,
                    diff: "+ // Native Kanban Board View"
                )
            ],
            recentCommits: [
                GitCommitInfo(id: "3fa98e1", message: "Incorporate adapter protocol and remove donor repo"),
                GitCommitInfo(id: "7bc2104", message: "Fix subordinate react persona lane tool hijacking"),
                GitCommitInfo(id: "e445b90", message: "Broaden intent scoping regex patterns for system/files")
            ]
        )
    }
}
