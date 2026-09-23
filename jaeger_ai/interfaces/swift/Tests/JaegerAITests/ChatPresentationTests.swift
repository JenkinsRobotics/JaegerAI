import AppKit
import SwiftUI
import XCTest
@testable import JaegerAI

final class ChatPresentationTests: XCTestCase {
    func testModelLabelPreservesProviderModelVariant() {
        XCTAssertEqual(ChatPresentation.modelLabel("  model-family:large-thinking  "),
                       "model-family:large-thinking")
        XCTAssertEqual(ChatPresentation.modelLabel(nil), "Choose model")
        XCTAssertEqual(ChatPresentation.modelLabel(" \n"), "Choose model")
    }

    func testSendRequiresConnectionAndRetainsDraftWhileDispatcherIsBusy() {
        func allowed(connected: Bool = true, transcribing: Bool = false,
                     switching: Bool = false, busy: Bool = false) -> Bool {
            ChatPresentation.canSubmit(text: "A draft", attachmentCount: 0,
                connected: connected, transcribing: transcribing,
                switchingSession: switching, dispatcherBusy: busy)
        }
        XCTAssertTrue(allowed())
        XCTAssertFalse(allowed(connected: false))
        XCTAssertFalse(allowed(transcribing: true))
        XCTAssertFalse(allowed(switching: true))
        XCTAssertFalse(allowed(busy: true))
    }

    func testAttachmentOnlySendAndEmptyDraft() {
        for count in [0, 1] {
            XCTAssertEqual(ChatPresentation.canSubmit(text: " \n", attachmentCount: count,
                connected: true, transcribing: false, switchingSession: false,
                dispatcherBusy: false), count > 0)
        }
    }

    func testActivityUsesActualToolNamesWithoutPersonaSpecificPrefixes() {
        XCTAssertEqual(ChatPresentation.toolName("mcp__any-server__read_file"), "read file")
        XCTAssertEqual(ChatPresentation.toolName("terminal"), "terminal")
        let items = [ToolCallItem(name: "read_file", ok: false)]
        XCTAssertEqual(ChatPresentation.activityTitle(items: items, running: true), "Using read file")
        XCTAssertEqual(ChatPresentation.activityTitle(items: items, running: false), "Used read file")
        XCTAssertFalse(ChatPresentation.activityTitle(items: items, running: false).contains("success"))
        XCTAssertEqual(ChatPresentation.activityTitle(items: items + items, running: false), "Used 2 tools")
    }

    /// Offline render fixture: no AgentBridge, onAppear startup, model calls,
    /// speech, or live state. Optional images are saved only outside the checkout.
    @MainActor
    func testNativeChatComponentsRenderAtNarrowAndWideWidths() throws {
        for width in [CGFloat(390), CGFloat(980)] {
            let content = VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        TranscriptRow(message: ChatMessage(author: .user,
                            text: "Inspect the chat, then ask a connected worker to review the findings."))
                        TranscriptRow(message: ChatMessage(author: .assistant,
                            text: "I’ll inspect the visible result and check the underlying code. Jaeger owns this task; connected workers contribute their findings."))
                        ToolCommandGroupView(items: [
                            ToolCallItem(name: "read_file", detail: "ChatView.swift"),
                            ToolCallItem(name: "terminal", detail: "Focused checks", ok: false)
                        ], isStreaming: false)
                        TranscriptRow(message: ChatMessage(author: .assistant,
                            text: "The model selector preserves the full model name.\n\nThe composer keeps your draft available while a task is running. Tool details are expandable, and failures stay visible.",
                            displayName: "Jaeger"))
                    }
                    .frame(maxWidth: ChatPresentation.contentWidth)
                    .padding(24)
                }
                ChatComposerView(text: .constant("Follow up with the reviewer.\nKeep the current task context."),
                    attachments: .constant([]), agentName: "Jaeger",
                    modelName: "Configured model with a long variant name", mode: .agent,
                    connected: true, canSend: true, isSending: true,
                    isRecording: false, isTranscribing: false, level: 0,
                    queuedMessages: ["Check the second message as well."],
                    onSend: {}, onStop: {}, onAttach: {}, onSelectModel: {},
                    onSelectMode: { _ in }, onDictate: {}, onVoice: {})
            }
            .frame(width: width, height: 800)
            .background(ChatPresentation.canvas)
            .environment(\.colorScheme, .dark)

            let host = NSHostingView(rootView: content)
            host.frame = NSRect(x: 0, y: 0, width: width, height: 800)
            host.layoutSubtreeIfNeeded()
            let bitmap = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
            host.cacheDisplay(in: host.bounds, to: bitmap)
            XCTAssertGreaterThan(bitmap.pixelsWide, 0)
            XCTAssertGreaterThan(bitmap.pixelsHigh, 0)
            if let directory = ProcessInfo.processInfo.environment["JAEGER_CHAT_SNAPSHOT_DIR"] {
                let destination = URL(fileURLWithPath: directory, isDirectory: true)
                try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
                let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                try png.write(to: destination.appendingPathComponent("chat-\(Int(width)).png"))
            }
        }
    }
}
