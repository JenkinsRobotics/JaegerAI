import XCTest
@testable import JaegerShellCore
final class ComputerSettingsTests: XCTestCase {
    func testStatusAndFixedNavigationNeverAcceptGrantOrArbitraryURL() {
        func command(_ type: String, _ payload: [String: Any]) -> Result<BridgeCommand, BridgeError> {
            BridgeCommand.from(BridgeRequest(id: "owned", type: type, payload: payload), home: "/owned", fileExists: { _ in false })
        }
        XCTAssertEqual(command("computer.status", [:]).successValue, .computerStatus)
        XCTAssertNotNil(command("computer.status", ["grant": true]).failureValue)
        XCTAssertEqual(command("computer.settings", ["target": "accessibility"]).successValue, .computerSettings(.accessibility))
        XCTAssertNotNil(command("computer.settings", ["target": "accessibility", "grant": true]).failureValue)
        XCTAssertNotNil(command("computer.settings", ["target": "https://example.com/"]).failureValue)
        XCTAssertEqual(ComputerSettingsTarget.screenRecording.url.scheme, "x-apple.systempreferences")
    }
}
