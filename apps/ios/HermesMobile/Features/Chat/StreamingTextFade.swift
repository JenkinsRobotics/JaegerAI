import Foundation

/// Tunables for the streamed-word fade-in effect (issue #213).
///
/// New glyphs are queued behind the previous reveal at `glyphStagger` pace
/// rather than stamped at arrival time, so a multi-word #212 drain batch
/// bleeds in glyph-by-glyph as a moving gradient (the Telegram look) instead
/// of fading as one chunk.
enum StreamingTextFadeDefaults {
    /// The shipped knob values. Release reads these through plain `static let`
    /// constants; Debug routes the same names through `StreamingTextFadeLab`
    /// so the Streaming Lab (issue #234) can tune them at runtime.
    /// The "Balanced" tuning from the issue #234 Streaming Lab session:
    /// crisper fade, a ripple fast enough (~14 words/s) to keep its shape
    /// under fast streams, and lower visible lag behind arrived text.
    enum Baseline {
        static let fadeDuration: TimeInterval = 0.35
        static let glyphStagger: TimeInterval = 0.012
        static let maxStampLead: TimeInterval = 0.45
    }

    static let floorOpacity: Double = 0

    #if DEBUG
    /// Per-glyph 0% → 100% time. Together with `glyphStagger` this sets the
    /// visible width of the leading-edge gradient (≈ fadeDuration /
    /// glyphStagger glyphs — currently ~29, about four words).
    static var fadeDuration: TimeInterval { StreamingTextFadeLab.shared.fadeDuration }

    /// Target spacing between consecutive glyph reveal times.
    static var glyphStagger: TimeInterval { StreamingTextFadeLab.shared.glyphStagger }

    /// Upper bound on how far reveal stamps may run ahead of the fade clock.
    /// When arrivals outpace `glyphStagger` the queue compresses toward the
    /// arrival rate, so the cascade speeds up rather than lagging the stream.
    static var maxStampLead: TimeInterval { StreamingTextFadeLab.shared.maxStampLead }
    #else
    /// Per-glyph 0% → 100% time. Together with `glyphStagger` this sets the
    /// visible width of the leading-edge gradient (≈ fadeDuration /
    /// glyphStagger glyphs — currently ~29, about four words).
    static let fadeDuration: TimeInterval = Baseline.fadeDuration

    /// Target spacing between consecutive glyph reveal times.
    static let glyphStagger: TimeInterval = Baseline.glyphStagger

    /// Upper bound on how far reveal stamps may run ahead of the fade clock.
    /// When arrivals outpace `glyphStagger` the queue compresses toward the
    /// arrival rate, so the cascade speeds up rather than lagging the stream.
    static let maxStampLead: TimeInterval = Baseline.maxStampLead
    #endif

    /// How long the frame-driven fade clock keeps ticking after the last
    /// content change before pausing (covers the queued reveals plus the
    /// final glyph's full fade).
    static var framePauseDelay: TimeInterval { maxStampLead + fadeDuration + 0.1 }

    /// How long after a block's last append its cascade is provably finished
    /// (queue fully revealed), making it safe to absorb into the solid head.
    static var blockAbsorbDelay: TimeInterval { maxStampLead + fadeDuration + 0.25 }
}

#if DEBUG
/// Runtime-tunable fade knobs for the Streaming Lab (issue #234). The text
/// renderer reads the knobs off the main thread on every frame while a lab
/// slider writes them, so access is lock-guarded like the stamp store.
/// Values live in memory only — every launch starts at `Baseline`.
final class StreamingTextFadeLab: @unchecked Sendable {
    static let shared = StreamingTextFadeLab()

    private let lock = NSLock()
    private var storedFadeDuration = StreamingTextFadeDefaults.Baseline.fadeDuration
    private var storedGlyphStagger = StreamingTextFadeDefaults.Baseline.glyphStagger
    private var storedMaxStampLead = StreamingTextFadeDefaults.Baseline.maxStampLead

    var fadeDuration: TimeInterval {
        get { lock.withLock { storedFadeDuration } }
        set { lock.withLock { storedFadeDuration = newValue } }
    }

    var glyphStagger: TimeInterval {
        get { lock.withLock { storedGlyphStagger } }
        set { lock.withLock { storedGlyphStagger = newValue } }
    }

    var maxStampLead: TimeInterval {
        get { lock.withLock { storedMaxStampLead } }
        set { lock.withLock { storedMaxStampLead = newValue } }
    }

