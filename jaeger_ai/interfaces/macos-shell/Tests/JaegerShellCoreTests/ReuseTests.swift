import XCTest
@testable import JaegerShellCore

final class ReuseTests: XCTestCase {
    let home = "/Users/t"
    let bundle = "/Users/t/.jaeger/apps/swift-build/ui-rebuild/JaegerShell.app"

    func testLauncherOrder() {
        let c = LauncherResolver.candidates(env: ["JAEGER_VENV": "/v"], plistLauncher: "~/bin/jaeger", bundlePath: bundle, home: home)
        XCTAssertEqual(c[0], "/Users/t/bin/jaeger")
        XCTAssertTrue(c.firstIndex(of: "/Users/t/GitHub/JaegerAI/jaeger")! < c.firstIndex(of: "/v/bin/jaeger")!)
        XCTAssertEqual(c[1], "/Users/t/.jaeger/apps/swift-build/ui-rebuild/jaeger")
        XCTAssertTrue(c.contains("/Users/t/GitHub/JaegerAI/jaeger"))
        XCTAssertEqual(c.last, "/usr/local/bin/jaeger")
    }

    func testLauncherRequiresExecutable() {
        XCTAssertNil(LauncherResolver.resolve(env: [:], plistLauncher: nil, bundlePath: bundle, home: home, isExecutable: { _ in false }))
        let hit = LauncherResolver.resolve(env: [:], plistLauncher: nil, bundlePath: bundle, home: home,
                                           isExecutable: { $0 == "/Users/t/.jaeger/venv/bin/jaeger" })
        XCTAssertEqual(hit, "/Users/t/.jaeger/venv/bin/jaeger")
    }

    func testStackActionDecode() throws {
        let json = #"{"ok": true, "step": "done", "services": [{"id": "gateway", "name": "gateway", "label": "ai.jaeger.gateway", "pid": 12, "state": "running", "raw_state": "running", "ready": true, "configured": true, "port": 33418, "git_commit": null, "head_commit": null, "stale": false}]}"#
        let reply = try StackCLI.decodeAction(Data(json.utf8))
        XCTAssertTrue(reply.ok)
        XCTAssertEqual(reply.services?.first?.port, 33418)
        XCTAssertEqual(StackCLI.summary(reply), "ok=true services=1 ready=1 step=done")
        XCTAssertThrowsError(try StackCLI.decodeAction(Data("nope".utf8)))
    }
}
