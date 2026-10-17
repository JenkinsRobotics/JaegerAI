// Stack mode + dev/test stack config (production `jaeger stack up/down` is never run by tests).
import XCTest
@testable import JaegerShellCore

final class DevStackTests: XCTestCase {
    let home = "/Users/t"
    let root = "/Users/t/GitHub/JaegerAI-worktrees/ui-rebuild"
    var base: [String: String] { ["JAEGER_SHELL_STACK_MODE": "dev", "JAEGER_SHELL_DEV_ROOT": root] }

    private func resolve(_ env: [String: String], dev: Bool = true) -> Result<DevStackConfig, DevStackError> {
        DevStackConfig.resolve(env: env, home: home, isDevBuild: dev,
                               fileExists: { $0 == self.root + "/jaeger_ai/core/gateway/server.py" },
                               isExecutable: { _ in true })
    }

    func testModeIsProductionUnlessDevBuildAndFlag() {
        XCTAssertEqual(StackMode.resolve(env: [:], isDevBuild: true), .production)
        XCTAssertEqual(StackMode.resolve(env: ["JAEGER_SHELL_STACK_MODE": "dev"], isDevBuild: false), .production)
        XCTAssertEqual(StackMode.resolve(env: ["JAEGER_SHELL_STACK_MODE": " DEV "], isDevBuild: true), .dev)
        XCTAssertEqual(StackMode.resolve(env: ["JAEGER_SHELL_STACK_MODE": "prod"], isDevBuild: true), .production)
    }

    func testDefaultsAndGatewayCommandMatchTestServers() throws {
        let c = try resolve(base).get()
        XCTAssertEqual(c.gatewayPort, 43428)
        XCTAssertEqual(c.uiPort, 18800)
        XCTAssertEqual(c.stateDir, "/Users/t/.cache/jaeger/ui-rebuild-test-state")
        let g = c.gatewayCommand(home: home)
        XCTAssertEqual(g.executable, "/Users/t/.jaeger/venv/bin/python")
        XCTAssertEqual(g.arguments, ["-m", "jaeger_ai.core.gateway.server", "--host", "127.0.0.1", "--port", "43428"])
        XCTAssertEqual(g.environment["JAEGER_TEST_HEADLESS"], "1")
        XCTAssertEqual(g.environment["JAEGER_STATE_DIR"], c.stateDir)
        XCTAssertEqual(g.environment["PYTHONPATH"], root)
        XCTAssertEqual(g.workingDirectory, root)
        XCTAssertFalse(g.environment.values.contains { $0.contains("0.0.0.0") })
        XCTAssertNil(g.environment["HERMES_WEBUI_HOST"])   // minimal env: nothing inherited
        let u = c.uiCommand(home: home)
        XCTAssertEqual(u.environment["JAEGER_WEBUI_URL"], "http://127.0.0.1:43428")
        XCTAssertEqual(u.environment["JAEGER_UI_PROXY_TARGET"], "http://127.0.0.1:43428")
        XCTAssertTrue(u.arguments.contains("preview") && u.arguments.contains("127.0.0.1") && u.arguments.contains("--strictPort"))
        XCTAssertEqual(u.workingDirectory, root + "/jaeger_ai/interfaces/ui")
    }

    func testRefusals() {
        XCTAssertEqual(resolve(base, dev: false).failureValue, .notDevMode)
        XCTAssertEqual(resolve(["JAEGER_SHELL_STACK_MODE": "dev"]).failureValue, .missingRoot)
        XCTAssertEqual(resolve(["JAEGER_SHELL_STACK_MODE": "dev", "JAEGER_SHELL_DEV_ROOT": "/tmp/x"]).failureValue, .notAWorktree("/tmp/x"))
        for reserved in [43418, 33418, 8790, 8793] {
            XCTAssertEqual(resolve(base.merging(["JAEGER_SHELL_DEV_GATEWAY_PORT": String(reserved)]) { $1 }).failureValue, .reservedPort(reserved))
        }
        XCTAssertEqual(resolve(base.merging(["JAEGER_SHELL_DEV_GATEWAY_PORT": "80"]) { $1 }).failureValue, .badPort("80"))
        XCTAssertNotNil(resolve(base.merging(["JAEGER_SHELL_DEV_UI_PORT": "43428"]) { $1 }).failureValue)
        for unsafe in ["/Users/t/.jaeger", "/Users/t/.jaeger/state", "/Users/t"] {
            XCTAssertEqual(resolve(base.merging(["JAEGER_SHELL_DEV_STATE_DIR": unsafe]) { $1 }).failureValue, .unsafeStateDir(unsafe))
        }
    }

    func testProductionArgumentsUpAndDown() {
        XCTAssertEqual(StackCLI.upArguments, ["stack", "up", "--json"])
        XCTAssertEqual(StackCLI.downArguments, ["stack", "down", "--json"])
    }

    func testBridgeRoutesStackCommands() {
        func cmd(_ t: String) -> BridgeCommand? {
            BridgeCommand.from(BridgeRequest(id: "1", type: t, payload: [:]), home: home, fileExists: { _ in false }).successValue
        }
        XCTAssertEqual(cmd("stack.start"), .stackStart)
        XCTAssertEqual(cmd("stack.stop"), .stackStop)
        XCTAssertEqual(cmd("stack.status"), .stackStatus)
    }
}
