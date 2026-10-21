import XCTest
@testable import JaegerShellCore
final class ClipboardPreviewTests: XCTestCase {
    func testLiteralOwnedTextAndUTF8ByteBoundWithoutClipboardAccess() {
        let literal = ClipboardPreview.project("<script>owned literal</script>")
        XCTAssertEqual(literal["state"] as? String, "text_available")
        XCTAssertEqual(literal["text"] as? String, "<script>owned literal</script>")
        XCTAssertEqual(ClipboardPreview.project(nil)["state"] as? String, "no_text_or_access_unavailable")
        let oversized = ClipboardPreview.project(String(repeating: "🌻", count: 25_001))
        XCTAssertEqual(oversized["state"] as? String, "over_limit")
        XCTAssertNil(oversized["text"])
    }
    func testReadHasNoAuthorityOrActionArguments() {
        func command(_ payload: [String: Any]) -> Result<BridgeCommand, BridgeError> {
            BridgeCommand.from(BridgeRequest(id: "owned", type: "clipboard.read", payload: payload), home: "/owned", fileExists: { _ in false })
        }
        XCTAssertEqual(command([:]).successValue, .clipboardRead)
        XCTAssertNotNil(command(["allow": true, "run": "tool"]).failureValue)
    }
}
