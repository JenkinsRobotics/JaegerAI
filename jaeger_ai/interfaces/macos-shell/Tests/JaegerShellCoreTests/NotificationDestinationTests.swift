import XCTest
@testable import JaegerShellCore

final class NotificationDestinationTests: XCTestCase {
    func testOnlyNavigationIdentitiesNotExecutionOrURLs() {
        XCTAssertEqual(NotificationDestination.parse(["target": "notifications"]), .inbox)
        XCTAssertEqual(NotificationDestination.parse(["target": "conversation", "session_id": "agent-native:builder"]), .conversation("agent-native:builder"))
        for bad: [AnyHashable: Any] in [
            ["target": "conversation", "session_id": "https://remote.example"],
            ["target": "conversation", "session_id": "owned", "run": true],
            ["target": "notifications", "approval": "allow"],
            ["target": "conversation", "session_id": ""],
            ["target": "conversation", "session_id": 42]
        ] { XCTAssertNil(NotificationDestination.parse(bad)) }
        XCTAssertEqual(NotificationDestination.conversation("owned-home").payload, ["target": "conversation", "session_id": "owned-home"])
    }
    func testClickSurvivesReadinessAndOnlyItsOwnAckClearsIt() throws {
        let mailbox = NotificationNavigationMailbox()
        let first = UUID(), second = UUID()
        mailbox.receive(.conversation("owned-first"), id: first)
        XCTAssertEqual(mailbox.payload?["id"] as? String, first.uuidString)
        XCTAssertEqual(mailbox.payload?["id"] as? String, first.uuidString) // peek never consumes
        mailbox.receive(.inbox, id: second)
        XCTAssertFalse(mailbox.acknowledge(first.uuidString))
        XCTAssertEqual(mailbox.payload?["id"] as? String, second.uuidString)
        XCTAssertTrue(mailbox.acknowledge(second.uuidString))
        XCTAssertNil(mailbox.payload)
        XCTAssertFalse(mailbox.acknowledge(second.uuidString))
    }

}
