import XCTest
@testable import JaegerAI

final class WorkspaceSnapshotTests: XCTestCase {
    func testParsesBranchAndGitPorcelainStatusesWithSpaces() {
        let root = URL(fileURLWithPath: "/tmp/Jaeger Repo")
        let snapshot = WorkspaceSnapshot.parseGitStatus(
            "## 0.13-dev...origin/0.13-dev\n M jaeger_ai/core/gateway/server.py\n?? new file.txt\nA  staged.swift\n",
            repoRoot: root
        )

        XCTAssertEqual(snapshot.branch, "0.13-dev")
        XCTAssertEqual(snapshot.repoRoot, root)
        XCTAssertEqual(snapshot.changes.map(\.path), [
            "jaeger_ai/core/gateway/server.py", "new file.txt", "staged.swift"
        ])
        XCTAssertEqual(snapshot.changes.map(\.badge), ["M", "?", "A"])
    }

    func testCleanWorkingTreeHasNoChanges() {
        let snapshot = WorkspaceSnapshot.parseGitStatus(
            "## main\n", repoRoot: URL(fileURLWithPath: "/tmp/repo")
        )
        XCTAssertEqual(snapshot.branch, "main")
        XCTAssertTrue(snapshot.changes.isEmpty)
    }
}
