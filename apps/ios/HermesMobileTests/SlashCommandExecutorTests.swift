import XCTest
@testable import HermesMobile

final class SlashCommandExecutorTests: XCTestCase {
    func testParseClearWithoutArgs() {
        let parsed = SlashCommandExecutor.parse("/clear")
        XCTAssertEqual(parsed?.command?.name, "clear")
        XCTAssertEqual(parsed?.name, "clear")
        XCTAssertEqual(parsed?.args, "")
    }

    func testParseHelpWithoutArgs() {
        let parsed = SlashCommandExecutor.parse("/help")
        XCTAssertEqual(parsed?.command?.name, "help")
        XCTAssertEqual(parsed?.name, "help")
        XCTAssertEqual(parsed?.args, "")
    }

    func testParseModelWithArgs() {
        let parsed = SlashCommandExecutor.parse("/model gpt-4")
        XCTAssertEqual(parsed?.command?.name, "model")
        XCTAssertEqual(parsed?.name, "model")
        XCTAssertEqual(parsed?.args, "gpt-4")
    }

    func testParseBranchWithTitle() {
        let parsed = SlashCommandExecutor.parse("/branch Planning Copy")
        XCTAssertEqual(parsed?.command?.name, "branch")
        XCTAssertEqual(parsed?.name, "branch")
        XCTAssertEqual(parsed?.args, "Planning Copy")

        let alias = SlashCommandExecutor.parse("/fork Planning Copy")
        XCTAssertEqual(alias?.command?.name, "fork")
        XCTAssertEqual(alias?.command?.handler, .serverSide(.branch))
        XCTAssertEqual(alias?.name, "fork")
        XCTAssertEqual(alias?.args, "Planning Copy")
    }

    func testParseUndoWithoutArgs() {
        let parsed = SlashCommandExecutor.parse("/undo")
        XCTAssertEqual(parsed?.command?.name, "undo")
        XCTAssertEqual(parsed?.name, "undo")
        XCTAssertEqual(parsed?.args, "")
    }

    func testParseRetryWithoutArgs() {
        let parsed = SlashCommandExecutor.parse("/retry")
        XCTAssertEqual(parsed?.command?.name, "retry")
        XCTAssertEqual(parsed?.name, "retry")
        XCTAssertEqual(parsed?.args, "")
    }

    func testParseCompressWithFocus() {
        let parsed = SlashCommandExecutor.parse("/compress architecture notes")
        XCTAssertEqual(parsed?.command?.name, "compress")
        XCTAssertEqual(parsed?.name, "compress")
        XCTAssertEqual(parsed?.args, "architecture notes")

        let alias = SlashCommandExecutor.parse("/compact architecture notes")
        XCTAssertEqual(alias?.command?.name, "compact")
        XCTAssertEqual(alias?.command?.handler, .serverSide(.compress))
        XCTAssertEqual(alias?.name, "compact")
        XCTAssertEqual(alias?.args, "architecture notes")
    }

    func testParseSkillsWithQuery() {
        let parsed = SlashCommandExecutor.parse("/skills claude")
        XCTAssertEqual(parsed?.command?.name, "skills")
        XCTAssertEqual(parsed?.name, "skills")
        XCTAssertEqual(parsed?.args, "claude")
    }

    func testParseGoalWithActionOrText() {
        let status = SlashCommandExecutor.parse("/goal status")
        XCTAssertEqual(status?.command?.name, "goal")
        XCTAssertEqual(status?.command?.handler, .serverSide(.goal))
        XCTAssertEqual(status?.name, "goal")
        XCTAssertEqual(status?.args, "status")

        let text = SlashCommandExecutor.parse("/goal ship the next build")
        XCTAssertEqual(text?.command?.name, "goal")
        XCTAssertEqual(text?.args, "ship the next build")
    }

    func testParseUnknownCommand() {
        let parsed = SlashCommandExecutor.parse("/unknown")
        XCTAssertNil(parsed?.command)
        XCTAssertEqual(parsed?.name, "unknown")
        XCTAssertEqual(parsed?.args, "")
    }

    func testParseResumeAsUnknownCommandName() {
        let parsed = SlashCommandExecutor.parse("/resume")
        XCTAssertNil(parsed?.command)
        XCTAssertEqual(parsed?.name, "resume")
        XCTAssertEqual(parsed?.args, "")
    }

    func testUnsupportedCommandFallback() {
        XCTAssertEqual(
            SlashCommandExecutor.unsupportedMessage(for: "terminal"),
            "Terminal is not available in the mobile app."
        )
        XCTAssertEqual(
            SlashCommandExecutor.unsupportedMessage(for: "not-real"),
            "This command is not available in the mobile app."
        )
    }

    func testParseBusyInputCommands() {
        for name in ["queue", "steer", "interrupt", "status", "btw", "background", "bg", "goal"] {
            let parsed = SlashCommandExecutor.parse("/\(name)")
            XCTAssertEqual(parsed?.command?.name, name)
            XCTAssertEqual(parsed?.name, name)
            XCTAssertEqual(parsed?.args, "")
        }

        XCTAssertEqual(SlashCommandExecutor.parse("/queue follow up")?.command?.handler, .serverSide(.queue))
        XCTAssertEqual(SlashCommandExecutor.parse("/steer prefer tests")?.command?.handler, .serverSide(.steer))
        XCTAssertEqual(SlashCommandExecutor.parse("/interrupt start over")?.command?.handler, .serverSide(.interrupt))
        XCTAssertEqual(SlashCommandExecutor.parse("/status")?.command?.handler, .serverSide(.status))
        XCTAssertEqual(SlashCommandExecutor.parse("/btw explain this")?.command?.handler, .serverSide(.btw))
        XCTAssertEqual(SlashCommandExecutor.parse("/background audit this")?.command?.handler, .serverSide(.background))
        XCTAssertEqual(SlashCommandExecutor.parse("/bg audit this")?.command?.handler, .serverSide(.background))
    }

    func testEmptyArgsHandlingTrimsWhitespace() {
        let parsed = SlashCommandExecutor.parse("  /model   ")
        XCTAssertEqual(parsed?.command?.name, "model")
        XCTAssertEqual(parsed?.args, "")
    }

    func testNonSlashTextReturnsNil() {
        XCTAssertNil(SlashCommandExecutor.parse("hello"))
    }
}
