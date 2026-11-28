import XCTest
@testable import JaegerShellCore

final class GatewayHealthTests: XCTestCase {
    func testParsesModularGatewayHealthyPayload() {
        let json = """
        {
          "ok": true,
          "status": "ok",
          "service": "jaeger-gateway",
          "architecture": "modular-standalone",
          "all_green": true,
          "pid": 4242,
          "model": "ollama:gemma4:12b",
          "checks": {
            "gateway": {"ok": true},
            "ollama": {"ok": true},
            "webui": {"ok": true}
          }
        }
        """
        let report = GatewayHealth.parse(statusCode: 200, data: Data(json.utf8))
        XCTAssertEqual(report.state, .online)
        XCTAssertTrue(report.isHealthy)
        XCTAssertTrue(report.allGreen)
        XCTAssertTrue(report.gatewayOK)
        XCTAssertEqual(report.webuiOK, true)
        XCTAssertEqual(report.statusText, "running")
        XCTAssertEqual(report.model, "ollama:gemma4:12b")
    }

    func testHandlesDegradedAndOfflineResponses() {
        let degraded = GatewayHealth.parse(statusCode: 200, data: Data(#"{"ok": false, "status": "degraded", "all_green": false}"#.utf8))
        XCTAssertEqual(degraded.state, .degraded)
        XCTAssertFalse(degraded.isHealthy)

        let http503 = GatewayHealth.parse(statusCode: 503, data: Data())
        XCTAssertEqual(http503.state, .offline)
        XCTAssertEqual(http503.statusText, "http_503")

        let unreachable = GatewayHealth.parse(statusCode: nil, data: nil)
        XCTAssertEqual(unreachable, .offline)
    }

    func testLiveTasksDisablesPollingOnMissingLegacyEndpoint() {
        XCTAssertTrue(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 404))
        XCTAssertTrue(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 405))
        XCTAssertTrue(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 501))
        XCTAssertFalse(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 200))
        XCTAssertFalse(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 500))
        XCTAssertFalse(LiveTasksResponsePolicy.shouldDisablePolling(statusCode: 503))
    }

    func testStackRestartArgumentsAndMinimalServiceDecode() throws {
        XCTAssertEqual(StackCLI.restartArguments, ["stack", "restart", "--json"])
        let minimal = #"{"ok": true, "services": [{"id": "gateway", "state": "running", "ready": true, "port": 33418}]}"#
        let reply = try StackCLI.decodeAction(Data(minimal.utf8))
        XCTAssertTrue(reply.ok)
        let svc = try XCTUnwrap(reply.services?.first)
        XCTAssertEqual(svc.id, "gateway")
        XCTAssertEqual(svc.name, "gateway")
        XCTAssertEqual(svc.label, "gateway")
        XCTAssertTrue(svc.ready)
        XCTAssertTrue(svc.configured)
        XCTAssertFalse(svc.stale)
    }
}
