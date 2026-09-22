import XCTest
@testable import HermesMobile

final class ChatHapticsTests: XCTestCase {
    @MainActor
    func testHapticsRespectEnabledSetting() {
        var feedback: [ChatHapticFeedback] = []

        ChatHaptics.messageSent(isEnabled: false) { feedback.append($0) }
        ChatHaptics.assistantResponseCompleted(isEnabled: false) { feedback.append($0) }
        ChatHaptics.streamCancelled(isEnabled: false) { feedback.append($0) }
        ChatHaptics.approvalSubmitted(.deny, isEnabled: false) { feedback.append($0) }
        ChatHaptics.clarificationSubmitted(isEnabled: false) { feedback.append($0) }
        ChatHaptics.configurationSelected(isEnabled: false) { feedback.append($0) }
        ChatHaptics.destructiveConfirmationAccepted(isEnabled: false) { feedback.append($0) }

        XCTAssertTrue(feedback.isEmpty)
    }

    @MainActor
    func testChatDecisionHapticLanguage() {
        var feedback: [ChatHapticFeedback] = []

        ChatHaptics.messageSent(isEnabled: true) { feedback.append($0) }
        ChatHaptics.assistantResponseCompleted(isEnabled: true) { feedback.append($0) }
        ChatHaptics.streamCancelled(isEnabled: true) { feedback.append($0) }
        ChatHaptics.approvalSubmitted(.once, isEnabled: true) { feedback.append($0) }
        ChatHaptics.approvalSubmitted(.session, isEnabled: true) { feedback.append($0) }
        ChatHaptics.approvalSubmitted(.always, isEnabled: true) { feedback.append($0) }
        ChatHaptics.approvalSubmitted(.deny, isEnabled: true) { feedback.append($0) }
        ChatHaptics.approvalBypassEnabled(isEnabled: true) { feedback.append($0) }
        ChatHaptics.clarificationSubmitted(isEnabled: true) { feedback.append($0) }
        ChatHaptics.configurationSelected(isEnabled: true) { feedback.append($0) }
        ChatHaptics.destructiveConfirmationAccepted(isEnabled: true) { feedback.append($0) }

        XCTAssertEqual(feedback, [
            .lightImpact,
            .success,
            .mediumImpact,
            .lightImpact,
            .lightImpact,
            .lightImpact,
            .warning,
            .warning,
            .selection,
            .selection,
            .warning
        ])
    }

    @MainActor
    func testConfigurationNoOpSelectionsDoNotReportSuccess() async {
        let viewModel = ChatViewModel(
            session: SessionSummary(
                sessionId: "session-1",
                workspace: "/tmp/project",
                model: "gpt-5",
                modelProvider: "openai",
                profile: "work"
            ),
            server: URL(string: "https://example.test")!
        )

        let didSelectCurrentModel = await viewModel.selectComposerModel(ModelCatalogOption(
            id: "gpt-5",
            displayName: "GPT-5",
            providerID: "openai"
        ))
        let didSelectCurrentWorkspace = await viewModel.selectWorkspacePath(" /tmp/project ")
        let didSelectCurrentProfile = await viewModel.switchProfile(
            ProfileSummary(
                name: "work",
                path: nil,
                isDefault: nil,
                isActive: true,
                gatewayRunning: nil,
                model: nil,
                provider: nil,
                hasEnv: nil,
                skillCount: nil
            ),
            startNewSession: false
        )

        XCTAssertFalse(didSelectCurrentModel)
        XCTAssertFalse(didSelectCurrentWorkspace)
        XCTAssertNil(didSelectCurrentProfile)
    }
}
