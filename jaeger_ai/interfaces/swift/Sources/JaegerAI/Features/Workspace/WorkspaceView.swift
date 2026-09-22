//
//  WorkspaceView.swift
//  JaegerAI / Features / Workspace
//
//  Desktop Git & Workspace browser view ported from Hermex architecture.
//

import SwiftUI

public struct WorkspaceView: View {
    @State private var snapshot = WorkspaceSnapshot.sample
    @State private var selectedFile: GitFileChange? = nil
    @State private var commitMessage = ""
    @State private var isCommitting = false
    @State private var commitSuccessBanner = false

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            // Header Bar
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "folder.badge.gearshape")
                        .font(.system(size: 14))
                        .foregroundColor(Color.cyan)
                    Text("Workspace & Git")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(Term.ink)
                }

                HStack(spacing: 6) {
                    Image(systemName: "arrow.triangle.branch")
                        .font(.system(size: 11))
                        .foregroundColor(Color.cyan)
                    Text(snapshot.branch)
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundColor(Term.ink)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Color.cyan.opacity(0.12))
                .cornerRadius(5)

                Spacer()

                Text("\(snapshot.changes.count) changed files")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.white.opacity(0.02))

            Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

            // Content Split View
            HSplitView {
                // Left pane: Changed files list & commit box
                VStack(spacing: 0) {
                    ScrollView {
                        VStack(spacing: 4) {
                            ForEach(snapshot.changes) { change in
                                fileRow(change)
                                    .onTapGesture {
                                        selectedFile = change
                                    }
                            }
                        }
                        .padding(8)
                    }

                    Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

                    // Commit Box
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Stage & Commit")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundColor(Term.inkDim)

                        TextField("Commit message...", text: $commitMessage)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 12))

                        HStack {
                            if commitSuccessBanner {
                                Text("Committed!")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundColor(Color.green)
                            }
                            Spacer()
                            Button("Commit") {
                                performCommit()
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                            .disabled(commitMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                    .padding(10)
                    .background(Color.white.opacity(0.02))
                }
                .frame(minWidth: 260, idealWidth: 300, maxWidth: 400)

                // Right pane: Diff Viewer
                VStack(spacing: 0) {
                    if let file = selectedFile ?? snapshot.changes.first {
                        diffHeader(for: file)
                        Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)
                        diffBody(for: file)
                    } else {
                        VStack {
                            Spacer()
                            Text("No file selected")
                                .foregroundColor(Term.inkDim)
                            Spacer()
                        }
                    }
                }
                .frame(minWidth: 400, maxWidth: .infinity)
            }
        }
        .onAppear {
            if selectedFile == nil {
                selectedFile = snapshot.changes.first
            }
        }
    }

    private func fileRow(_ change: GitFileChange) -> some View {
        let isSelected = selectedFile?.path == change.path
        return HStack(spacing: 8) {
            Text(change.status.badge)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .foregroundColor(change.status.color)
                .frame(width: 16)

            Text(change.path)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(isSelected ? Term.ink : Term.inkDim)
                .lineLimit(1)
                .truncationMode(.middle)

            Spacer()

            HStack(spacing: 4) {
                if change.additions > 0 {
                    Text("+\(change.additions)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Color.green)
                }
                if change.deletions > 0 {
                    Text("-\(change.deletions)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Color.red)
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(isSelected ? Color.white.opacity(0.08) : Color.clear)
        .cornerRadius(6)
    }

    private func diffHeader(for file: GitFileChange) -> some View {
        HStack {
            Text(file.path)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundColor(Term.ink)
            Spacer()
            HStack(spacing: 8) {
                Text("+\(file.additions)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(Color.green)
                Text("-\(file.deletions)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(Color.red)
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.02))
    }

    private func diffBody(for file: GitFileChange) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(file.diff.split(separator: "\n").enumerated()), id: \.offset) { _, line in
                    diffLine(String(line))
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
    }

    private func diffLine(_ line: String) -> some View {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        let color: Color
        let bg: Color

        if trimmed.hasPrefix("+") && !trimmed.hasPrefix("+++") {
            color = Color(red: 0.4, green: 0.85, blue: 0.4)
            bg = Color.green.opacity(0.08)
        } else if trimmed.hasPrefix("-") && !trimmed.hasPrefix("---") {
            color = Color(red: 0.95, green: 0.4, blue: 0.4)
            bg = Color.red.opacity(0.08)
        } else if trimmed.hasPrefix("@@") {
            color = Color.cyan
            bg = Color.cyan.opacity(0.05)
        } else {
            color = Term.inkDim
            bg = Color.clear
        }

        return Text(line)
            .font(.system(size: 11, design: .monospaced))
            .foregroundColor(color)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 4)
            .padding(.vertical, 1)
            .background(bg)
            .cornerRadius(2)
    }

    private func performCommit() {
        let msg = commitMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty else { return }
        let newCommit = GitCommitInfo(id: UUID().uuidString.prefix(7).lowercased(), message: msg)
        snapshot.recentCommits.insert(newCommit, at: 0)
        commitMessage = ""
        commitSuccessBanner = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            commitSuccessBanner = false
        }
    }
}
