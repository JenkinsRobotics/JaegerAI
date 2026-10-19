import XCTest
@testable import JaegerAI

final class WebUIEndpointTests: XCTestCase {
    func testMultilineCLIOutputChoosesBareBrowserURL() {
        XCTAssertEqual(WebUIEndpoint.parseAddress("http://127.0.0.1:1234/\nremote (Tailscale Serve): https://machine.example/\n")?.absoluteString, "http://127.0.0.1:1234/")
        XCTAssertEqual(WebUIEndpoint.parseAddress("Starting lookup…\n\n https://machine.example/ \nDiagnostic: ready\n")?.host, "machine.example")
    }
    func testInvalidOrAmbiguousOutputFailsClosed() {
        for output in ["", "not a URL", "remote (Tailscale Serve): https://machine.example", "file:///tmp/test", "http:///missing-host", "http://user:secret@host/", "https://one.example\nhttps://two.example"] {
            XCTAssertNil(WebUIEndpoint.parseAddress(output), output)
        }
    }
}
