import XCTest
@testable import JaegerShellCore

final class HotkeyConfigTests: XCTestCase {
    func testCtrlOptSpace() {
        let r = HotkeyConfig.resolve("ctrl-opt-space")
        XCTAssertEqual(r.spec, HotkeyConfig.controlOptionSpace)
        XCTAssertEqual(r.spec.modifiers, 6144)
        XCTAssertEqual(r.spec.keyCode, 49)
        XCTAssertNil(r.note)
    }
    func testMissingFallsBackToOptionSpace() {
        let r = HotkeyConfig.resolve(nil)
        XCTAssertEqual(r.spec, HotkeyConfig.optionSpace)
        XCTAssertNotNil(r.note)
    }
    func testUnknownFallsBackToOptionSpace() {
        let r = HotkeyConfig.resolve("cmd-k")
        XCTAssertEqual(r.spec, HotkeyConfig.optionSpace)
        XCTAssertTrue(r.note?.contains("cmd-k") ?? false)
    }
    func testOptSpace() {
        XCTAssertEqual(HotkeyConfig.resolve(" Opt-Space ").spec, HotkeyConfig.optionSpace)
    }
}
