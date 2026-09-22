//
//  ApprovalRequestOverlay.swift
//  JaegerAI / Features / ChatComponents
//
//  Tool approval request modal ported from Hermex architecture.
//

import SwiftUI

public enum ApprovalDecision: String, Sendable {
    case once = "once"
    case always = "always"
    case deny = "deny"
}

public struct ApprovalRequestInfo: Identifiable, Sendable {
    public let id: String
    public let toolName: String
    public let command: String
    public let description: String

    public init(id: String = UUID().uuidString, toolName: String, command: String, description: String = "") {
        self.id = id
        self.toolName = toolName
        self.command = command
        self.description = description
    }
}

public struct ApprovalRequestOverlay: View {
    public let request: ApprovalRequestInfo
    public let onDecision: (ApprovalDecision) -> Void

    public init(request: ApprovalRequestInfo, onDecision: @escaping (ApprovalDecision) -> Void) {
        self.request = request
        self.onDecision = onDecision
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            // Header
            HStack(spacing: 8) {
                Image(systemName: "shield.lefthalf.filled.badge.checkmark")
                    .font(.system(size: 16))
                    .foregroundColor(Color.orange)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Tool Approval Required")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(Term.ink)
                    Text("Jaeger is requesting authorization to run a system action.")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                }
            }

            // Command Box
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Tool: \(request.toolName)")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundColor(Color.orange)
                    Spacer()
                }

                if !request.command.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        Text(request.command)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(Term.ink)
                            .padding(8)
                    }
                    .background(Color(red: 0.05, green: 0.06, blue: 0.08))
                    .cornerRadius(6)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Color.white.opacity(0.08), lineWidth: 1)
                    )
                }

                if !request.description.isEmpty {
                    Text(request.description)
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                }
            }

            // Decision Buttons
            HStack(spacing: 10) {
                Button(role: .destructive) {
                    onDecision(.deny)
                } label: {
                    Text("Deny")
                        .frame(minWidth: 70)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Spacer()

                Button {
                    onDecision(.always)
                } label: {
                    Text("Always Allow")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Button {
                    onDecision(.once)
                } label: {
                    Text("Approve Once")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
            .padding(.top, 4)
        }
        .padding(18)
        .frame(width: 440)
        .background(Color(red: 0.11, green: 0.12, blue: 0.16))
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.orange.opacity(0.35), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.4), radius: 20, x: 0, y: 10)
    }
}
