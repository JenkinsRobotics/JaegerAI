import XCTest
@testable import JaegerShellCore

final class NavigationPolicyTests: XCTestCase {
    let o = LoopbackOrigin(port: 18790)
    func d(_ s: String) -> NavigationDecision { NavigationPolicy.decide(URL(string: s), allowed: o) }
    func testAllowsOnlyTheOrigin() {
        XCTAssertEqual(d("http://127.0.0.1:18790/?host=macos"), .allow)
        XCTAssertEqual(d("http://127.0.0.1:18790/api/x"), .allow)
        XCTAssertEqual(d("about:blank"), .allow)
    }
    func testOthersLeaveTheShell() {
        XCTAssertEqual(d("http://127.0.0.1:8790/"), .openExternally)
        XCTAssertEqual(d("https://example.com/"), .openExternally)
        XCTAssertEqual(d("http://localhost:18790/"), .openExternally)
        XCTAssertEqual(d("file:///etc/hosts"), .block)
        XCTAssertEqual(d("javascript:alert(1)"), .block)
        XCTAssertEqual(NavigationPolicy.decide(nil, allowed: o), .block)
    }
    func testRuleListIsValidJSON() throws {
        let json = NavigationPolicy.contentRuleListJSON(allowed: o)
        let parsed = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [[String: Any]]
        XCTAssertEqual(parsed?.count, 6)
        // WebKit rejects disjunctions in url-filter; keep every filter free of "|".
        for rule in parsed ?? [] {
            let f = (rule["trigger"] as? [String: Any])?["url-filter"] as? String ?? ""
            XCTAssertFalse(f.contains("|"), f)
        }
        let filter = ((parsed?[1]["trigger"]) as? [String: Any])?["url-filter"] as? String
        XCTAssertEqual(filter, "^http://127\\.0\\.0\\.1:18790/")
    }
}
