import Foundation
import XCTest
@testable import JaegerAI

final class ProcessTreeTests: XCTestCase {
    func testDescendantsFindsNestedChildren() async throws {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/sh")
        proc.arguments = ["-c", "sleep 60 & sleep 60 & wait"]
        try proc.run()
        let root = proc.processIdentifier
        defer { proc.terminate() }

        var kids: [pid_t] = []
        for _ in 0..<40 {
            kids = ProcessTree.descendants(of: root)
            if kids.count >= 2 { break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertGreaterThanOrEqual(kids.count, 2, "expected nested sleep children under \(root)")
    }

    func testTerminateReapsRootAndDescendants() async throws {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/sh")
        proc.arguments = ["-c", "sleep 60 & sleep 60 & wait"]
        try proc.run()
        let root = proc.processIdentifier

        var kids: [pid_t] = []
        for _ in 0..<40 {
            kids = ProcessTree.descendants(of: root)
            if kids.count >= 2 { break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertGreaterThanOrEqual(kids.count, 2)

        await ProcessTree.terminate(root: root, graceSeconds: 1)

        XCTAssertFalse(ProcessTree.isAlive(root), "root \(root) survived")
        for pid in kids {
            XCTAssertFalse(ProcessTree.isAlive(pid), "orphan pid \(pid)")
        }
    }

    func testWatchdogScriptCapturesParentPidNotLivePPID() {
        let script = ProcessTree.parentDeathWatchdogScript(parent: 4242, root: 4343)
        XCTAssertTrue(script.contains("parent=4242"))
        XCTAssertTrue(script.contains("root=4343"))
        XCTAssertTrue(script.contains("kill -0 \"$parent\""))
        XCTAssertFalse(script.contains("kill -0 \"$PPID\""))
        XCTAssertTrue(script.contains("kill -TERM"))
        XCTAssertTrue(script.contains("kill -KILL"))
    }

    func testNeverTargetsPidOne() async {
        await ProcessTree.terminate(root: 1, graceSeconds: 0)
        await ProcessTree.terminate(pids: [0, 1, -1], graceSeconds: 0)
        XCTAssertTrue(ProcessTree.isAlive(getpid()))
    }
}
