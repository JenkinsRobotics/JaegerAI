import Foundation

/// Session-level compaction anchor metadata carried by `SessionDetail`
/// (`compression_anchor_*` fields in the `/api/session` payload).
struct CompressionAnchorMetadata: Equatable {
    let visibleIdx: Int?
    let messageKey: CompressionAnchorMessageKey?
    let summary: String?

    init?(from session: SessionDetail?) {
        guard let session else { return nil }
        guard session.compressionAnchorVisibleIdx != nil
            || session.compressionAnchorMessageKey != nil
            || session.compressionAnchorSummary != nil
        else {
            return nil
        }

        visibleIdx = session.compressionAnchorVisibleIdx
        messageKey = session.compressionAnchorMessageKey
        summary = session.compressionAnchorSummary
    }

    init(visibleIdx: Int?, messageKey: CompressionAnchorMessageKey?, summary: String?) {
        self.visibleIdx = visibleIdx
        self.messageKey = messageKey
        self.summary = summary
    }
}

/// Resolves the synthesized "Context compaction · Reference only" card from
/// session compaction metadata, mirroring the web UI's settled-reference logic
/// (`_latestCompressionReferenceMessage`, `_shouldShowSettledCompressionReference`,
/// `_compressionMessageAnchorKey`, and `_compressionAnchorIndex` in `ui.js`).
enum CompressionAnchorResolver {
    struct Resolution: Equatable {
        enum Placement: Equatable {
            /// Render the card directly after the loaded message at this raw
            /// index into the loaded messages array.
            case afterLoadedMessageIndex(Int)
            /// Render the card above the loaded transcript: the anchor predates
            /// the currently loaded tail window, or only a summary resolved.
            case top
        }

        let referenceText: String
        let placement: Placement
    }

    static func resolve(
        messages: [ChatMessage],
        messagesOffset: Int,
        metadata: CompressionAnchorMetadata?
    ) -> Resolution? {
        guard let metadata else { return nil }

        let summary = (metadata.summary ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard metadata.visibleIdx != nil || metadata.messageKey != nil || !summary.isEmpty else {
            return nil
        }

        let referenceText = referenceText(in: messages, summary: summary)
        guard shouldShowReference(referenceText) else { return nil }

        let candidateIndices = anchorCandidateIndices(in: messages)

        if let anchorKey = metadata.messageKey,
           let matchedIndex = latestMatch(of: anchorKey, in: messages, candidateIndices: candidateIndices) {
            return Resolution(referenceText: referenceText, placement: .afterLoadedMessageIndex(matchedIndex))
        }

        if let visibleIdx = metadata.visibleIdx, !candidateIndices.isEmpty {
            // The server index counts visible messages from the absolute start
            // of the session, while the app holds a `msg_limit` tail window.
            // Shifting by the raw `messagesOffset` over-corrects (raw count ≥
            // visible count), which only biases unresolved anchors toward the
            // top clamp — the degraded behavior the issue asks for when the
            // anchor predates the loaded tail. The key match above remains the
            // precise path.
            let localIdx = visibleIdx - max(0, messagesOffset)
            guard localIdx >= 0 else {
                return Resolution(referenceText: referenceText, placement: .top)
            }

            let clampedIdx = min(localIdx, candidateIndices.count - 1)
            return Resolution(
                referenceText: referenceText,
                placement: .afterLoadedMessageIndex(candidateIndices[clampedIdx])
            )
        }

        return Resolution(referenceText: referenceText, placement: .top)
    }

    // MARK: - Reference text

    /// Mirrors `_latestCompressionReferenceMessage`: prefer the latest literal
    /// compaction-marker message (matching summary containment when a summary
    /// exists), falling back to the summary itself.
    private static func referenceText(in messages: [ChatMessage], summary: String) -> String {
        let normalizedSummary = normalizedWhitespace(summary)

        for message in messages.reversed() {
            guard ChatMarkerMessageClassifier.classify(message) == .contextCompaction else { continue }

            let content = message.content ?? ""
            if normalizedSummary.isEmpty || normalizedWhitespace(content).contains(normalizedSummary) {
                return content
            }
        }

        return summary
    }

    /// Mirrors `_shouldShowSettledCompressionReference`: non-empty reference
    /// text that is not itself a literal compaction marker.
    private static func shouldShowReference(_ referenceText: String) -> Bool {
        let trimmed = referenceText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }

        return !ChatMarkerMessageClassifier.isContextCompactionText(trimmed)
    }

    // MARK: - Anchor matching

    private struct CandidateKey {
        let role: String
        let ts: Double?
        let text: String
        let attachments: Int
    }

    /// Loaded indices of messages eligible to anchor the card. Approximates the
    /// server's `visible_messages_for_anchor` list (which both the anchor key
    /// and `compression_anchor_visible_idx` are computed against): non-tool,
    /// non-marker messages that carry text, attachments, or assistant activity.
    private static func anchorCandidateIndices(in messages: [ChatMessage]) -> [Int] {
        messages.indices.filter { index in
            let message = messages[index]
            guard let role = message.role, !role.isEmpty, role != "tool" else { return false }
            guard ChatMarkerMessageClassifier.classify(message) == nil else { return false }

            let hasText = message.content?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
            let hasAttachments = message.attachments?.isEmpty == false
            if hasText || hasAttachments {
                return true
            }

            guard role == "assistant" else { return false }
            return message.toolCalls?.isEmpty == false
                || message.reasoning?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
        }
    }

    /// Mirrors `_compressionMessageAnchorKey`.
    private static func candidateKey(for message: ChatMessage) -> CandidateKey? {
        guard let role = message.role, !role.isEmpty, role != "tool" else { return nil }

        let normalizedText = normalizedAnchorText(message.content ?? "")
        let attachments = message.attachments?.count ?? 0
        let ts = message.timestamp
        if normalizedText.isEmpty, attachments == 0, ts == nil {
            return nil
        }

        return CandidateKey(role: role, ts: ts, text: normalizedText, attachments: attachments)
    }

    /// Mirrors `_compressionAnchorIndex`'s reverse scan: role and normalized
    /// text must match exactly, attachment counts must match, and timestamps
    /// are compared only when both sides have one.
    private static func latestMatch(
        of anchorKey: CompressionAnchorMessageKey,
        in messages: [ChatMessage],
        candidateIndices: [Int]
    ) -> Int? {
        for index in candidateIndices.reversed() {
            guard let candidate = candidateKey(for: messages[index]) else { continue }

            guard candidate.role == (anchorKey.role ?? "") else { continue }
            if let anchorTs = anchorKey.ts, let candidateTs = candidate.ts, anchorTs != candidateTs {
                continue
            }
            guard candidate.text == (anchorKey.text ?? "") else { continue }
            guard candidate.attachments == (anchorKey.attachments ?? 0) else { continue }

            return index
        }

        return nil
    }

    /// First 160 characters of whitespace-normalized text, matching the server's
    /// `" ".join(text.split()).strip()[:160]` key construction.
    static func normalizedAnchorText(_ text: String) -> String {
        String(normalizedWhitespace(text).prefix(160))
    }

    private static func normalizedWhitespace(_ text: String) -> String {
        text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
