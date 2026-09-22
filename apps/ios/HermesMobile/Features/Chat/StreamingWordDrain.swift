import Foundation

/// Pure helpers for pacing streamed assistant text at a word cadence (issue #212).
///
/// The streaming flush pipeline reveals buffered tokens word-by-word instead of
/// dumping whole burst batches into the transcript at once. A drainable "unit" is
/// one word plus its trailing whitespace; leading whitespace attaches to the first
/// unit, and a trailing in-progress word counts as a unit so buffers without
/// whitespace still drain. Splitting walks `Character`s (grapheme clusters), so
/// emoji/ZWJ sequences and combining marks are never split, and `head + tail`
/// always reproduces the input exactly — pacing can never alter final content.
enum StreamingWordDrain {
    /// Number of drainable word units in `text`.
    static func unitCount(in text: String) -> Int {
        var count = 0
        var hasSeenNonWhitespace = false
        var previousWasWhitespace = false
        for character in text {
            let isWhitespace = character.isWhitespace
            if count == 0 {
                count = 1
            } else if previousWasWhitespace, !isWhitespace, hasSeenNonWhitespace {
                count += 1
            }
            if !isWhitespace {
                hasSeenNonWhitespace = true
            }
            previousWasWhitespace = isWhitespace
        }
        return count
    }

    /// Splits `text` after its first `unitCount` units; `head + tail == text`.
    /// A non-positive count returns everything in `tail`; a count at or beyond
    /// the backlog returns everything in `head`.
    static func splitAtUnitBoundary(_ text: String, unitCount: Int) -> (head: String, tail: String) {
        guard unitCount > 0, !text.isEmpty else { return ("", text) }

        var unitsSeen = 0
        var hasSeenNonWhitespace = false
        var previousWasWhitespace = false
        var index = text.startIndex
        while index < text.endIndex {
            let character = text[index]
            let isWhitespace = character.isWhitespace
            if unitsSeen == 0 {
                unitsSeen = 1
            } else if previousWasWhitespace, !isWhitespace, hasSeenNonWhitespace {
                unitsSeen += 1
                if unitsSeen > unitCount {
                    return (String(text[..<index]), String(text[index...]))
                }
            }
            if !isWhitespace {
                hasSeenNonWhitespace = true
            }
            previousWasWhitespace = isWhitespace
            index = text.index(after: index)
        }
        return (text, "")
    }

    /// Units to drain on one cadence tick. Normally one word per tick; when the
    /// backlog would take longer than `maxLagNanoseconds` to drain at
    /// `cadenceNanoseconds` per word, the quota scales up proportionally so the
    /// display catches up to the live stream within the lag bound.
    static func drainQuota(
        backlogUnitCount: Int,
        cadenceNanoseconds: UInt64,
        maxLagNanoseconds: UInt64
    ) -> Int {
        guard backlogUnitCount > 1 else { return 1 }
        guard cadenceNanoseconds > 0, maxLagNanoseconds > 0 else { return backlogUnitCount }

        let drainNanoseconds = Double(backlogUnitCount) * Double(cadenceNanoseconds)
        let quota = Int((drainNanoseconds / Double(maxLagNanoseconds)).rounded(.up))
        return min(backlogUnitCount, max(1, quota))
    }
}
