import XCTest
@testable import JaegerAI

final class RuntimeSkillsTests: XCTestCase {
    func testGatewayCatalogPreservesLifecycleAndIdentity() throws {
        let data = Data(#"{"skills":[{"name":"review","category":"code","description":"Review changes","lifecycle":"available"}],"count":1}"#.utf8)
        let catalog = try JSONDecoder().decode(GatewayClient.RuntimeSkills.self, from: data)
        XCTAssertEqual(catalog.skills.first?.id, "code/review")
        XCTAssertEqual(catalog.skills.first?.lifecycle, "available")
    }

    func testEmptyAndMalformedCatalogAreDifferent() throws {
        let empty = try JSONDecoder().decode(GatewayClient.RuntimeSkills.self, from: Data(#"{"skills":[],"count":0}"#.utf8))
        XCTAssertTrue(empty.skills.isEmpty)
        XCTAssertThrowsError(try JSONDecoder().decode(GatewayClient.RuntimeSkills.self, from: Data(#"{"error":"unavailable"}"#.utf8)))
    }
}
