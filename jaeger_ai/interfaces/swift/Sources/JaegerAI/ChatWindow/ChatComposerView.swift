import AppKit
import SwiftUI

/// Native, multiline composer. All execution actions are supplied by ChatView.
/// Provider connections must be backed by real adapters, never sample menu rows.
struct ChatComposerView: View {
    @Binding var text: String
    @Binding var attachments: [URL]
    let agentName: String
    let modelName: String
    let mode: OperatingMode
    let connected: Bool
    let canSend: Bool
    let isSending: Bool
    let isRecording: Bool
    let isTranscribing: Bool
    let level: Float
    let queuedMessages: [String]
    var agenticTools: Binding<Bool>? = nil
    let onSend: () -> Void
    let onStop: () -> Void
    let onAttach: () -> Void
    let onSelectModel: () -> Void
    let onSelectMode: (OperatingMode) -> Void
    let onDictate: () -> Void
    let onVoice: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let agentic = agenticTools {
                Toggle("Agent tools", isOn: agentic)
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .help("Turn off for a conversation without tool execution")
            }
            if let next = queuedMessages.first {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "text.bubble")
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(queuedMessages.count) queued")
                            .fontWeight(.medium)
                        Text(next).lineLimit(2)
                    }
                    Spacer(minLength: 0)
                }
                .font(.system(size: 12))
                .foregroundStyle(Term.inkDim)
                .padding(.horizontal, 12)
                .accessibilityElement(children: .combine)
            }

            VStack(alignment: .leading, spacing: 14) {
                if !attachments.isEmpty { attachmentList }

                TextField(text: $text,
                          prompt: Text("Message \(agentName)…").foregroundColor(Term.inkDim),
                          axis: .vertical) { Text("Message") }
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .foregroundStyle(Term.ink)
                    .lineLimit(3...8)
                    .onKeyPress(.return) {
                        if NSEvent.modifierFlags.contains(.shift) { return .ignored }
                        if canSend { onSend() }
                        return .handled
                    }
                    .accessibilityLabel("Message \(agentName)")
                    .accessibilityHint("Return sends. Shift Return adds a new line.")

                HStack(spacing: 10) {
                    iconButton("plus", label: "Attach files", action: onAttach)
                        .disabled(!connected)

                    Menu {
                        ForEach(OperatingMode.allCases) { option in
                            Button {
                                onSelectMode(option)
                            } label: {
                                Label(option.rawValue,
                                      systemImage: mode == option ? "checkmark" : "circle")
                            }
                            .help(option.summary)
                        }
                    } label: {
                        Text(mode.rawValue).font(.system(size: 12, weight: .medium))
                    }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                    .disabled(!connected)
                    .help(mode.summary)
                    .accessibilityLabel("Execution mode: \(mode.rawValue)")

                    Spacer(minLength: 0)

                    Button(action: onSelectModel) {
                        HStack(spacing: 4) {
                            Text(modelName)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Image(systemName: "chevron.down").font(.system(size: 9))
                        }
                        .font(.system(size: 12))
                        .frame(maxWidth: 260, alignment: .trailing)
                    }
                    .buttonStyle(.plain)
                    .help("Select model: \(modelName)")
                    .accessibilityLabel("Select model: \(modelName)")

                    iconButton(isRecording ? "stop.circle" : "mic",
                               label: isRecording ? "Stop recording" : "Dictate prompt",
                               action: onDictate)
                        .foregroundStyle(isRecording ? Color.red : Term.inkDim)
                        .disabled(!connected || isTranscribing)
                    iconButton("waveform", label: "Voice conversation", action: onVoice)
                        .disabled(!connected || isTranscribing)

                    if isSending {
                        iconButton("stop.circle.fill", label: "Stop current task", action: onStop)
                    }
                    Button(action: { if canSend { onSend() } }) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(canSend ? ChatPresentation.canvas : Term.inkDim)
                            .frame(width: 32, height: 32)
                            .background(Circle().fill(canSend ? Term.ink : Color.white.opacity(0.06)))
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSend)
                    .accessibilityLabel(isSending ? "Send follow-up" : "Send message")
                    .help(isSending ? "Send follow-up when available" : "Send message")
                }
                .foregroundStyle(Term.inkDim)

                if isTranscribing {
                    Text("Transcribing…").font(.caption).foregroundStyle(Term.inkDim)
                }
                if isRecording { LevelBar(level: level).frame(height: 2) }
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 20).fill(ChatPresentation.composer))
            .overlay(RoundedRectangle(cornerRadius: 20)
                .strokeBorder(isRecording ? Color.red.opacity(0.6) : Color.white.opacity(0.10)))
        }
        .frame(maxWidth: ChatPresentation.contentWidth)
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .padding(.bottom, 14)
        .frame(maxWidth: .infinity)
    }

    private var attachmentList: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(attachments, id: \.path) { url in
                    HStack(spacing: 6) {
                        Image(systemName: "doc")
                        Text(url.lastPathComponent).lineLimit(1)
                        Button {
                            attachments.removeAll { $0 == url }
                        } label: {
                            Image(systemName: "xmark")
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Remove \(url.lastPathComponent)")
                    }
                    .font(.system(size: 11))
                    .foregroundStyle(Term.ink)
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.05)))
                }
            }
        }
    }

    private func iconButton(_ symbol: String, label: String,
                            action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 15))
                .frame(width: 24, height: 28)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
    }
}
