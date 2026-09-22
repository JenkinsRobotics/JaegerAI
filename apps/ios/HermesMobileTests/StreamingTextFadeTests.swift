import MarkdownUI
import SwiftUI
import XCTest
@testable import HermesMobile

final class StreamingTextFadeTests: XCTestCase {
    private let fade = StreamingTextFadeDefaults.fadeDuration
    private let floorOpacity = StreamingTextFadeDefaults.floorOpacity

    // MARK: - StreamingTextFadeCurve

    func testCurveStartsAtFloorOpacity() {
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: 0), floorOpacity)
    }

    func testCurveReachesFullOpacityAtFadeDuration() {
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: fade), 1)
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: fade * 10), 1)
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: .infinity), 1)
    }

    func testCurveIsMonotonicallyIncreasingWithAge() {
        let ages = stride(from: 0.0, through: fade, by: fade / 20).map { $0 }
        let opacities = ages.map { StreamingTextFadeCurve.opacity(age: $0) }
        for (earlier, later) in zip(opacities, opacities.dropFirst()) {
            XCTAssertLessThanOrEqual(earlier, later)
        }
    }

    func testCurveClampsNegativeAgeToFloor() {
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: -0.5), floorOpacity)
    }

    func testCurveZeroDurationIsAlwaysOpaque() {
        XCTAssertEqual(StreamingTextFadeCurve.opacity(age: 0, fadeDuration: 0), 1)
    }

    func testCurveProducesTrailingGradientAtWordCadence() {
        // Words stamped one #212 tick (48ms) apart: the newest must be the
        // faintest and each older word strictly more opaque until solid.
        let cadence = 0.048
        let newest = StreamingTextFadeCurve.opacity(age: 0)
        let previous = StreamingTextFadeCurve.opacity(age: cadence)
        let older = StreamingTextFadeCurve.opacity(age: cadence * 2)
        let oldest = StreamingTextFadeCurve.opacity(age: fade)

        XCTAssertLessThan(newest, previous)
        XCTAssertLessThan(previous, older)
        XCTAssertLessThan(older, oldest)
        XCTAssertEqual(oldest, 1)
    }

    // MARK: - StreamingTextFadeStampStore

    private let stagger = StreamingTextFadeDefaults.glyphStagger
    private let maxLead = StreamingTextFadeDefaults.maxStampLead

    func testStoreBaselineCharactersNeverFade() {
        let store = StreamingTextFadeStampStore<Int>()
        store.register([0, 1], clock: 0)
        XCTAssertEqual(store.opacity(for: 0, clock: 0), 1)
        XCTAssertEqual(store.opacity(for: 1, clock: 0), 1)
        store.finishBaseline()

        // Baseline characters stay opaque on every later frame too.
        XCTAssertEqual(store.opacity(for: 0, clock: 5), 1)
    }

    func testStoreNewCharacterAfterBaselineFadesIn() {
        let store = StreamingTextFadeStampStore<Int>()
        store.register([0], clock: 0)
        store.finishBaseline()

        store.register([1], clock: 1)
        XCTAssertEqual(store.opacity(for: 1, clock: 1), floorOpacity)
        let mid = store.opacity(for: 1, clock: 1 + fade / 2)
        XCTAssertGreaterThan(mid, floorOpacity)
        XCTAssertLessThan(mid, 1)
        XCTAssertEqual(store.opacity(for: 1, clock: 1 + fade), 1)
    }

    func testStoreRepeatRegisterKeepsOriginalStamp() {
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        store.register([7], clock: 2)
        // Re-registering on later frames must not re-stamp (which would
        // reset the fade every frame).
        store.register([7], clock: 2 + fade / 2)
        store.register([7], clock: 2 + fade)
        XCTAssertEqual(store.opacity(for: 7, clock: 2 + fade), 1)
    }

    func testStoreBatchCascadesInReadingOrder() {
        // Glyphs arriving in one draw frame (a multi-word drain batch) must
        // reveal in sequence, newest-last — not as one chunk.
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        store.register([1, 2, 3], clock: 10)
        let probe = 10 + stagger * 2
        let first = store.opacity(for: 1, clock: probe)
        let second = store.opacity(for: 2, clock: probe)
        let third = store.opacity(for: 3, clock: probe)
        XCTAssertGreaterThan(first, second)
        XCTAssertGreaterThan(second, third)
    }

    func testStoreQueueContinuesAcrossBatches() {
        // A glyph arriving one frame after a queued batch must reveal after
        // the queue tail, not jump in at arrival time.
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        store.register([1, 2], clock: 10)
        store.register([3], clock: 10.001)
        let probe = 10 + stagger * 2 + 0.001
        XCTAssertGreaterThan(
            store.opacity(for: 2, clock: probe),
            store.opacity(for: 3, clock: probe)
        )
    }

    func testStoreLeadCompressionBoundsTheQueue() {
        // A huge batch must compress its pace so the last glyph's reveal
        // stays within maxStampLead of the clock.
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        store.register(Array(0..<2_000), clock: 10)
        XCTAssertEqual(store.opacity(for: 1_999, clock: 10 + maxLead + fade), 1)
        // And it still cascades: the first glyph leads the last.
        let probe = 10 + maxLead / 2
        XCTAssertGreaterThan(
            store.opacity(for: 0, clock: probe),
            store.opacity(for: 1_999, clock: probe)
        )
    }

    func testStoreSaturatedQueueStaysBounded() {
        // Repeated batches at a saturated queue must not push reveals
        // arbitrarily far into the future.
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        var nextKey = 0
        for tick in 0..<50 {
            let clock = 10 + Double(tick) * 0.048
            store.register(Array(nextKey..<(nextKey + 40)), clock: clock)
            nextKey += 40
        }
        let lastClock = 10 + 49 * 0.048
        XCTAssertEqual(store.opacity(for: nextKey - 1, clock: lastClock + maxLead + fade), 1)
    }

    func testStoreUnregisteredKeyIsOpaque() {
        let store = StreamingTextFadeStampStore<Int>()
        store.finishBaseline()
        XCTAssertEqual(store.opacity(for: 42, clock: 1), 1)
    }

    func testStoreNilKeyIsOpaque() {
        let store = StreamingTextFadeStampStore<Int>()
        store.finishBaseline()
        XCTAssertEqual(store.opacity(for: nil, clock: 1), 1)
    }

    func testStoreRolloverResetKeepsFadingArmed() {
        let store = StreamingTextFadeStampStore<Int>()
        store.register([0], clock: 0)
        store.finishBaseline()
        XCTAssertEqual(store.opacity(for: 0, clock: 5), 1)

        store.rolloverReset()

        // The same character offset belongs to a brand-new block now and
        // must fade in rather than inherit the old block's stamp.
        store.register([0], clock: 5)
        XCTAssertEqual(store.opacity(for: 0, clock: 5), floorOpacity)
        XCTAssertEqual(store.opacity(for: 0, clock: 5 + fade), 1)
    }

    func testStoreRolloverResetBeforeBaselineArmsFading() {
        let store = StreamingTextFadeStampStore<Int>()
        store.rolloverReset()

        // First content arriving into a previously empty tail fades in.
        store.register([0], clock: 1)
        XCTAssertEqual(store.opacity(for: 0, clock: 1), floorOpacity)
    }

    // MARK: - StreamedTextAnimationSettings

    func testAnimationSettingRoutesEverythingToHeadWhenDisabled() {
        // Int.max puts all blocks in the solid head — no fade renderer, no
        // frame clock (same mechanism as Reduce Motion).
        XCTAssertEqual(
            StreamedTextAnimationSettings.effectiveFirstFadeOrdinal(3, reduceMotion: false, isEnabled: false),
            Int.max
        )
        XCTAssertEqual(
            StreamedTextAnimationSettings.effectiveFirstFadeOrdinal(3, reduceMotion: true, isEnabled: true),
            Int.max
        )
        XCTAssertEqual(
            StreamedTextAnimationSettings.effectiveFirstFadeOrdinal(3, reduceMotion: false, isEnabled: true),
            3
        )
    }

    // MARK: - StreamingTextFadeStampChain

    func testChainedBlocksRevealInReadingOrder() {
        // The #234 lab inversion: a fast stream backlogs line 2's queue up to
        // maxStampLead, then line 3 starts a fresh store. Sharing one chain,
        // line 3 must queue behind line 2's tail instead of jumping to "now".
        let chain = StreamingTextFadeStampChain()
        let lineTwo = StreamingTextFadeStampStore<Int>(chain: chain)
        let lineThree = StreamingTextFadeStampStore<Int>(chain: chain)
        lineTwo.rolloverReset()
        lineThree.rolloverReset()

        lineTwo.register(Array(0..<2_000), clock: 10)
        lineThree.register([0, 1], clock: 10.001)

        // At every instant of the cascade, line 3's first glyph is never
        // more revealed than line 2's last glyph.
        for probe in stride(from: 10.0, through: 10 + maxLead + fade, by: 0.02) {
            XCTAssertLessThanOrEqual(
                lineThree.opacity(for: 0, clock: probe),
                lineTwo.opacity(for: 1_999, clock: probe),
                "line 3 overtook line 2's tail at clock \(probe)"
            )
        }
    }

    func testChainedBlockWithIdleChainStartsAtClock() {
        // When the previous block's cascade already drained, the next block
        // reveals immediately — chaining adds no artificial delay.
        let chain = StreamingTextFadeStampChain()
        let first = StreamingTextFadeStampStore<Int>(chain: chain)
        first.rolloverReset()
        first.register([0], clock: 10)

        let second = StreamingTextFadeStampStore<Int>(chain: chain)
        second.rolloverReset()
        second.register([0], clock: 20)
        XCTAssertEqual(second.opacity(for: 0, clock: 20), floorOpacity)
        XCTAssertEqual(second.opacity(for: 0, clock: 20 + fade), 1)
    }

    func testChainResetForgetsBacklog() {
        // Wholesale content replacement resets the cursor so the restarted
        // window does not inherit a stale future backlog.
        let chain = StreamingTextFadeStampChain()
        let before = StreamingTextFadeStampStore<Int>(chain: chain)
        before.rolloverReset()
        before.register(Array(0..<2_000), clock: 10)

        chain.reset()

        let after = StreamingTextFadeStampStore<Int>(chain: chain)
        after.rolloverReset()
        after.register([0], clock: 10.001)
        XCTAssertEqual(after.opacity(for: 0, clock: 10.001), floorOpacity)
        XCTAssertEqual(after.opacity(for: 0, clock: 10.001 + fade), 1)
    }

    // MARK: - StreamingTextFadeTailSplitter

    private func assertRoundTrip(_ text: String, from firstFadeOrdinal: Int = 0, file: StaticString = #filePath, line: UInt = #line) {
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: firstFadeOrdinal)
        let joined = split.head + split.blocks.map(\.text).joined()
        XCTAssertEqual(joined, text, "head + block texts must reproduce the input", file: file, line: line)
    }

    func testSplitterEmptyText() {
        let split = StreamingTextFadeTailSplitter.split("", firstFadeOrdinal: 0)
        XCTAssertEqual(split.head, "")
        XCTAssertTrue(split.blocks.isEmpty)
        XCTAssertEqual(split.boundaryCount, 0)
    }

    func testSplitterSingleParagraphIsOneBlock() {
        let split = StreamingTextFadeTailSplitter.split("Hello **world**, streaming", firstFadeOrdinal: 0)
        XCTAssertEqual(split.head, "")
        XCTAssertEqual(split.blocks, [
            StreamingTextFadeTailSplitter.Block(ordinal: 0, text: "Hello **world**, streaming", fadeEnabled: true)
        ])
    }

    func testSplitterBlankLineSeparatesBlocks() {
        let text = "First paragraph.\n\nSecond paragraph still stre"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.boundaryCount, 1)
        XCTAssertEqual(split.blocks.map(\.text), ["First paragraph.\n\n", "Second paragraph still stre"])
        assertRoundTrip(text)
    }

    func testSplitterFirstFadeOrdinalMovesEarlierBlocksToHead() {
        let text = "First paragraph.\n\nSecond paragraph still stre"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 1)
        XCTAssertEqual(split.head, "First paragraph.\n\n")
        XCTAssertEqual(split.blocks.map(\.ordinal), [1])
        assertRoundTrip(text, from: 1)
    }

    func testSplitterFirstFadeOrdinalBeyondCountYieldsAllHead() {
        let text = "First paragraph.\n\nSecond"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: Int.max)
        XCTAssertEqual(split.head, text)
        XCTAssertTrue(split.blocks.isEmpty)
    }

    func testSplitterOrdinalsAreStableAcrossAppends() {
        let before = StreamingTextFadeTailSplitter.split("a\n\nb gro", firstFadeOrdinal: 0)
        let after = StreamingTextFadeTailSplitter.split("a\n\nb grows\n\nc starts", firstFadeOrdinal: 0)
        XCTAssertEqual(before.blocks[0].text, after.blocks[0].text)
        XCTAssertEqual(before.blocks[0].ordinal, after.blocks[0].ordinal)
        XCTAssertEqual(after.blocks.map(\.ordinal), [0, 1, 2])
    }

    func testSplitterTrailingBlankLineYieldsNoCurrentBlock() {
        let text = "First paragraph.\n\n"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 1)
        XCTAssertEqual(split.head, text)
        XCTAssertTrue(split.blocks.isEmpty)
    }

    func testSplitterSoftWrappedParagraphStaysOneBlock() {
        let text = "line one\nline two of the same paragraph"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), [text])
    }

    func testSplitterUnclosedFenceBlockIsNotFadeable() {
        let text = "Intro.\n\n```swift\nlet x = 1\n"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [true, false])
        XCTAssertEqual(split.blocks[1].text, "```swift\nlet x = 1\n")
    }

    func testSplitterClosedFenceCreatesBoundaryAfterIt() {
        let text = "```swift\nlet x = 1\n```\nAfter the code"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), ["```swift\nlet x = 1\n```\n", "After the code"])
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [false, true])
        assertRoundTrip(text)
    }

    func testSplitterBlankLineInsideFenceIsNotABoundary() {
        let text = "```\nfirst\n\nsecond\n"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.boundaryCount, 0)
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [false])
    }

    func testSplitterTildeFenceIsRecognized() {
        let split = StreamingTextFadeTailSplitter.split("~~~\ncode\n", firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [false])
    }

    func testSplitterHeadingLineIsABoundary() {
        let text = "## Section\nBody text streaming"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), ["## Section\n", "Body text streaming"])
    }

    func testSplitterStreamingHeadingWithoutNewlineIsCurrentBlock() {
        let text = "Intro.\n\n## Partial headi"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 1)
        XCTAssertEqual(split.head, "Intro.\n\n")
        XCTAssertEqual(split.blocks.map(\.text), ["## Partial headi"])
    }

    func testSplitterThematicBreakIsABoundary() {
        let text = "Before.\n---\nAfter words"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), ["Before.\n---\n", "After words"])
    }

    func testSplitterCompletedTopLevelItemsAreBoundaries() {
        // MarkdownUI renders one Text per list item, so each completed item
        // becomes its own fade block and only the in-progress item grows.
        let text = "Intro:\n\n- first item\n- second item\n- third streaming ite"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), [
            "Intro:\n\n",
            "- first item\n",
            "- second item\n",
            "- third streaming ite"
        ])
        assertRoundTrip(text)
    }

    func testSplitterCompletedOrderedItemsAreBoundaries() {
        let text = "1. alpha\n2. beta\n3. gamma still str"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 2)
        XCTAssertEqual(split.head, "1. alpha\n2. beta\n")
        XCTAssertEqual(split.blocks.map(\.text), ["3. gamma still str"])
        assertRoundTrip(text, from: 2)
    }

    func testSplitterNestedItemLinesAreNotBoundaries() {
        // Splitting a nested item into its own Markdown view would render it
        // un-nested and jump the layout when absorbed; it stays in its
        // parent's block instead.
        let text = "- parent item\n  - nested child\n  - second child gro"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.boundaryCount, 0)
        XCTAssertEqual(split.blocks.map(\.text), [text])
    }

    func testSplitterThematicBreakLineIsNotMistakenForBullet() {
        let text = "***\nAfter break words"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.text), ["***\n", "After break words"])
    }

    func testSplitterBlockquoteBlockIsNotFadeable() {
        let text = "Intro.\n\n> quoted words streaming"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [true, false])
    }

    func testSplitterTableBlockIsNotFadeable() {
        let text = "Intro.\n\n| a | b |\n|---|---|\n| 1 | 2"
        let split = StreamingTextFadeTailSplitter.split(text, firstFadeOrdinal: 0)
        XCTAssertEqual(split.blocks.map(\.fadeEnabled), [true, false])
    }

    func testSplitterRoundTripsAcrossShapesAndOrdinals() {
        let samples = [
            "",
            "word",
            "a\n\nb\n\nc",
            "Intro.\n\n```swift\ncode\n```\ntail",
            "## H\n\n- item one\n- item two",
            "1. a\n2. b\n3. c",
            "para\n\n",
            "  \n\t\n",
            "emoji 👩‍👩‍👧‍👦 tail café"
        ]
        for sample in samples {
            for ordinal in 0...4 {
                assertRoundTrip(sample, from: ordinal)
            }
        }
    }

    // MARK: - StreamingTextFadeWindow

    func testWindowKeepsFreshBlocks() {
        let start = StreamingTextFadeWindow.advanceStart(
            current: 3,
            boundaryCount: 5,
            lastTouchedAt: [3: 100, 4: 100.5, 5: 101],
            now: 101,
            absorbDelay: 1.3
        )
        XCTAssertEqual(start, 3)
    }

    func testWindowAbsorbsBlocksUntouchedPastTheDelay() {
        let start = StreamingTextFadeWindow.advanceStart(
            current: 3,
            boundaryCount: 6,
            lastTouchedAt: [3: 100, 4: 100.1, 5: 105.9, 6: 106],
            now: 106,
            absorbDelay: 1.3
        )
        // Blocks 3 and 4 finished their cascade long ago; 5 is still fresh.
        XCTAssertEqual(start, 5)
    }

    func testWindowNeverAbsorbsTheCurrentBlock() {
        let start = StreamingTextFadeWindow.advanceStart(
            current: 2,
            boundaryCount: 2,
            lastTouchedAt: [:],
            now: 1_000,
            absorbDelay: 1.3
        )
        XCTAssertEqual(start, 2)
    }

    func testWindowCapForcesAbsorptionOfOldestBlocks() {
        let touched = Dictionary(uniqueKeysWithValues: (0...30).map { ($0, 100.0) })
        let start = StreamingTextFadeWindow.advanceStart(
            current: 0,
            boundaryCount: 30,
            lastTouchedAt: touched,
            now: 100.1,
            absorbDelay: 1.3
        )
        XCTAssertEqual(start, 30 - StreamingTextFadeWindow.maxBlocks + 1)
    }

    // MARK: - Renderer attach + opacity through the real MarkdownUI pipeline

    @MainActor
    func testFadeRendererAttachesThroughMarkdownUIAndAppliesStampOpacity() throws {
        let markdown = "Streaming fade attach probe with several plain words"
        let clock: TimeInterval = 1_000

        // Armed store: every character stamps at first sight → age 0 →
        // opacity 0 → no visible ink. If .textRenderer does not attach
        // through MarkdownUI's subtree, the text renders solid and this
        // test fails loudly.
        let armedStore = StreamingTextFadeStampStore<Text.Layout.CharacterIndex>()
        armedStore.rolloverReset()
        let fadedInk = try renderedDarkness(markdown: markdown, store: armedStore, clock: clock)

        // Untouched store: the first draw is the baseline → opacity 1.
        let baselineStore = StreamingTextFadeStampStore<Text.Layout.CharacterIndex>()
        let solidInk = try renderedDarkness(markdown: markdown, store: baselineStore, clock: clock)

        XCTAssertGreaterThan(solidInk, 0, "baseline render must produce visible text")
        XCTAssertLessThan(
            fadedInk, solidInk / 20,
            "age-zero stamps must render (near-)invisible — if not, the fade renderer is not attached through MarkdownUI"
        )
    }

    @MainActor
    func testFadeRendererCascadesInkOverTime() throws {
        let markdown = "Streaming fade cascade probe with several plain words"
        let clock: TimeInterval = 1_000

        let store = StreamingTextFadeStampStore<Text.Layout.CharacterIndex>()
        store.rolloverReset()
        // First render queues every glyph's reveal stamp from `clock`.
        let startInk = try renderedDarkness(markdown: markdown, store: store, clock: clock)
        let earlyInk = try renderedDarkness(markdown: markdown, store: store, clock: clock + 0.12)
        let lateInk = try renderedDarkness(markdown: markdown, store: store, clock: clock + 0.28)
        let doneInk = try renderedDarkness(
            markdown: markdown,
            store: store,
            clock: clock + maxLead + fade + 0.05
        )

        let solidStore = StreamingTextFadeStampStore<Text.Layout.CharacterIndex>()
        let solidInk = try renderedDarkness(markdown: markdown, store: solidStore, clock: clock)

        // Ink must bleed in progressively (the moving-gradient cascade), not
        // jump from invisible to solid in one step.
        XCTAssertLessThan(startInk, solidInk / 20)
        XCTAssertGreaterThan(earlyInk, Int(Double(solidInk) * 0.03), "cascade should have visibly started")
        XCTAssertLessThan(earlyInk, Int(Double(solidInk) * 0.7), "cascade should not be done this early")
        XCTAssertGreaterThan(lateInk, earlyInk, "ink must keep increasing through the cascade")
        XCTAssertGreaterThan(doneInk, Int(Double(solidInk) * 0.95), "cascade must finish fully solid")
    }

    @MainActor
    private func renderedDarkness(
        markdown: String,
        store: StreamingTextFadeStampStore<Text.Layout.CharacterIndex>,
        clock: TimeInterval
    ) throws -> Int {
        let view = Markdown(markdown)
            .textRenderer(StreamingTextFadeRenderer(clock: clock, store: store))
            .frame(width: 320, alignment: .leading)
            .background(SwiftUI.Color.white)
            .environment(\.colorScheme, .light)

        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        let image = try XCTUnwrap(renderer.cgImage, "ImageRenderer produced no image")
        return darknessSum(in: image)
    }

    /// Sum of per-pixel darkness vs. white; antialiasing-tolerant measure of
    /// how much ink the text laid down.
    private func darknessSum(in image: CGImage) -> Int {
        let width = image.width
        let height = image.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        guard let context = CGContext(
            data: &pixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            return 0
        }
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))

        var sum = 0
        for index in stride(from: 0, to: pixels.count, by: 4) {
            let rgb = Int(pixels[index]) + Int(pixels[index + 1]) + Int(pixels[index + 2])
            sum += max(0, 765 - rgb)
        }
        return sum
    }
}