    func reset() {
        lock.withLock {
            storedFadeDuration = StreamingTextFadeDefaults.Baseline.fadeDuration
            storedGlyphStagger = StreamingTextFadeDefaults.Baseline.glyphStagger
            storedMaxStampLead = StreamingTextFadeDefaults.Baseline.maxStampLead
        }
    }
}
#endif

enum StreamingTextFadeCurve {
    /// Opacity for a glyph first seen `age` seconds ago. Quadratic ease-out
    /// from `floorOpacity` (0 by default: a word starts invisible in its
    /// final layout position and fades up, per the issue spec's 0% → 100%).
    static func opacity(
        age: TimeInterval,
        fadeDuration: TimeInterval = StreamingTextFadeDefaults.fadeDuration,
        floorOpacity: Double = StreamingTextFadeDefaults.floorOpacity
    ) -> Double {
        guard fadeDuration > 0 else { return 1 }
        guard age < fadeDuration else { return 1 }
        let t = max(0, age) / fadeDuration
        let eased = 1 - (1 - t) * (1 - t)
        return floorOpacity + (1 - floorOpacity) * eased
    }
}

/// The reveal cursor shared by every stamp store of one streaming message.
/// Each block view keeps its own store (character offsets would collide
/// otherwise), but reveal times are reserved from this single monotonic
/// cursor: a new block's first glyph queues `glyphStagger` behind the
/// previous block's last scheduled glyph instead of jumping to "now". Without
/// it, a backlogged line's tail (stamped up to `maxStampLead` in the future)
/// was overtaken by the next line starting at the clock — text appeared out
/// of reading order at fast stream rates.
final class StreamingTextFadeStampChain: @unchecked Sendable {
    private let lock = NSLock()
    private var lastStamp: TimeInterval = -.infinity

    /// Atomically reserves reveal times for `count` queued glyphs. Same
    /// budget rule as before the chain existed: reservations never run more
    /// than `maxStampLead` ahead of `clock`, compressing the pace to fit.
    func reserve(
        count: Int,
        clock: TimeInterval,
        glyphStagger: TimeInterval,
        maxStampLead: TimeInterval
    ) -> (start: TimeInterval, pace: TimeInterval) {
        lock.lock()
        defer { lock.unlock() }

        let start = min(max(clock, lastStamp + glyphStagger), clock + maxStampLead)
        let available = max(0, clock + maxStampLead - start)
        let pace = min(glyphStagger, available / Double(count))
        lastStamp = start + pace * Double(count - 1)
        return (start, pace)
    }

    /// Forgets the cursor. Only for wholesale content replacement — never on
    /// block rollover, where remembering the cursor is what keeps blocks in
    /// reading order.
    func reset() {
        lock.lock()
        defer { lock.unlock() }
        lastStamp = -.infinity
    }
}

/// Records the fade-clock reveal time of each rendered character. New
/// characters are not stamped at arrival: they join a reveal queue paced at
/// `glyphStagger` behind the previous stamp, so a multi-word drain batch
/// cascades in reading order instead of fading as one chunk. A stamp in the
/// future simply means the glyph is still invisible (the curve clamps to the
/// floor until its reveal time comes).
///
/// `TextRenderer.draw` is not bound to an actor, so access is serialized with
/// a lock rather than actor isolation.
final class StreamingTextFadeStampStore<Key: Hashable>: @unchecked Sendable {
    private let lock = NSLock()
    private let chain: StreamingTextFadeStampChain
    private var stamps: [Key: TimeInterval] = [:]
    private var baselineTaken = false

    /// Stores that render blocks of the same message must share one `chain`
    /// so their reveals stay in reading order; the default private chain
    /// keeps single-store behavior unchanged.
    init(chain: StreamingTextFadeStampChain = StreamingTextFadeStampChain()) {
        self.chain = chain
    }

    /// Queues reveal stamps for keys not seen before. `orderedKeys` must be
    /// in reading order (the renderer walks the layout lines top-to-bottom).
    /// Characters visible before the baseline frame completes (text already
    /// on screen when the message mounts) are stamped infinitely old so they
    /// never fade. The queue never runs more than `maxStampLead` ahead of
    /// `clock`: the per-glyph pace compresses to fit the budget.
    func register(
        _ orderedKeys: [Key],
        clock: TimeInterval,
        glyphStagger: TimeInterval = StreamingTextFadeDefaults.glyphStagger,
        maxStampLead: TimeInterval = StreamingTextFadeDefaults.maxStampLead
    ) {
        lock.lock()
        defer { lock.unlock() }

        let newKeys = orderedKeys.filter { stamps[$0] == nil }
        guard !newKeys.isEmpty else { return }

        guard baselineTaken else {
            for key in newKeys {
                stamps[key] = -.infinity
            }
            return
        }

        let (start, pace) = chain.reserve(
            count: newKeys.count,
            clock: clock,
            glyphStagger: glyphStagger,
            maxStampLead: maxStampLead
        )
        var cursor = start
        for key in newKeys {
            stamps[key] = cursor
            cursor += pace
        }
    }

