//
//  TranscriptFeedTests.swift
//  JaegerAITests
//
//  The chat feed has to read in the order the turn actually happened:
//  deliberation and tool runs interleaved chronologically, the operator's
//  answer last, each section collapsible on its own. ``TranscriptFeed`` is
//  pure list surgery, so the ordering is pinned here directly rather than
//  through a live bridge turn.
//

import XCTest
@testable import JaegerAI

final class TranscriptFeedTests: XCTestCase {

    /// A turn mid-flight: the user's prompt and the answer row that stays
    /// pinned to the bottom while activity accumulates above it.
    private func startedTurn() -> (messages: [ChatMessage], answerID: UUID) {
        let answer = ChatMessage(author: .assistant, text: "", isStreaming: true)
        return ([ChatMessage(author: .user, text: "do the thing"), answer], answer.id)
    }

    private func shape(_ messages: [ChatMessage]) -> [ChatMessage.Author] {
        messages.map(\.author)
    }

    private func tool(_ name: String) -> ToolCallItem {
        ToolCallItem(name: name, isStreaming: true)
    }

    // MARK: - Chronology

    func testThoughtAfterToolOpensItsOwnSectionBelowTheTool() {
        // The headline requirement: "if it thought after a tool use it should
        // be displayed in that way". The old code merged this second thought
        // back into the first, rendering think→think→run.
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("first, plan it", to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("read_file"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.4, in: &messages, answerID: answerID)
        TranscriptFeed.appendThought("now I know the contents", to: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .thought, .toolGroup, .thought, .assistant])
        XCTAssertEqual(messages[1].thoughtText, "first, plan it")
        XCTAssertEqual(messages[3].thoughtText, "now I know the contents")
    }

