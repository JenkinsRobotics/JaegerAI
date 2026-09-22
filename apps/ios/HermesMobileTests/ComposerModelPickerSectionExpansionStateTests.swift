import XCTest
@testable import HermesMobile

final class ComposerModelPickerSectionExpansionStateTests: XCTestCase {
    func testSectionsStartCollapsedWhenSearchIsEmpty() {
        let state = ComposerModelPickerSectionExpansionState()

        XCTAssertFalse(state.isExpanded(groupID: "openai"))
    }

    func testManualExpansionPersistsWhileSearchIsEmpty() {
        var state = ComposerModelPickerSectionExpansionState()

        state.setExpanded(true, groupID: "openai")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))

        state.setExpanded(false, groupID: "openai")

        XCTAssertFalse(state.isExpanded(groupID: "openai"))
    }

    func testSearchAutoExpandsAllSections() {
        var state = ComposerModelPickerSectionExpansionState()

        state.updateSearchText("gpt")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertTrue(state.isExpanded(groupID: "anthropic"))
    }

    func testManualCollapseDuringSearchDoesNotChangeEmptySearchState() {
        var state = ComposerModelPickerSectionExpansionState()
        state.setExpanded(true, groupID: "openai")
        state.updateSearchText("gpt")

        state.setExpanded(false, groupID: "openai")

        XCTAssertFalse(state.isExpanded(groupID: "openai"))

        state.updateSearchText("")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
    }

    func testChangingSearchQueryReexpandsCollapsedSearchSections() {
        var state = ComposerModelPickerSectionExpansionState()
        state.updateSearchText("gpt")
        state.setExpanded(false, groupID: "openai")
        state.setExpanded(false, groupID: "anthropic")

        XCTAssertFalse(state.isExpanded(groupID: "openai"))
        XCTAssertFalse(state.isExpanded(groupID: "anthropic"))

        state.updateSearchText("gpt 5")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertTrue(state.isExpanded(groupID: "anthropic"))
    }

    func testGroupExpansionStateIsIndependentAcrossSearchBoundary() {
        var state = ComposerModelPickerSectionExpansionState()
        state.setExpanded(true, groupID: "openai")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertFalse(state.isExpanded(groupID: "anthropic"))

        state.updateSearchText("claude")
        state.setExpanded(false, groupID: "anthropic")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertFalse(state.isExpanded(groupID: "anthropic"))

        state.updateSearchText("")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertFalse(state.isExpanded(groupID: "anthropic"))
    }

    func testWhitespaceOnlySearchUsesEmptySearchState() {
        var state = ComposerModelPickerSectionExpansionState()
        state.setExpanded(true, groupID: "openai")
        state.updateSearchText("gpt")
        state.setExpanded(false, groupID: "openai")

        XCTAssertFalse(state.isExpanded(groupID: "openai"))

        state.updateSearchText("   ")

        XCTAssertTrue(state.isExpanded(groupID: "openai"))
        XCTAssertFalse(state.isExpanded(groupID: "anthropic"))
    }
}
