//
//  SkillModels.swift
//  JaegerAI / Features / Skills
//
//  Agent Skill catalog models ported from Hermex architecture.
//

import Foundation
import SwiftUI

public struct SkillItem: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public let name: String
    public let description: String
    public let category: String
    public let toolCount: Int
    public let isBuiltIn: Bool

    public init(
        id: String = UUID().uuidString,
        name: String,
        description: String,
        category: String = "general",
        toolCount: Int = 1,
        isBuiltIn: Bool = true
    ) {
        self.id = id
        self.name = name
        self.description = description
        self.category = category
        self.toolCount = toolCount
        self.isBuiltIn = isBuiltIn
    }

    public var categoryColor: Color {
        switch category.lowercased() {
        case "core": return Color.orange
        case "code": return Color.blue
        case "files": return Color.green
        case "system": return Color.purple
        case "productivity": return Color.yellow
        case "browser": return Color.cyan
        default: return Color.gray
        }
    }

    public static var sampleCatalog: [SkillItem] {
        [
            SkillItem(name: "terminal", description: "Execute native shell commands in persistent terminal environments.", category: "core", toolCount: 3),
            SkillItem(name: "read_file", description: "Read lines, slices, and exact byte ranges from disk files.", category: "files", toolCount: 2),
            SkillItem(name: "replace_file_content", description: "Surgically patch and replace file content blocks.", category: "files", toolCount: 2),
            SkillItem(name: "grep_search", description: "Fast regex pattern search across code repositories.", category: "code", toolCount: 1),
            SkillItem(name: "browser_subagent", description: "Autonomous web browsing and DOM navigation subagent.", category: "browser", toolCount: 4),
            SkillItem(name: "kanban", description: "Visual and structured board management for tasks and sprints.", category: "productivity", toolCount: 5),
            SkillItem(name: "doctor", description: "System diagnostics, environment integrity, and preflight auditing.", category: "system", toolCount: 2),
            SkillItem(name: "roundtable", description: "Multi-agent peer deliberation, review, and consensus synthesis.", category: "core", toolCount: 3)
        ]
    }
}