    func testToolAfterThoughtOpensANewGroup() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.beginTool(tool("read_file"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.1, in: &messages, answerID: answerID)
        TranscriptFeed.appendThought("that was not enough", to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("grep"), in: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .toolGroup, .thought, .toolGroup, .assistant])
        XCTAssertEqual(messages[1].toolItems.map(\.name), ["read_file"])
        XCTAssertEqual(messages[3].toolItems.map(\.name), ["grep"])
    }

    func testFullInterleavingSurvivesInOrder() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("plan", to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("a"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.1, in: &messages, answerID: answerID)
        TranscriptFeed.appendThought("reconsider", to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("b"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.1, in: &messages, answerID: answerID)
        TranscriptFeed.appendThought("conclude", to: &messages, answerID: answerID)
        TranscriptFeed.appendAnswerDelta("done.", to: &messages, answerID: answerID)

        XCTAssertEqual(
            shape(messages),
            [.user, .thought, .toolGroup, .thought, .toolGroup, .thought, .assistant])
        XCTAssertEqual(messages.last?.text, "done.")
    }

    /// Replays a real turn captured off the bridge on 2026-09-14
    /// ("list the files in the workspace, then tell me how many"), whose
    /// frames arrived in this order:
    ///
    ///     reasoning  "user wants me to list files…"
    ///     tool       list_skill_dir            (start)
    ///     tool       list_skill_dir            (complete)
    ///     reasoning  "the workspace has 4 entries…"
    ///     delta      the answer
    ///
    /// The agent genuinely deliberates AFTER acting, so this is the shape the
    /// feed has to get right. The previous code rendered it answer-first with
    /// both thoughts fused above the tool run.
    func testRealBridgeTurnRendersThoughtToolThoughtAnswer() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought(
            "The user wants me to list files in the current workspace directory.",
            to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("list_skill_dir"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.3, in: &messages, answerID: answerID)
        TranscriptFeed.appendThought(
            "The workspace has 4 entries: 2 directories and 2 files.",
            to: &messages, answerID: answerID)
        TranscriptFeed.appendAnswerDelta("The workspace has 4 entries", to: &messages, answerID: answerID)
        TranscriptFeed.closeStreaming(in: &messages)

        XCTAssertEqual(shape(messages), [.user, .thought, .toolGroup, .thought, .assistant])
        XCTAssertTrue(messages[1].thoughtText.hasPrefix("The user wants me to list"))
        XCTAssertEqual(messages[2].toolItems.map(\.name), ["list_skill_dir"])
        XCTAssertTrue(messages[3].thoughtText.hasPrefix("The workspace has 4 entries"))
        XCTAssertEqual(messages.last?.id, answerID)
        XCTAssertTrue(messages.allSatisfy { !$0.isStreaming })
    }

    // MARK: - Grouping

    func testConsecutiveThoughtsShareOneSection() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("one", to: &messages, answerID: answerID)
        TranscriptFeed.appendThought("two", to: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .thought, .assistant])
        XCTAssertEqual(messages[1].thoughtText, "one\n\ntwo")
    }

    func testRepeatedDeliberationIsNotDuplicated() {
        // Some adapters re-send accumulated reasoning rather than a delta.
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("same text", to: &messages, answerID: answerID)
        TranscriptFeed.appendThought("same text", to: &messages, answerID: answerID)

        XCTAssertEqual(messages[1].thoughtText, "same text")
    }

    func testConsecutiveToolsShareOneGroup() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.beginTool(tool("a"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.1, in: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("b"), in: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .toolGroup, .assistant])
        XCTAssertEqual(messages[1].toolItems.map(\.name), ["a", "b"])
    }

    // MARK: - The answer stays last

    func testAnswerRemainsTheFinalRowThroughoutTheTurn() {
        var (messages, answerID) = startedTurn()
        for step in 0..<5 {
            TranscriptFeed.appendThought("step \(step)", to: &messages, answerID: answerID)
            TranscriptFeed.beginTool(tool("t\(step)"), in: &messages, answerID: answerID)
            TranscriptFeed.completeTool(ok: true, elapsed: 0.1, in: &messages, answerID: answerID)
            XCTAssertEqual(messages.last?.id, answerID,
                           "answer drifted off the bottom after step \(step)")
        }
    }

    func testAnswerDeltasLandOnThisTurnsAnswerNotAnOlderOne() {
        // A queued follow-up leaves the previous turn's answer in the list;
        // addressing "the last assistant row" by position would be ambiguous.
        var (messages, answerID) = startedTurn()
        messages[1].text = "stale answer"
        let second = ChatMessage(author: .assistant, text: "", isStreaming: true)
        messages.append(ChatMessage(author: .user, text: "again"))
        messages.append(second)

        TranscriptFeed.appendAnswerDelta("fresh", to: &messages, answerID: second.id)

        XCTAssertEqual(messages.first(where: { $0.id == answerID })?.text, "stale answer")
        XCTAssertEqual(messages.first(where: { $0.id == second.id })?.text, "fresh")
    }

    // MARK: - Tool completion

    func testToolCompletesInItsOwnGroupAfterANewSectionOpened() {
        // A slow tool can settle after the agent has already started
        // thinking again; the result belongs to the group it started in.
        var (messages, answerID) = startedTurn()
        TranscriptFeed.beginTool(tool("slow"), in: &messages, answerID: answerID)
        TranscriptFeed.appendThought("meanwhile", to: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: false, elapsed: 2.5, in: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .toolGroup, .thought, .assistant])
        let item = messages[1].toolItems[0]
        XCTAssertFalse(item.isStreaming)
        XCTAssertFalse(item.ok)
        XCTAssertEqual(item.elapsed_s, 2.5, accuracy: 0.001)
        XCTAssertFalse(messages[1].isStreaming, "settled group still shows as live")
    }

    func testCompletingWithNoRunningToolIsANoOp() {
        var (messages, answerID) = startedTurn()
        let before = messages
        TranscriptFeed.completeTool(ok: true, elapsed: 1, in: &messages, answerID: answerID)
        XCTAssertEqual(shape(messages), shape(before))
    }

    // MARK: - Turn boundaries

    func testActivityNeverMergesIntoThePreviousTurn() {
        var (messages, _) = startedTurn()
        TranscriptFeed.appendThought("old turn", to: &messages, answerID: nil)
        TranscriptFeed.closeStreaming(in: &messages)

        // A new turn starts; its first thought must not join the old section.
        let answer = ChatMessage(author: .assistant, text: "", isStreaming: true)
        messages.append(ChatMessage(author: .user, text: "next"))
        messages.append(answer)
        TranscriptFeed.appendThought("new turn", to: &messages, answerID: answer.id)

        XCTAssertEqual(
            shape(messages),
            [.user, .assistant, .thought, .user, .thought, .assistant])
        XCTAssertEqual(messages[4].thoughtText, "new turn")
    }

    func testActivityStillWorksWhileAFollowUpIsQueuedBelowTheAnswer() {
        // Typing while the agent works queues a user row BELOW the running
        // answer. The turn must keep grouping and settling normally.
        var (messages, answerID) = startedTurn()
        TranscriptFeed.beginTool(tool("slow"), in: &messages, answerID: answerID)
        messages.append(ChatMessage(author: .user, text: "queued follow-up"))

        TranscriptFeed.beginTool(tool("next"), in: &messages, answerID: answerID)
        TranscriptFeed.completeTool(ok: true, elapsed: 0.2, in: &messages, answerID: answerID)

        XCTAssertEqual(shape(messages), [.user, .toolGroup, .assistant, .user])
        XCTAssertEqual(messages[1].toolItems.map(\.name), ["slow", "next"],
                       "queued follow-up split a contiguous tool group")
        XCTAssertFalse(messages[1].toolItems[0].isStreaming,
                       "tool result was dropped while a follow-up sat queued")
    }

    // MARK: - Streaming state

    func testCloseThoughtSettlesOnlyTheOpenSection() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("thinking", to: &messages, answerID: answerID)
        XCTAssertTrue(messages[1].isStreaming)

        TranscriptFeed.closeThought(in: &messages, answerID: answerID)
        XCTAssertFalse(messages[1].isStreaming)
    }

    func testCloseStreamingSettlesEveryRow() {
        var (messages, answerID) = startedTurn()
        TranscriptFeed.appendThought("t", to: &messages, answerID: answerID)
        TranscriptFeed.beginTool(tool("x"), in: &messages, answerID: answerID)

        TranscriptFeed.closeStreaming(in: &messages)
        XCTAssertTrue(messages.allSatisfy { !$0.isStreaming })
    }

    /// With no answer row (activity arriving outside a turn) activity still
    /// appends in order rather than being dropped.
    func testActivityWithoutAnAnswerRowAppendsAtTheEnd() {
        var messages: [ChatMessage] = [ChatMessage(author: .user, text: "hi")]
        TranscriptFeed.appendThought("a", to: &messages, answerID: nil)
        TranscriptFeed.beginTool(tool("x"), in: &messages, answerID: nil)
        TranscriptFeed.appendThought("b", to: &messages, answerID: nil)

        XCTAssertEqual(shape(messages), [.user, .thought, .toolGroup, .thought])
    }
}
