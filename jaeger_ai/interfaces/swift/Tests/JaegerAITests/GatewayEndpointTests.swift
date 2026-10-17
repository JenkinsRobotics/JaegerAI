import XCTest
@testable import JaegerAI

/// The Gateway lives on the contract's port; the old port is retired, so
/// nothing falls back to it. JAEGER_GATEWAY_URL / JAEGER_GATEWAY_PORT override.
final class GatewayEndpointTests: XCTestCase {
    func testExplicitURLWins() {
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_URL": "http://example.local:1234"]) { _ in false }
        XCTAssertEqual(url.absoluteString, "http://example.local:1234")
    }

    func testDefaultIsTheContractPortWithoutProbing() {
        var probed = false
        let url = GatewayEndpoint.resolve([:]) { _ in probed = true; return false }
        XCTAssertEqual(url, GatewayEndpoint.currentURL)
        XCTAssertEqual(GatewayEndpoint.currentURL.absoluteString, "http://127.0.0.1:33418")
        XCTAssertFalse(probed)
    }

    func testPortOverride() {
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_PORT": "40001"]) { _ in false }
        XCTAssertEqual(url.absoluteString, "http://127.0.0.1:40001")
    }

    func testRetiredFallbackEnvIsIgnored() {
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_LEGACY_FALLBACK": "1"]) { _ in false }
        XCTAssertEqual(url, GatewayEndpoint.currentURL)
    }
}
