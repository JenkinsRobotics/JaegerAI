import XCTest
@testable import JaegerShellCore

final class LifecycleLeaseTests: XCTestCase {
    let home = "/Users/t"

    func testPathFollowsLifecycleLeasePyOrder() {
        XCTAssertEqual(LeaseContract.path(env: [:], home: home), "/Users/t/.jaeger/control/lifecycle-lease.json")
        XCTAssertEqual(LeaseContract.path(env: ["JAEGER_HOME": "~/jh"], home: home), "/Users/t/jh/.jaeger_ai/control/lifecycle-lease.json")
        XCTAssertEqual(LeaseContract.path(env: ["JAEGER_HOME": "/x", "JAEGER_STATE_DIR": "/s"], home: home), "/s/control/lifecycle-lease.json")
        XCTAssertEqual(LeaseContract.path(env: ["JAEGER_STATE_DIR": "/s", "JAEGER_LIFECYCLE_LEASE": "~/l.json"], home: home), "/Users/t/l.json")
        XCTAssertEqual(LeaseContract.path(env: ["JAEGER_STATE_DIR": "  "], home: home), "/Users/t/.jaeger/control/lifecycle-lease.json")
        XCTAssertEqual(LeaseContract.path(stateDir: "/c/state"), "/c/state/control/lifecycle-lease.json")
        XCTAssertEqual(LeaseContract.realOperatorPath(home: home), LeaseContract.path(env: [:], home: home))
    }

    func testBodyMatchesPythonBeat() {
        XCTAssertEqual(LeaseContract.body(beatAt: 0), "{\"beat_at\": 0.000000, \"owner\": \"menubar\"}\n")
        XCTAssertEqual(LeaseContract.beatAt(contents: LeaseContract.body(beatAt: 1760745600.25)), 1760745600.25)
    }

    func testDecisionMirrorsContract() {
        let now = 1_000_000.0
        XCTAssertEqual(LeaseContract.decide(contents: nil, now: now), .noLease)
        XCTAssertEqual(LeaseContract.decide(contents: LeaseContract.body(beatAt: now - 1), now: now), .alive)
        XCTAssertEqual(LeaseContract.decide(contents: LeaseContract.body(beatAt: now - 6), now: now), .suspended)
        XCTAssertEqual(LeaseContract.decide(contents: LeaseContract.body(beatAt: now - 16), now: now), .shutdown("lifecycle owner disappeared"))
        XCTAssertEqual(LeaseContract.decide(contents: LeaseContract.body(beatAt: 0), now: now), .shutdown("lifecycle owner disappeared"))
        XCTAssertEqual(LeaseContract.decide(contents: #"{"beat_at": 1, "owner": "webui"}"#, now: 1), .shutdown("lifecycle lease is not the menu bar"))
        XCTAssertEqual(LeaseContract.decide(contents: "garbage", now: now), .shutdown("lifecycle lease is unreadable"))
    }

    func testBeatIsFasterThanSuspend() {
        XCTAssertLessThan(LeaseContract.beatInterval * 2, LeaseContract.suspendAfter)
    }

    func testRetireIsRemoveUnlessDevBuildAsksForExpire() {
        XCTAssertEqual(LeaseRetire.resolve(env: [:], isDevBuild: true), .remove)
        XCTAssertEqual(LeaseRetire.resolve(env: ["JAEGER_SHELL_LEASE_RETIRE": "expire"], isDevBuild: false), .remove)
        XCTAssertEqual(LeaseRetire.resolve(env: ["JAEGER_SHELL_LEASE_RETIRE": "Expire"], isDevBuild: true), .expire)
        XCTAssertEqual(LeaseRetire.allowed(.expire, isDevBuild: false), .remove)
        XCTAssertEqual(LeaseRetire.allowed(.expire, isDevBuild: true), .expire)
    }
}
