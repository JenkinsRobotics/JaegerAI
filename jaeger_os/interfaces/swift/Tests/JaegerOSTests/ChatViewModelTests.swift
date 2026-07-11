//
//  ChatViewModelTests.swift
//  JaegerOSTests
//
//  ChatViewModel's networked paths (newChat/loadSession/fetchSessions) go
//  through a live AgentBridge/BridgeProcess child process, which isn't
//  mockable without a protocol seam the codebase doesn't have yet (see
//  SettingsStore for the same shape — no tests either). These tests pin
//  the PURE pieces instead: the turn-list -> transcript mapping
//  (``rebuildMessages``, runway item 4's History → load_session path) and
//  the session-key minting convention.
//

import XCTest
@testable import JaegerOS

final class ChatViewModelTests: XCTestCase {

    // MARK: rebuildMessages — load_session's turn list -> transcript

    func testRebuildMessagesMapsRolesInOrder() {
        let turns = [
            SessionTurn(role: "user", text: "hi", ts: 1_700_000_000),
            SessionTurn(role: "assistant", text: "hello", ts: 1_700_000_001),
            SessionTurn(role: "user", text: "again", ts: 1_700_000_002),
        ]
        let messages = ChatViewModel.rebuildMessages(from: turns)
        XCTAssertEqual(messages.map(\.author), [.user, .assistant, .user])
        XCTAssertEqual(messages.map(\.text), ["hi", "hello", "again"])
        // Timestamps carry through (off the durable store's ``ts``).
        XCTAssertEqual(messages[0].timestamp,
                       Date(timeIntervalSince1970: 1_700_000_000))
    }

    func testRebuildMessagesOnEmptyHistoryIsEmpty() {
        XCTAssertEqual(ChatViewModel.rebuildMessages(from: []), [])
    }

    func testRebuildMessagesTreatsAnyNonUserRoleAsAssistant() {
        // The bridge only ever records "user"/"assistant" (see
        // core/sessions.py SessionStore.record's call sites), but the
        // mapping is defensive rather than force-unwrapping an enum.
        let turns = [SessionTurn(role: "system", text: "x", ts: 0)]
        XCTAssertEqual(ChatViewModel.rebuildMessages(from: turns).first?.author,
                       .assistant)
    }

    // MARK: session-key minting

    func testMintSessionKeyIsShortAndLowercaseHex() {
        let key = ChatViewModel.mintSessionKey()
        XCTAssertEqual(key.count, 8)
        XCTAssertTrue(key.allSatisfy { $0.isHexDigit && !$0.isUppercase })
    }

    func testMintSessionKeyIsUniquePerCall() {
        let a = ChatViewModel.mintSessionKey()
        let b = ChatViewModel.mintSessionKey()
        XCTAssertNotEqual(a, b)
    }

    // MARK: SessionSummary.displayTitle — title > preview > placeholder

    func testDisplayTitlePrefersTitleOverPreview() {
        let row = SessionSummary(id: "s1", title: "My Task", preview: "hi",
                                 created_at: 1, last_active: 1, messages: 2)
        XCTAssertEqual(row.displayTitle, "My Task")
    }

    func testDisplayTitleFallsBackToPreviewThenPlaceholder() {
        let withPreview = SessionSummary(id: "s1", title: nil, preview: "first line",
                                         created_at: 1, last_active: 1, messages: 1)
        XCTAssertEqual(withPreview.displayTitle, "first line")

        let bare = SessionSummary(id: "s1", title: nil, preview: nil,
                                  created_at: 1, last_active: 1, messages: 0)
        XCTAssertEqual(bare.displayTitle, "(untitled)")

        let blank = SessionSummary(id: "s1", title: "   ", preview: "  ",
                                   created_at: 1, last_active: 1, messages: 0)
        XCTAssertEqual(blank.displayTitle, "(untitled)")
    }

    // MARK: wire decoding — the bridge's snake_case JSON shape

    func testSessionSummaryDecodesBridgeJSON() throws {
        let json = """
        [{"id":"a1b2c3d4","title":null,"preview":"hello there",
          "created_at":1700000000.0,"last_active":1700000005.0,"messages":2}]
        """.data(using: .utf8)!
        let rows = try JSONDecoder().decode([SessionSummary].self, from: json)
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].id, "a1b2c3d4")
        XCTAssertEqual(rows[0].preview, "hello there")
        XCTAssertEqual(rows[0].messages, 2)
    }

    func testSessionTurnDecodesBridgeJSON() throws {
        let json = """
        [{"role":"user","text":"hi","ts":1700000000.0}]
        """.data(using: .utf8)!
        let turns = try JSONDecoder().decode([SessionTurn].self, from: json)
        XCTAssertEqual(turns, [SessionTurn(role: "user", text: "hi", ts: 1_700_000_000)])
    }
}
