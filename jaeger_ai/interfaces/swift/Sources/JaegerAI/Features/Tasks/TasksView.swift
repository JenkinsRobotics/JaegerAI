//
//  TasksView.swift
//  JaegerAI / Features / Tasks
//
//  Desktop scheduled tasks & cron inspector view ported from Hermex architecture.
//

import SwiftUI

public struct TasksView: View {
    @State private var tasks = ScheduledTask.sampleTasks
    @State private var filterText = ""
    @State private var selectedTask: ScheduledTask? = nil

    public init() {}

    private var filteredTasks: [ScheduledTask] {
        let q = filterText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if q.isEmpty { return tasks }
        return tasks.filter {
            $0.name.lowercased().contains(q) || $0.command.lowercased().contains(q) || $0.schedule.contains(q)
        }
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Header Bar
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "clock.badge.checkmark")
                        .font(.system(size: 14))
                        .foregroundColor(Color.indigo)
                    Text("Scheduled Tasks & Cron")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(Term.ink)
                }

                Spacer()

                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundColor(Term.inkDim)
                        .font(.system(size: 11))
                    TextField("Search tasks...", text: $filterText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundColor(Term.ink)
                        .frame(width: 140)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.white.opacity(0.06))
                .cornerRadius(6)

                Text("\(tasks.filter(\.enabled).count) active")
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundColor(Color.green)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.green.opacity(0.12))
                    .cornerRadius(5)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.white.opacity(0.02))

            Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

            // Task List
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(filteredTasks) { task in
                        taskCard(task)
                    }
                }
                .padding(16)
            }
        }
    }

    private func taskCard(_ task: ScheduledTask) -> some View {
        HStack(spacing: 14) {
            // Status Icon
            Circle()
                .fill(task.enabled ? task.status.color : Color.gray.opacity(0.4))
                .frame(width: 10, height: 10)

            // Details
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(task.name)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(task.enabled ? Term.ink : Term.inkDim)

                    Text(task.schedule)
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundColor(Color.indigo)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.indigo.opacity(0.15))
                        .cornerRadius(4)
                }

                Text(task.command)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)

                HStack(spacing: 12) {
                    Text("Last run: \(task.lastRun)")
                        .font(.system(size: 10))
                        .foregroundColor(Term.inkDim)
                    Text("Next: \(task.nextRun)")
                        .font(.system(size: 10))
                        .foregroundColor(Term.inkDim)
                }
                .padding(.top, 2)
            }

            Spacer()

            // Actions & Toggle
            HStack(spacing: 12) {
                Button("Run Now") {
                    triggerRun(task.id)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Toggle("", isOn: Binding(
                    get: { task.enabled },
                    set: { val in toggleTask(task.id, enabled: val) }
                ))
                .toggleStyle(.switch)
                .controlSize(.small)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.02))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }

    private func toggleTask(_ id: String, enabled: Bool) {
        if let idx = tasks.firstIndex(where: { $0.id == id }) {
            tasks[idx].enabled = enabled
        }
    }

    private func triggerRun(_ id: String) {
        if let idx = tasks.firstIndex(where: { $0.id == id }) {
            tasks[idx].status = .running
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                tasks[idx].status = .success
                tasks[idx].lastRun = "Just now"
            }
        }
    }
}
