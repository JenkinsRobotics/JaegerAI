import XCTest
@testable import JaegerShellCore

final class JaegerDeepLinkTests: XCTestCase {
    func testOriginalConversationAndInboxNavigationOnly() throws {
        XCTAssertEqual(JaegerDeepLink.destination(try XCTUnwrap(URL(string: "jaeger://conversation/agent-native%3Abuilder"))), .conversation("agent-native:builder"))
        XCTAssertEqual(JaegerDeepLink.destination(try XCTUnwrap(URL(string: "jaeger://notifications"))), .inbox)
        for raw in [
            "https://example.com/conversation/owned", "file:///owned", "jaeger://conversation/owned?run=tool",
            "jaeger://conversation/owned#approve", "jaeger://user:secret@conversation/owned", "jaeger://conversation:80/owned",
            "jaeger://conversation/owned/extra", "jaeger://conversation/..", "jaeger://conversation/%2Fother",
            "jaeger://conversation/%252Fother", "jaeger://conversation/owned%0Aother", "jaeger://notifications/extra",
            "jaeger://run/owned", "jaeger://conversation/", "jaeger://conversation/" + String(repeating: "x", count: 257)
        ] { XCTAssertNil(JaegerDeepLink.destination(try XCTUnwrap(URL(string: raw))), raw) }
    }
    func testColdLinkUsesExistingReadyAckMailbox() throws {
        let mailbox = NotificationNavigationMailbox()
        let destination = try XCTUnwrap(JaegerDeepLink.destination(try XCTUnwrap(URL(string: "jaeger://conversation/owned-home"))))
        mailbox.receive(destination)
        let id = try XCTUnwrap(mailbox.payload?["id"] as? String)
        XCTAssertEqual(mailbox.payload?["destination"] as? [String: String], ["target": "conversation", "session_id": "owned-home"])
        XCTAssertEqual(mailbox.payload?["id"] as? String, id) // remains while page/registry not ready
        XCTAssertTrue(mailbox.acknowledge(id))
        XCTAssertNil(mailbox.payload)
    }
}
