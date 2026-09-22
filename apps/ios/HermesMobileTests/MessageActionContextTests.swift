import XCTest
import AVFoundation
import ImageIO
import SwiftData
import UIKit
import UniformTypeIdentifiers
@testable import HermesMobile

final class MessageActionContextTests: XCTestCase {
    func testUserMessageContextPreservesFullHistoryIndexWithOffset() throws {
        let message = ChatMessage(
            role: "user",
            content: "Please revise this",
            timestamp: 1_770_000_000,
            messageId: "message-28"
        )

        let context = try XCTUnwrap(
            MessageActionContext(message: message, visibleIndex: 3, messagesOffset: 25)
        )

        XCTAssertEqual(context.role, .user)
        XCTAssertEqual(context.visibleIndex, 3)
        XCTAssertEqual(context.fullHistoryIndex, 28)
        XCTAssertEqual(context.keepCountThroughMessage, 29)
        XCTAssertEqual(context.messageID, "message-28")
        XCTAssertEqual(context.copyText, "Please revise this")
        XCTAssertNil(context.listenText)
    }

    func testAssistantMessageContextCopiesRawMarkdownText() throws {
        let message = ChatMessage(
            role: "assistant",
            content: "## Result\n\nUse `xcodebuild test`.",
            timestamp: 1_770_000_001,
            messageId: "message-29"
        )

        let context = try XCTUnwrap(
            MessageActionContext(message: message, visibleIndex: 4, messagesOffset: 25)
        )

        XCTAssertEqual(context.role, .assistant)
        XCTAssertEqual(context.fullHistoryIndex, 29)
        XCTAssertEqual(context.keepCountThroughMessage, 30)
        XCTAssertEqual(context.messageID, "message-29")
        XCTAssertEqual(context.copyText, "## Result\n\nUse `xcodebuild test`.")
        XCTAssertEqual(context.listenText, "Result\n\nUse xcodebuild test.")
    }

    func testAssistantListenTextNormalizesCommonMarkdown() throws {
        let message = ChatMessage(
            role: "assistant",
            content: """
            # Summary

            - Open [Hermes](https://example.test)
            > Then run `xcodebuild test`.
            """,
            timestamp: 1_770_000_002,
            messageId: "message-30"
        )

        let context = try XCTUnwrap(
            MessageActionContext(message: message, visibleIndex: 5, messagesOffset: 25)
        )

        XCTAssertEqual(
            context.listenText,
            "Summary\n\nOpen Hermes\nThen run xcodebuild test."
        )
    }

    func testMessageContextIgnoresUnsupportedOrEmptyMessages() {
        let systemMessage = ChatMessage(
            role: "system",
            content: "Hidden instruction",
            timestamp: nil,
            messageId: "system-1"
        )
        let emptyUserMessage = ChatMessage(
            role: "user",
            content: "",
            timestamp: nil,
            messageId: "user-empty"
        )

        XCTAssertNil(MessageActionContext(message: systemMessage, visibleIndex: 0, messagesOffset: 0))
        XCTAssertNil(MessageActionContext(message: emptyUserMessage, visibleIndex: 0, messagesOffset: 0))
        XCTAssertNil(MessageActionContext(message: emptyUserMessage, visibleIndex: -1, messagesOffset: 0))
    }

    func testMessageContextIgnoresLocalAssistantMessages() {
        let message = ChatMessage(
            role: "local_assistant",
            content: "Available mobile commands",
            timestamp: nil,
            messageId: "local-help"
        )

        XCTAssertNil(MessageActionContext(message: message, visibleIndex: 0, messagesOffset: 0))
    }

    func testEditTruncationIndexIsFullHistoryIndex() throws {
        // For edit: we truncate to fullHistoryIndex (removing the selected message),
        // not keepCountThroughMessage (which would keep the selected message).
        let message = ChatMessage(
            role: "user",
            content: "Original question",
            timestamp: 1_770_000_010,
            messageId: "user-5"
        )

        let context = try XCTUnwrap(
            MessageActionContext(message: message, visibleIndex: 3, messagesOffset: 10)
        )

        // fullHistoryIndex = offset + visibleIndex = 10 + 3 = 13
        XCTAssertEqual(context.fullHistoryIndex, 13)
        // keepCountThroughMessage = fullHistoryIndex + 1 = 14 (used for fork, not edit)
        XCTAssertEqual(context.keepCountThroughMessage, 14)
        // For edit, we truncate to fullHistoryIndex to remove the user message itself
        XCTAssertEqual(context.role, .user)
    }

    func testRegenerateUsesNearestLoadedUserMessageText() {
        let messages = [
            ChatMessage(role: "user", content: "First question", timestamp: 1, messageId: "u1"),
            ChatMessage(role: "assistant", content: "First answer", timestamp: 2, messageId: "a1"),
            ChatMessage(role: "user", content: "Second question", timestamp: 3, messageId: "u2"),
            ChatMessage(role: "assistant", content: "Second answer", timestamp: 4, messageId: "a2")
        ]

        let text = ChatViewModel.precedingUserMessageText(in: messages, beforeVisibleIndex: 3)

        XCTAssertEqual(text, "Second question")
    }

    func testRegenerateReturnsNilWhenPrecedingUserIsNotLoaded() {
        let messages = [
            ChatMessage(role: "assistant", content: "Answer in truncated window", timestamp: 1, messageId: "a1"),
            ChatMessage(role: "assistant", content: "Another answer", timestamp: 2, messageId: "a2")
        ]

        let text = ChatViewModel.precedingUserMessageText(in: messages, beforeVisibleIndex: 1)

        XCTAssertNil(text)
    }
}
