import XCTest
@testable import JaegerAI

final class NativePanelTests: XCTestCase {
    func testSchedulerTruthAndUnavailableAreNotSampleFallbacks() throws {
        let decoder = JSONDecoder()
        let jobs = try decoder.decode(CronCatalog.self, from: Data(#"{"jobs":[{"id":"job1","name":"Real job","enabled":false,"last_status":"error"}],"other_profile_count":2}"#.utf8))
        XCTAssertEqual(jobs.jobs.first?.last_status, "error")
        XCTAssertEqual(jobs.jobs.first?.enabled, false)
        XCTAssertEqual(jobs.other_profile_count, 2)
        let absent = try decoder.decode(CronCatalog.self, from: Data(#"{"jobs":[],"cron_unavailable":true}"#.utf8))
        XCTAssertTrue(absent.cron_unavailable == true)
        XCTAssertThrowsError(try decoder.decode(CronCatalog.self, from: Data(#"{"error":"denied"}"#.utf8)))
    }
    func testBoardSnapshotPreservesBackendStatusAndReadOnly() throws {
        let board = try JSONDecoder().decode(BoardSnapshot.self, from: Data(#"{"columns":[{"name":"blocked","tasks":[{"id":"t1","title":"Actual task","status":"blocked","assignee":"jaeger"}]},{"name":"done","tasks":[]}],"read_only":true}"#.utf8))
        XCTAssertEqual(board.columns.first?.tasks.first?.status, "blocked")
        XCTAssertTrue(board.columns[1].tasks.isEmpty)
        XCTAssertTrue(board.read_only == true)
        XCTAssertThrowsError(try JSONDecoder().decode(BoardSnapshot.self, from: Data(#"{"error":"missing backend"}"#.utf8)))
    }
    func testSessionCookiesStayWithinHostPathAndTransport() throws {
        let session = try XCTUnwrap(HTTPCookie(properties: [.domain:"localhost", .path:"/api", .name:"session", .value:"fixture", .secure:"TRUE"]))
        XCTAssertEqual(NativePanelClient.matchingCookies([session], for: URL(string:"https://localhost/api/crons")!).count, 1)
        for address in ["http://localhost/api/crons", "https://localhost/apix", "https://other.local/api/crons", "https://sub.localhost/api/crons"] {
            XCTAssertTrue(NativePanelClient.matchingCookies([session], for: URL(string: address)!).isEmpty)
        }
    }
}