    /// Opacity for `key` at `clock`. Unregistered keys render solid (the
    /// renderer registers every slice before drawing, so this is a fallback).
    func opacity(
        for key: Key?,
        clock: TimeInterval,
        fadeDuration: TimeInterval = StreamingTextFadeDefaults.fadeDuration,
        floorOpacity: Double = StreamingTextFadeDefaults.floorOpacity
    ) -> Double {
        guard let key else { return 1 }
        lock.lock()
        defer { lock.unlock() }

        guard let stamp = stamps[key] else { return 1 }

        return StreamingTextFadeCurve.opacity(
            age: clock - stamp,
            fadeDuration: fadeDuration,
            floorOpacity: floorOpacity
        )
    }

    /// Locks in the baseline after the first complete draw; characters seen
    /// from now on are new text and fade in.
    func finishBaseline() {
        lock.lock()
        defer { lock.unlock() }
        baselineTaken = true
    }

    /// Clears stamps when the rendered tail moves to a new block (or the
    /// content was replaced). Fading stays armed: the next paragraph's first
    /// word should fade rather than be treated as pre-existing text. The
    /// shared chain cursor is deliberately untouched — the new block must
    /// queue behind the previous block's reveals, not restart at the clock.
    func rolloverReset() {
        lock.lock()
        defer { lock.unlock() }
        stamps.removeAll()
        baselineTaken = true
    }
}

/// Splits the active streaming markdown into a solid head plus the trailing
/// fade-window blocks, each rendered with its own fade renderer and stamp
/// store. Keeping completed blocks in the window until their cascade
/// finishes (see `StreamingTextFadeWindow`) is what prevents the
/// end-of-block opacity snap that reads as "text appearing in blocks".
///
/// Boundaries sit after blank lines, headings, thematic breaks, closed code
/// fences, and completed top-level list-item lines (MarkdownUI renders one
/// `Text` per item; CommonMark preserves an ordered list's start number, so
/// a lone "3. …" still renders as 3). Indented (nested) item lines are NOT
/// boundaries: splitting them would re-render the nesting differently and
/// jump the layout. A block's `ordinal` counts the boundaries before it, so
/// it is stable as the stream appends.
///
/// Blocks containing a code fence, or starting a blockquote or table, get
/// `fadeEnabled == false`: their multi-`Text` rendering would collide in one
/// stamp store, so they reveal unfaded (code fade is an explicit non-goal).
enum StreamingTextFadeTailSplitter {
    struct Block: Equatable {
        let ordinal: Int
        let text: String
        let fadeEnabled: Bool
    }

    struct BlockSplit: Equatable {
        let head: String
        let blocks: [Block]
        /// Ordinal of the current (still-growing) block == total boundaries.
        let boundaryCount: Int
    }

    static func split(_ text: String, firstFadeOrdinal: Int) -> BlockSplit {
        var boundaries: [String.Index] = []
        // A completed item line's boundary is provisional: it vanishes if the
        // next line turns out to be indented (a nested child or continuation
        // belongs in the parent's block, or it would render un-nested and
        // jump the layout when absorbed). The view tolerates the resulting
        // backward shift in boundary count.
        var pendingItemBoundary: String.Index?
        var lineStart = text.startIndex
        var isInsideFence = false

        while lineStart < text.endIndex {
            let lineEnd = text[lineStart...].firstIndex(of: "\n") ?? text.endIndex
            let nextLineStart = lineEnd < text.endIndex ? text.index(after: lineEnd) : text.endIndex
            let hasLineBreak = lineEnd < text.endIndex
            let line = text[lineStart..<lineEnd]
            let trimmedLine = String(line).trimmingCharacters(in: .whitespacesAndNewlines)

            if let pending = pendingItemBoundary {
                if line.first != " ", line.first != "\t" {
                    boundaries.append(pending)
                }
                pendingItemBoundary = nil
            }

            if isFenceDelimiter(trimmedLine) {
                isInsideFence.toggle()
                if !isInsideFence {
                    boundaries.append(nextLineStart)
                }
            } else if !isInsideFence, hasLineBreak {
                if trimmedLine.isEmpty || isBlockBoundaryLine(trimmedLine) {
                    boundaries.append(nextLineStart)
                } else if isTopLevelListItemLine(line) {
                    pendingItemBoundary = nextLineStart
                }
            }

            lineStart = nextLineStart
        }

        if let pending = pendingItemBoundary {
            boundaries.append(pending)
        }

        // firstFadeOrdinal == boundaryCount + 1 (e.g. Int.max for Reduce
        // Motion) puts everything, including the current block, in the head.
        let firstKept = max(0, min(firstFadeOrdinal, boundaries.count + 1))
        let headEnd: String.Index
        if firstKept == 0 {
            headEnd = text.startIndex
        } else if firstKept <= boundaries.count {
            headEnd = boundaries[firstKept - 1]
        } else {
            headEnd = text.endIndex
        }

        var blocks: [Block] = []
        if firstKept <= boundaries.count {
            for ordinal in firstKept...boundaries.count {
                let start = ordinal == 0 ? text.startIndex : boundaries[ordinal - 1]
                let end = ordinal == boundaries.count ? text.endIndex : boundaries[ordinal]
                guard start < end else { continue }
                let blockText = String(text[start..<end])
                blocks.append(
                    Block(
                        ordinal: ordinal,
                        text: blockText,
                        fadeEnabled: isFadeable(blockText)
                    )
                )
            }
        }

        return BlockSplit(
            head: String(text[..<headEnd]),
            blocks: blocks,
            boundaryCount: boundaries.count
        )
    }

