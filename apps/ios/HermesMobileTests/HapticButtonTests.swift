import XCTest
@testable import HermesMobile

final class HapticButtonTests: XCTestCase {
    @MainActor
    func testTapHapticsRespectEnabledSetting() {
        var feedback: [HapticButtonFeedbackStyle] = []

        HapticButtonHaptics.tap(style: .light, isEnabled: false) { feedback.append($0) }
        HapticButtonHaptics.tap(style: .medium, isEnabled: false) { feedback.append($0) }

        XCTAssertTrue(feedback.isEmpty)
    }

    @MainActor
    func testTapHapticsSupportLightAndMediumStyles() {
        var feedback: [HapticButtonFeedbackStyle] = []

        HapticButtonHaptics.tap(isEnabled: true) { feedback.append($0) }
        HapticButtonHaptics.tap(style: .medium, isEnabled: true) { feedback.append($0) }

        XCTAssertEqual(feedback, [.light, .medium])
    }
}
