import XCTest
@testable import HermesMobile

final class SessionHapticsTests: XCTestCase {
    @MainActor
    func testHapticsRespectEnabledSetting() {
        var feedback: [SessionHapticFeedback] = []

        SessionHaptics.sessionCreated(isEnabled: false) { feedback.append($0) }
        SessionHaptics.pinStateChanged(isEnabled: false) { feedback.append($0) }
        SessionHaptics.archiveStateChanged(isEnabled: false) { feedback.append($0) }
        SessionHaptics.sessionDeleted(isEnabled: false) { feedback.append($0) }
        SessionHaptics.sessionRenamed(isEnabled: false) { feedback.append($0) }

        XCTAssertTrue(feedback.isEmpty)
    }

    @MainActor
    func testSessionActionHapticLanguage() {
        var feedback: [SessionHapticFeedback] = []

        SessionHaptics.sessionCreated(isEnabled: true) { feedback.append($0) }
        SessionHaptics.pinStateChanged(isEnabled: true) { feedback.append($0) }
        SessionHaptics.archiveStateChanged(isEnabled: true) { feedback.append($0) }
        SessionHaptics.sessionDeleted(isEnabled: true) { feedback.append($0) }
        SessionHaptics.sessionRenamed(isEnabled: true) { feedback.append($0) }

        XCTAssertEqual(feedback, [
            .lightImpact,
            .lightImpact,
            .lightImpact,
            .warning,
            .selection
        ])
    }
}
