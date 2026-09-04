import XCTest
@testable import JaegerOS

@MainActor
final class MultimodalWindowControllerTests: XCTestCase {
    func testLaunchesCanonicalMultimodalFace() {
        XCTAssertEqual(
            MultimodalWindowController.launchArguments,
            ["multimodal", "--audio", "structured"]
        )
    }

    func testLaunchEnvironmentPinsTheCurrentAgentInstance() {
        let environment = MultimodalWindowController.launchEnvironment(
            base: ["PATH": "/usr/bin", "JAEGER_INSTANCE_NAME": "old"],
            instance: "lilith"
        )
        XCTAssertEqual(environment["PATH"], "/usr/bin")
        XCTAssertEqual(environment["JAEGER_INSTANCE_NAME"], "lilith")
    }
}