    private static func isFenceDelimiter(_ trimmedLine: String) -> Bool {
        trimmedLine.hasPrefix("```") || trimmedLine.hasPrefix("~~~")
    }

    private static func isBlockBoundaryLine(_ trimmedLine: String) -> Bool {
        let headingMarkerCount = trimmedLine.prefix(while: { $0 == "#" }).count
        let isHeading = (1...6).contains(headingMarkerCount)
            && trimmedLine.dropFirst(headingMarkerCount).first?.isWhitespace == true
        return isHeading || trimmedLine == "---" || trimmedLine == "***"
    }

    private static func isTopLevelListItemLine(_ line: Substring) -> Bool {
        // Nested items carry ≥2 spaces of indentation; splitting them off
        // would render them un-nested until absorbed, jumping the layout.
        let indent = line.prefix(while: { $0 == " " }).count
        guard indent <= 1 else { return false }
        let trimmedLine = String(line).trimmingCharacters(in: .whitespacesAndNewlines)

        if trimmedLine.hasPrefix("- ") || trimmedLine.hasPrefix("* ") || trimmedLine.hasPrefix("+ ") {
            return true
        }

        let digits = trimmedLine.prefix(while: \.isNumber)
        guard !digits.isEmpty, digits.count <= 9 else { return false }
        let rest = trimmedLine.dropFirst(digits.count)
        return rest.hasPrefix(". ") || rest.hasPrefix(") ")
    }

    private static func isFadeable(_ blockText: String) -> Bool {
        var sawContent = false
        var lineStart = blockText.startIndex
        while lineStart < blockText.endIndex {
            let lineEnd = blockText[lineStart...].firstIndex(of: "\n") ?? blockText.endIndex
            let trimmedLine = String(blockText[lineStart..<lineEnd])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if isFenceDelimiter(trimmedLine) {
                return false
            }
            if !sawContent, !trimmedLine.isEmpty {
                sawContent = true
                if trimmedLine.hasPrefix(">") || trimmedLine.hasPrefix("|") {
                    return false
                }
            }
            lineStart = lineEnd < blockText.endIndex ? blockText.index(after: lineEnd) : blockText.endIndex
        }
        return true
    }
}

/// Decides when completed blocks can leave the fade window and be absorbed
/// into the solid head. A block whose text has not been appended to for
/// `blockAbsorbDelay` has provably finished its cascade (the reveal queue
/// never leads the clock by more than `maxStampLead`, plus the fade itself),
/// so absorbing it is visually a no-op. A hard cap bounds the number of
/// in-flight block views regardless of timing.
enum StreamingTextFadeWindow {
    static let maxBlocks = 10

    static func advanceStart(
        current: Int,
        boundaryCount: Int,
        lastTouchedAt: [Int: TimeInterval],
        now: TimeInterval,
        absorbDelay: TimeInterval = StreamingTextFadeDefaults.blockAbsorbDelay
    ) -> Int {
        var start = max(0, current)
        while start < boundaryCount {
            let stale = now - (lastTouchedAt[start] ?? -.infinity) > absorbDelay
            let overCap = boundaryCount - start >= maxBlocks
            guard stale || overCap else { break }
            start += 1
        }
        return start
    }
}
