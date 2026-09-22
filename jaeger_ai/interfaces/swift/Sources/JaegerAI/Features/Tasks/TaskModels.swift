//
//  TaskModels.swift
//  JaegerAI / Features / Tasks
//
//  Scheduled tasks and cron job models ported from Hermex architecture.
//

import Foundation
import SwiftUI

public enum TaskRunStatus: String, CaseIterable, Codable, Sendable {
    case idle = "idle"
    case running = "running"
    case success = "success"
    case failed = "failed"

    public var color: Color {
        switch self {
        case .idle: return Color.gray
        case .running: return Color.blue
        case .success: return Color.green
        case .failed: return Color.red
        }
    }
}

public struct ScheduledTask: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public var name: String
    public var schedule: String
    public var command: String
    public var enabled: Bool
    public var lastRun: String
    public var nextRun: String
    public var status: TaskRunStatus

    public init(
        id: String = UUID().uuidString,
        name: String,
        schedule: String,
        command: String,
        enabled: Bool = true,
        lastRun: String = "Never",
        nextRun: String = "In 1h",
        status: TaskRunStatus = .idle
    ) {
        self.id = id
        self.name = name
        self.schedule = schedule
        self.command = command
        self.enabled = enabled
        self.lastRun = lastRun
        self.nextRun = nextRun
        self.status = status
    }

    public static var sampleTasks: [ScheduledTask] {
        [
            ScheduledTask(
                name: "Nightly Workspace Health Check",
                schedule: "0 3 * * *",
                command: "jaeger doctor --json",
                enabled: true,
                lastRun: "Today, 03:00 AM",
                nextRun: "Tomorrow, 03:00 AM",
                status: .success
            ),
            ScheduledTask(
                name: "Fabric Supervisor Heartbeat",
                schedule: "*/5 * * * *",
                command: "jaeger fabric ping",
                enabled: true,
                lastRun: "2 mins ago",
                nextRun: "In 3 mins",
                status: .success
            ),
            ScheduledTask(
                name: "Memory Consolidation & Pruning",
                schedule: "0 0 * * 0",
                command: "jaeger memory compact",
                enabled: true,
                lastRun: "Sunday, 12:00 AM",
                nextRun: "Next Sunday",
                status: .idle
            ),
            ScheduledTask(
                name: "Model Certification & Benchmark Sync",
                schedule: "0 12 1 * *",
                command: "jaeger bench verify",
                enabled: false,
                lastRun: "Sep 1, 12:00 PM",
                nextRun: "Paused",
                status: .idle
            )
        ]
    }
}
