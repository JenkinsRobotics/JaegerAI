//
//  TranscriptFeed.swift
//  JaegerAI / ChatWindow
//
//  Placement rules for the live agent feed.
//
//  The feed reads top-to-bottom as the turn actually happened: every
//  deliberation and every tool run appears in the order the agent produced
//  it, and the answer the operator asked for sits at the bottom.
//
//  Two invariants carry that, and both are load-bearing:
//
//  1. ACTIVITY IS CHRONOLOGICAL. An event may only merge into the section
//     immediately above the answer, and only when that section is the same
//     kind. A thought after a tool run therefore opens a NEW thought
//     section below that tool run instead of being folded back into the
//     thought that preceded it. The old code searched for the last row of a
//     matching kind anywhere in the turn, which silently reordered the
//     transcript: think → run → think rendered as think(×2) → run, telling
//     the operator the agent reasoned before evidence it had not yet seen.
//
//  2. THE ANSWER IS LAST. The assistant row is created when the turn starts
//     and every activity row is inserted ABOVE it, so the reply never floats
//     up above the work that produced it. Appending activity blindly — what
//     the old code did — pushed thoughts and tool runs BELOW an answer bubble
//     that was appended first.
//
//  Rules live here, apart from ``ChatViewModel``, because they are pure
//  list surgery: they need no bridge, no MainActor and no live turn to
//  exercise, so ``TranscriptFeedTests`` can pin the ordering directly.
//

import Foundation

enum TranscriptFeed {

    // MARK: - Anchors

    /// Where this turn's activity rows belong: immediately above the answer,
    /// or at the end when the turn has no answer row (yet, or ever).
    static func activityInsertionIndex(
        in messages: [ChatMessage], answerID: UUID?
    ) -> Int {
        guard let answerID,
              let index = messages.firstIndex(where: { $0.id == answerID })
        else { return messages.count }
        return index
    }

    /// First index belonging to the running turn: just past the user row that
    /// opened it. Merging must never reach back into a previous turn.
    ///
    /// Scoped to rows ABOVE the answer rather than to the last user row in the
    /// list, because a message typed while a turn is in flight is queued as a
    /// user row appended BELOW that answer. Keying off the global last user row
    /// would put the turn's start after its own answer, collapsing the search
    /// window to nothing — tool results would stop settling (spinners stuck
    /// until the turn ended) the moment the operator got ahead of the agent.
    private static func turnStart(in messages: [ChatMessage], below upper: Int) -> Int {
        guard let user = messages[..<upper].lastIndex(where: { $0.author == .user })
        else { return 0 }
        return user + 1
    }

    /// The section a new event may merge into: the row directly above the
    /// answer, when it is of the requested kind and part of this turn.
    /// ``nil`` means "open a new section", which is what keeps the feed in
    /// chronological order.
    static func openSectionIndex(
        in messages: [ChatMessage], answerID: UUID?,
        author: ChatMessage.Author
    ) -> Int? {
        let upper = activityInsertionIndex(in: messages, answerID: answerID)
        let index = upper - 1
        guard index >= 0, index >= turnStart(in: messages, below: upper) else { return nil }
        guard messages[index].author == author else { return nil }
        return index
    }

    // MARK: - Deliberation

    /// Add model deliberation, continuing the open thought section or
    /// starting a new one below whatever ran since.
    static func appendThought(
        _ text: String, to messages: inout [ChatMessage], answerID: UUID?
    ) {
        if let index = openSectionIndex(in: messages, answerID: answerID, author: .thought) {
            guard !text.isEmpty else { return }
            // The bridge re-sends accumulated deliberation on some adapters;
            // appending it verbatim would stutter the same paragraph twice.
            guard !messages[index].thoughtText.contains(text) else { return }
            messages[index].thoughtText +=
                (messages[index].thoughtText.isEmpty ? "" : "\n\n") + text
            return
        }
        messages.insert(
            ChatMessage(author: .thought, isStreaming: true, thoughtText: text),
            at: activityInsertionIndex(in: messages, answerID: answerID))
    }

    /// Close the open thought section so it stops showing a live indicator.
    static func closeThought(in messages: inout [ChatMessage], answerID: UUID?) {
        guard let index = openSectionIndex(
            in: messages, answerID: answerID, author: .thought) else { return }
        messages[index].isStreaming = false
    }

    // MARK: - Tool runs

    /// Start a tool run, grouping it with the tool runs it directly follows.
    /// A thought (or anything else) between two runs splits the group, which
    /// is what makes "thought AFTER a tool use" readable as such.
    static func beginTool(
        _ item: ToolCallItem, in messages: inout [ChatMessage], answerID: UUID?
    ) {
        if let index = openSectionIndex(in: messages, answerID: answerID, author: .toolGroup) {
            messages[index].toolItems.append(item)
            messages[index].isStreaming = true
            return
        }
        messages.insert(
            ChatMessage(author: .toolGroup, isStreaming: true, toolItems: [item]),
            at: activityInsertionIndex(in: messages, answerID: answerID))
    }

    /// Settle the oldest still-running tool item.
    ///
    /// Searched backwards rather than taken from the open section: a run that
    /// finishes after the agent has already started thinking again belongs to
    /// the group it started in, which by then is no longer the bottom section.
    static func completeTool(
        ok: Bool, elapsed: Double, in messages: inout [ChatMessage], answerID: UUID?
    ) {
        let upper = activityInsertionIndex(in: messages, answerID: answerID)
        let lower = turnStart(in: messages, below: upper)
        guard upper > lower else { return }
        for index in stride(from: upper - 1, through: lower, by: -1)
        where messages[index].author == .toolGroup {
            // Oldest first: the bridge reports results in the order the calls
            // were made, so a result belongs to the run that has been open
            // longest. Settling the newest instead (the pre-existing
            // behaviour) only ever matched while exactly one run was open —
            // with two in flight it attributed each result to the wrong call.
            guard let item = messages[index].toolItems
                .firstIndex(where: { $0.isStreaming }) else { continue }
            messages[index].toolItems[item].ok = ok
            messages[index].toolItems[item].elapsed_s = elapsed
            messages[index].toolItems[item].isStreaming = false
            if !messages[index].toolItems.contains(where: { $0.isStreaming }) {
                messages[index].isStreaming = false
            }
            return
        }
    }

    // MARK: - The answer

    /// Stream reply text into THIS turn's answer row.
    ///
    /// Addressed by id, never by "last assistant row": a queued follow-up
    /// turn leaves an earlier answer in the list, and position alone would
    /// let a late delta append onto the wrong one.
    static func appendAnswerDelta(
        _ delta: String, to messages: inout [ChatMessage], answerID: UUID?
    ) {
        guard !delta.isEmpty, let answerID,
              let index = messages.firstIndex(where: { $0.id == answerID })
        else { return }
        messages[index].text += delta
    }

    /// End every live indicator in the turn.
    static func closeStreaming(in messages: inout [ChatMessage]) {
        for index in messages.indices where messages[index].isStreaming {
            messages[index].isStreaming = false
        }
    }
}
