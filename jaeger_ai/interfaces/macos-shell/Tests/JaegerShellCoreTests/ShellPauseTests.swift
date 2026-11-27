import XCTest
@testable import JaegerShellCore

final class ShellPauseTests: XCTestCase {
    func testToggleIgnoresFocus() {
        XCTAssertEqual(WindowToggle.action(windowVisible: true), .hide)
        XCTAssertEqual(WindowToggle.action(windowVisible: false), .show)
    }
    func testPauseState() {
        var s = ShellPauseState()
        XCTAssertFalse(s.paused); XCTAssertEqual(s.menuTitle, "Pause Jaeger Shell")
        XCTAssertTrue(s.set(true)); XCTAssertFalse(s.set(true))
        XCTAssertEqual(s.menuTitle, "Resume Jaeger Shell")
        XCTAssertTrue(s.statusTitle.contains("paused"))
        XCTAssertTrue(s.set(false)); XCTAssertEqual(s.statusTitle, "Shell: active")
    }
}
