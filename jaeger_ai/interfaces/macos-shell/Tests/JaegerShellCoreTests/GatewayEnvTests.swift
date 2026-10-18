// M1: JAEGER_GATEWAY_URL is read for the gateway probe, loopback-validated like the WebUI override.
import XCTest
@testable import JaegerShellCore

final class GatewayEnvTests: XCTestCase {
    func testShellKeyWinsOverShared() {
        let env = ["JAEGER_SHELL_GATEWAY_URL": "http://127.0.0.1:43428/", "JAEGER_GATEWAY_URL": "http://127.0.0.1:33418"]
        XCTAssertEqual(StartURL.gatewayEnvValue(env), "http://127.0.0.1:43428/")
    }

    func testSharedKeyUsedWhenShellKeyMissingOrBlank() {
        XCTAssertEqual(StartURL.gatewayEnvValue(["JAEGER_GATEWAY_URL": " http://127.0.0.1:43428 "]), "http://127.0.0.1:43428")
        XCTAssertEqual(StartURL.gatewayEnvValue(["JAEGER_SHELL_GATEWAY_URL": "  ", "JAEGER_GATEWAY_URL": "http://127.0.0.1:43428"]),
                       "http://127.0.0.1:43428")
        XCTAssertNil(StartURL.gatewayEnvValue([:]))
    }

    func testSharedKeyIsLoopbackValidated() {
        let ok = StartURL.resolve(fallback: StartURL.defaultGateway,
                                  envValue: StartURL.gatewayEnvValue(["JAEGER_GATEWAY_URL": "http://127.0.0.1:43428"]),
                                  defaultsValue: nil, isDevBuild: true)
        XCTAssertEqual(ok.origin.port, 43428)
        for bad in ["http://0.0.0.0:43428", "http://192.168.1.5:33418", "https://127.0.0.1:43428", "http://localhost:43428",
                    "http://user:pw@127.0.0.1:43428", "http://127.0.0.1:43428/v1"] {
            let r = StartURL.resolve(fallback: StartURL.defaultGateway,
                                     envValue: StartURL.gatewayEnvValue(["JAEGER_GATEWAY_URL": bad]),
                                     defaultsValue: nil, isDevBuild: true)
            XCTAssertEqual(r.origin, StartURL.defaultGateway, bad)
            XCTAssertEqual(r.rejected, bad, bad)
        }
    }

    func testSharedKeyIgnoredInProductionBuild() {
        let r = StartURL.resolve(fallback: StartURL.defaultGateway,
                                 envValue: StartURL.gatewayEnvValue(["JAEGER_GATEWAY_URL": "http://127.0.0.1:43428"]),
                                 defaultsValue: nil, isDevBuild: false)
        XCTAssertEqual(r.origin, StartURL.defaultGateway)
    }
}
