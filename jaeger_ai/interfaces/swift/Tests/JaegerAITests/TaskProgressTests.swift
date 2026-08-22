//
//  TaskProgressTests.swift
//  JaegerAITests
//
//  Live work-ledger frames → ToolProgress. Additive: a core that
//  only sends ``detail: "worker 190/292"`` still parses, and a
//  structured ``args`` snapshot wins when present.
//

import XCTest
@testable import JaegerAI

final class TaskProgressTests: XCTestCase {

    func testParseFromStructuredArgs() {
        let args: [String: Any] = [
            "task_id": "abc123",
            "task_name": "notes",
            "done": 190,
            "total": 292,
            "remaining": 102,
            "in_progress": ["item_190.txt"],
            "completed": false,
            "state": "RUNNING",
            "step": 4,
        ]
        let progress = ToolProgress.parse(
            name: "work_ledger",
            detail: "notes · 190/292 · item_190.txt",
            args: args
        )
        XCTAssertEqual(progress?.taskName, "notes")
        XCTAssertEqual(progress?.done, 190)
        XCTAssertEqual(progress?.total, 292)
        XCTAssertEqual(progress?.remaining, 102)
        XCTAssertEqual(progress?.currentItem, "item_190.txt")
        XCTAssertEqual(progress?.step, 4)
        XCTAssertEqual(progress?.countLabel, "190/292")
        XCTAssertFalse(progress?.completed ?? true)
        XCTAssertEqual(progress?.fraction ?? 0, 190.0 / 292.0, accuracy: 0.001)
    }

    func testParseLegacyWorkerDetail() {
        let progress = ToolProgress.parse(
            name: "work_ledger",
            detail: "worker 12/50",
            args: nil
        )
        XCTAssertEqual(progress?.done, 12)
        XCTAssertEqual(progress?.total, 50)
        XCTAssertEqual(progress?.countLabel, "12/50")
        XCTAssertFalse(progress?.completed ?? true)
    }

    func testParseNamedDetailWithCurrentItem() {
        let progress = ToolProgress.parse(
            name: "work_ledger",
            detail: "notes · 2/4 · item_02.txt",
            args: nil
        )
        XCTAssertEqual(progress?.taskName, "notes")
        XCTAssertEqual(progress?.done, 2)
        XCTAssertEqual(progress?.total, 4)
        XCTAssertEqual(progress?.currentItem, "item_02.txt")
    }

    func testCompletedWhenDoneMeetsTotal() {
        let progress = ToolProgress.parse(
            name: "work_ledger",
            detail: "notes · 4/4",
            args: ["done": 4, "total": 4, "completed": true,
                   "task_name": "notes", "task_id": "x"]
        )
        XCTAssertEqual(progress?.completed, true)
        XCTAssertEqual(progress?.fraction, 1.0)
        XCTAssertEqual(progress?.state, "COMPLETED")
    }

    func testOrdinaryToolChipIsNil() {
        XCTAssertNil(ToolProgress.parse(
            name: "web_search", detail: "view scheduling", args: nil))
        XCTAssertNil(ToolProgress.parse(
            name: "read_file", detail: "src/main.py", args: nil))
    }

    func testProtocolFrameDecodesWorkLedgerArgs() throws {
        let json: [String: Any] = [
            "type": "tool",
            "name": "work_ledger",
            "phase": "progress",
            "elapsed_s": 0,
            "detail": "notes · 3/10 · item_03.txt",
            "args": [
                "task_id": "t1",
                "task_name": "notes",
                "done": 3,
                "total": 10,
                "remaining": 7,
                "in_progress": ["item_03.txt"],
                "completed": false,
                "state": "RUNNING",
            ],
        ]
        let data = try JSONSerialization.data(withJSONObject: json)
        guard let frame = ProtocolFrame.decode(data),
              case .tool(let name, let phase, _, let detail, let progress) = frame
        else {
            return XCTFail("did not decode")
        }
        XCTAssertEqual(name, "work_ledger")
        XCTAssertEqual(phase, "progress")
        XCTAssertEqual(detail, "notes · 3/10 · item_03.txt")
        XCTAssertEqual(progress?.taskId, "t1")
        XCTAssertEqual(progress?.done, 3)
        XCTAssertEqual(progress?.total, 10)
        XCTAssertEqual(progress?.currentItem, "item_03.txt")
    }
}
