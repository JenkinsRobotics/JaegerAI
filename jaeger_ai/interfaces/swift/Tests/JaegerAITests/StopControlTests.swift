import XCTest
@testable import JaegerAI

final class StopControlTests: XCTestCase {
    func testCancelRequiresExactRequestIdentity() throws {
        XCTAssertEqual(try GatewayClient.cancellationBody(requestID: "specific-request"), ["request_id": "specific-request"])
        XCTAssertThrowsError(try GatewayClient.cancellationBody(requestID: " "))
    }

    func testRecoveredTurnAndUnknownSettlementStayDistinct() throws {
        let data = Data(#"{"session_id":"s","status":"running","latest_request":{"session_id":"s","request_id":"r","status":"running"}}"#.utf8)
        let session = try JSONDecoder().decode(GatewayClient.Session.self, from: data)
        XCTAssertTrue(session.latest_request?.canCancel == true)
        for status in ["cancelling", "execution_unknown", "cancelled"] {
            let request = GatewayClient.RequestState(session_id: "s", request_id: "r", status: status)
            XCTAssertFalse(request.canCancel)
            XCTAssertEqual(request.isActive, status == "cancelling")
        }
        XCTAssertTrue(GatewayClient.RequestState(session_id: "s", request_id: "r", status: "execution_unknown").stopLabel.contains("unknown"))
    }

    func testStopPreservesAlreadyStreamedText() {
        XCTAssertEqual(ChatViewModel.settledReplyText(partial: "Work so far", reply: "cancelled", interrupted: true), "Work so far")
        XCTAssertEqual(ChatViewModel.settledReplyText(partial: "Partial", reply: "Final", interrupted: false), "Final")
    }
}
