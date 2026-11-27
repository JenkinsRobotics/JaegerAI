import XCTest
@testable import JaegerShellCore

final class StartURLTests: XCTestCase {
    func testDefaultIsLoopback8790() {
        let r = StartURL.resolve(fallback: StartURL.defaultWebUI, envValue: nil, defaultsValue: nil, isDevBuild: true)
        XCTAssertEqual(r.url.absoluteString, "http://127.0.0.1:8790/?host=macos")
        XCTAssertNil(r.override); XCTAssertNil(r.rejected)
    }
    func testAcceptsLoopbackOverride() {
        let r = StartURL.resolve(fallback: StartURL.defaultWebUI, envValue: "http://127.0.0.1:18790/", defaultsValue: nil, isDevBuild: true)
        XCTAssertEqual(r.url.absoluteString, "http://127.0.0.1:18790/?host=macos")
        XCTAssertEqual(r.override, "http://127.0.0.1:18790/")
    }
    func testEnvWinsOverDefaults() {
        let r = StartURL.resolve(fallback: StartURL.defaultWebUI, envValue: "http://127.0.0.1:18790", defaultsValue: "http://127.0.0.1:28790/", isDevBuild: true)
        XCTAssertEqual(r.origin.port, 18790)
    }
    func testRejects() {
        for raw in ["http://localhost:18790/", "http://100.74.2.15:8790/", "https://127.0.0.1:18790/",
                    "http://127.0.0.1/", "http://u:p@127.0.0.1:18790/", "http://127.0.0.1:80/",
                    "http://127.0.0.1:18790/x", "http://[::1]:18790/", "file:///etc/hosts", "garbage"] {
            let r = StartURL.resolve(fallback: StartURL.defaultWebUI, envValue: raw, defaultsValue: nil, isDevBuild: true)
            XCTAssertEqual(r.origin, StartURL.defaultWebUI, raw)
            XCTAssertEqual(r.rejected, raw, raw)
        }
    }
    func testProductionBuildIgnoresOverride() {
        let r = StartURL.resolve(fallback: StartURL.defaultWebUI, envValue: "http://127.0.0.1:18790/", defaultsValue: nil, isDevBuild: false)
        XCTAssertEqual(r.origin, StartURL.defaultWebUI)
        XCTAssertEqual(r.rejected, "http://127.0.0.1:18790/")
    }
}
