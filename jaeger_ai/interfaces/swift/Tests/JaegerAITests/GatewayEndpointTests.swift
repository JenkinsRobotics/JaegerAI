import XCTest
@testable import JaegerAI

/// The Gateway moved to the contract's current port; the legacy port is a
/// fallback only while installed services still run there.
final class GatewayEndpointTests: XCTestCase {
    func testExplicitURLWinsWithoutProbing() {
        var probed = false
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_URL": "http://example.local:1234"]) { _ in
            probed = true; return false
        }
        XCTAssertEqual(url.absoluteString, "http://example.local:1234")
        XCTAssertFalse(probed)
    }

    func testCurrentPortFirst() {
        let url = GatewayEndpoint.resolve([:]) { $0 == GatewayEndpoint.currentURL }
        XCTAssertEqual(url, GatewayEndpoint.currentURL)
    }

    func testLegacyFallbackWhenCurrentIsDown() {
        let url = GatewayEndpoint.resolve([:]) { $0 == GatewayEndpoint.legacyURL }
        XCTAssertEqual(url, GatewayEndpoint.legacyURL)
    }

    func testNothingAnsweringKeepsCurrent() {
        XCTAssertEqual(GatewayEndpoint.resolve([:]) { _ in false }, GatewayEndpoint.currentURL)
    }

    func testFallbackCanBeTurnedOff() {
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_LEGACY_FALLBACK": "0"]) {
            $0 == GatewayEndpoint.legacyURL
        }
        XCTAssertEqual(url, GatewayEndpoint.currentURL)
    }

    func testPortOverride() {
        let url = GatewayEndpoint.resolve(["JAEGER_GATEWAY_PORT": "\(GatewayEndpoint.legacyPort)"]) { _ in false }
        XCTAssertEqual(url, GatewayEndpoint.legacyURL)
    }
}
