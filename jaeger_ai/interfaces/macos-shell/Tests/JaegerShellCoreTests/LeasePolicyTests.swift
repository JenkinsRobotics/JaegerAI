import XCTest
@testable import JaegerShellCore

final class LeasePolicyTests: XCTestCase {
    let dev = "/Users/m/GitHub/JaegerAI-worktrees/mac-grok-ui/jaeger_ai/interfaces/macos-shell/.build/ui-rebuild/JaegerShell.app"
    func testInstalledAppHoldsTheLeaseByDefault() {
        XCTAssertEqual(LeasePolicy.decide(env: [:], bundlePath: "/Applications/Jaeger AI.app"), .enabled(reason: "installed app"))
        XCTAssertTrue(LeasePolicy.decide(env: [:], bundlePath: "/Applications/JaegerAI.app/").isEnabled)
    }
    func testDevBuildsGetNoLeaseByDefault() {
        XCTAssertEqual(LeasePolicy.decide(env: [:], bundlePath: dev), .disabled(reason: "not the installed app"))
        XCTAssertFalse(LeasePolicy.decide(env: [:], bundlePath: "/Users/m/macos-shell/Jaeger Dev.app").isEnabled)
        XCTAssertFalse(LeasePolicy.decide(env: [:], bundlePath: "/Applications/Jaeger AI.app.bak").isEnabled)
        XCTAssertFalse(LeasePolicy.decide(env: [:], bundlePath: "/Users/m/Applications/Jaeger AI.app").isEnabled)
    }
    func testNoLeaseAlwaysWinsEvenForTheInstalledAppAndOptIn() {
        for v in ["1", "true", "YES", " on "] {
            XCTAssertEqual(LeasePolicy.decide(env: ["JAEGER_SHELL_NO_LEASE": v], bundlePath: "/Applications/Jaeger AI.app"), .disabled(reason: "JAEGER_SHELL_NO_LEASE"))
            XCTAssertFalse(LeasePolicy.decide(env: ["JAEGER_SHELL_NO_LEASE": v, "JAEGER_SHELL_LEASE": "1"], bundlePath: dev).isEnabled)
        }
        XCTAssertTrue(LeasePolicy.decide(env: ["JAEGER_SHELL_NO_LEASE": "0"], bundlePath: "/Applications/Jaeger AI.app").isEnabled)
    }
    func testExplicitOptInForDevBuilds() {
        XCTAssertEqual(LeasePolicy.decide(env: ["JAEGER_SHELL_LEASE": "1"], bundlePath: dev), .enabled(reason: "JAEGER_SHELL_LEASE opt-in"))
        XCTAssertFalse(LeasePolicy.decide(env: ["JAEGER_SHELL_LEASE": ""], bundlePath: dev).isEnabled)
        XCTAssertFalse(LeasePolicy.decide(env: ["JAEGER_SHELL_LEASE": "0"], bundlePath: dev).isEnabled)
    }
}
