//
//  KanbanModels.swift
//  JaegerAI / Features / Kanban
//
//  Ported from Hermex Kanban architecture for native desktop management.
//

import Foundation
import SwiftUI

public enum KanbanStatus: String, CaseIterable, Identifiable, Codable, Sendable {
    case backlog = "backlog"
    case todo = "todo"
    case inProgress = "in_progress"
    case review = "review"
    case done = "done"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .backlog: return "Backlog"
        case .todo: return "To Do"
        case .inProgress: return "In Progress"
        case .review: return "Review"
        case .done: return "Done"
        }
    }

    public var color: Color {
        switch self {
        case .backlog: return Color.gray
        case .todo: return Color.blue
        case .inProgress: return Color.orange
        case .review: return Color.purple
        case .done: return Color.green
        }
    }

    public var icon: String {
        switch self {
        case .backlog: return "archivebox"
        case .todo: return "circle"
        case .inProgress: return "arrow.triangle.2.circlepath"
        case .review: return "eye"
        case .done: return "checkmark.circle.fill"
        }
    }
}

public struct KanbanCard: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public var title: String
    public var body: String
    public var status: KanbanStatus
    public var priority: Int // 1 = Urgent, 2 = High, 3 = Medium, 4 = Low
    public var assignee: String?
    public var tags: [String]
    public var updatedAt: Date

    public init(
        id: String = UUID().uuidString,
        title: String,
        body: String = "",
        status: KanbanStatus = .todo,
        priority: Int = 3,
        assignee: String? = nil,
        tags: [String] = [],
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.body = body
        self.status = status
        self.priority = priority
        self.assignee = assignee
        self.tags = tags
        self.updatedAt = updatedAt
    }

    public var priorityLabel: String {
        switch priority {
        case 1: return "Urgent"
        case 2: return "High"
        case 3: return "Medium"
        default: return "Low"
        }
    }

    public var priorityColor: Color {
        switch priority {
        case 1: return Color.red
        case 2: return Color.orange
        case 3: return Color.yellow
        default: return Color.gray
        }
    }
}

public struct KanbanBoard: Identifiable, Codable, Sendable {
    public let id: String
    public var name: String
    public var cards: [KanbanCard]

    public init(id: String = "default", name: String = "Main Board", cards: [KanbanCard] = []) {
        self.id = id
        self.name = name
        self.cards = cards
    }

    public static var sample: KanbanBoard {
        KanbanBoard(cards: [
            KanbanCard(
                title: "Incorporate Hermex UI into Jaeger",
                body: "Port Kanban, Git Workspace, Tasks, and LaTeX math into macOS desktop app.",
                status: .inProgress,
                priority: 1,
                assignee: "Jaeger Core",
                tags: ["Architecture", "SwiftUI"]
            ),
            KanbanCard(
                title: "Refactor Tool Execution Scoping",
                body: "Broaden regex patterns for system, process, and files tools.",
                status: .done,
                priority: 2,
                assignee: "Agent Runtime",
                tags: ["Tools", "Cognition"]
            ),
            KanbanCard(
                title: "iOS Multiplatform Target Setup",
                body: "Configure Xcode targets for connected iPhone/iPad deployment.",
                status: .inProgress,
                priority: 2,
                assignee: "Mobile Seam",
                tags: ["iOS", "Xcode"]
            ),
            KanbanCard(
                title: "Live Activity & Dynamic Island",
                body: "Keep long-running autonomous runs visible on iPhone Lock Screen.",
                status: .todo,
                priority: 3,
                assignee: "Mobile Seam",
                tags: ["ActivityKit"]
            ),
            KanbanCard(
                title: "Scheduled Cron Tasks Monitoring",
                body: "Display heartbeat and background worker health in desktop tasks tab.",
                status: .todo,
                priority: 3,
                assignee: "Scheduler",
                tags: ["Cron", "Daemon"]
            )
        ])
    }
}
