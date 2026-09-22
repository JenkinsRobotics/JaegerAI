import XCTest
@testable import HermesMobile

final class StreamingWordDrainTests: XCTestCase {
    // MARK: - unitCount

    func testUnitCountEmptyTextIsZero() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: ""), 0)
    }

    func testUnitCountTextWithoutWhitespaceIsOneUnit() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "chunk-0chunk-1chunk-2"), 1)
    }

    func testUnitCountWhitespaceOnlyTextIsOneUnit() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "  \n\t "), 1)
    }

    func testUnitCountCountsWordsWithTrailingWhitespace() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "alpha beta gamma"), 3)
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "alpha beta gamma "), 3)
    }

    func testUnitCountLeadingWhitespaceAttachesToFirstUnit() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "  alpha beta"), 2)
    }

    func testUnitCountTreatsConsecutiveWhitespaceAsOneSeparator() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "alpha  \n\n beta\t\tgamma"), 3)
    }

    func testUnitCountHandlesGraphemeClusters() {
        XCTAssertEqual(StreamingWordDrain.unitCount(in: "👩‍👩‍👧‍👦 🇫🇷 café"), 3)
    }

    // MARK: - splitAtUnitBoundary

    func testSplitAtUnitBoundaryRoundTripsForEveryCount() {
        let text = "  alpha beta\n\ngamma  delta epsilon"
        let unitCount = StreamingWordDrain.unitCount(in: text)
        for count in 0...(unitCount + 2) {
            let (head, tail) = StreamingWordDrain.splitAtUnitBoundary(text, unitCount: count)
            XCTAssertEqual(head + tail, text, "head + tail must reproduce input for count \(count)")
        }
    }

    func testSplitAtUnitBoundaryZeroCountReturnsEverythingInTail() {
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary("alpha beta", unitCount: 0)
        XCTAssertEqual(head, "")
        XCTAssertEqual(tail, "alpha beta")
    }

    func testSplitAtUnitBoundaryTakesWordsWithTrailingWhitespace() {
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary("alpha  beta gamma", unitCount: 1)
        XCTAssertEqual(head, "alpha  ")
        XCTAssertEqual(tail, "beta gamma")
    }

    func testSplitAtUnitBoundaryCountBeyondBacklogReturnsEverythingInHead() {
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary("alpha beta", unitCount: 5)
        XCTAssertEqual(head, "alpha beta")
        XCTAssertEqual(tail, "")
    }

    func testSplitAtUnitBoundaryNeverSplitsGraphemeClusters() {
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary("👩‍👩‍👧‍👦 x", unitCount: 1)
        XCTAssertEqual(head, "👩‍👩‍👧‍👦 ")
        XCTAssertEqual(tail, "x")
    }

    func testSplitAtUnitBoundaryKeepsCombiningMarksWithBaseCharacter() {
        // "e" + U+0301 combine into one grapheme; the boundary after "café" must
        // include the combining mark in head.
        let text = "cafe\u{301} au lait"
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary(text, unitCount: 1)
        XCTAssertEqual(head, "cafe\u{301} ")
        XCTAssertEqual(tail, "au lait")
    }

    func testSplitAtUnitBoundaryLeadingWhitespaceStaysWithFirstUnit() {
        let (head, tail) = StreamingWordDrain.splitAtUnitBoundary("  alpha beta", unitCount: 1)
        XCTAssertEqual(head, "  alpha ")
        XCTAssertEqual(tail, "beta")
    }

    // MARK: - drainQuota

    func testDrainQuotaSmallBacklogDrainsOneWordPerTick() {
        // 10 words × 48ms = 480ms, under the 1s lag bound → steady cadence.
        XCTAssertEqual(
            StreamingWordDrain.drainQuota(
                backlogUnitCount: 10,
                cadenceNanoseconds: 48_000_000,
                maxLagNanoseconds: 1_000_000_000
            ),
            1
        )
    }

    func testDrainQuotaScalesWithBacklogToStayWithinLagBound() {
        // 1000 words × 48ms = 48s of backlog; quota must scale to drain in ~1s.
        let quota = StreamingWordDrain.drainQuota(
            backlogUnitCount: 1000,
            cadenceNanoseconds: 48_000_000,
            maxLagNanoseconds: 1_000_000_000
        )
        XCTAssertEqual(quota, 48)
    }

    func testDrainQuotaNeverExceedsBacklog() {
        let quota = StreamingWordDrain.drainQuota(
            backlogUnitCount: 5,
            cadenceNanoseconds: 1_000_000_000,
            maxLagNanoseconds: 1_000_000
        )
        XCTAssertEqual(quota, 5)
    }

    func testDrainQuotaSingleUnitBacklogIsOne() {
        XCTAssertEqual(
            StreamingWordDrain.drainQuota(
                backlogUnitCount: 1,
                cadenceNanoseconds: 48_000_000,
                maxLagNanoseconds: 1_000_000_000
            ),
            1
        )
    }

    func testDrainQuotaZeroCadenceDrainsEverything() {
        XCTAssertEqual(
            StreamingWordDrain.drainQuota(
                backlogUnitCount: 7,
                cadenceNanoseconds: 0,
                maxLagNanoseconds: 1_000_000_000
            ),
            7
        )
    }

    func testDrainQuotaZeroLagBoundDrainsEverything() {
        XCTAssertEqual(
            StreamingWordDrain.drainQuota(
                backlogUnitCount: 7,
                cadenceNanoseconds: 48_000_000,
                maxLagNanoseconds: 0
            ),
            7
        )
    }
}
