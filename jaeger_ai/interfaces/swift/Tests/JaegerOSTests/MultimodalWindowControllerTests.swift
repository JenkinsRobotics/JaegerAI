import XCTest
import AVFoundation
@testable import JaegerOS

@MainActor
final class MultimodalWindowControllerTests: XCTestCase {
    func testCameraConsentIsRequestedOnlyWhenUndetermined() async {
        for status: AVAuthorizationStatus in [.authorized, .denied, .restricted] {
            var requested = false
            let allowed = await MultimodalWindowController.prepareCameraPermission(status: status) {
                requested = true
                return true
            }
            XCTAssertFalse(requested)
            XCTAssertEqual(allowed, status == .authorized)
        }
    }

    func testCameraConsentPreservesTheUsersChoice() async {
        for choice in [false, true] {
            var requests = 0
            let allowed = await MultimodalWindowController.prepareCameraPermission(status: .notDetermined) {
                requests += 1
                return choice
            }
            XCTAssertEqual(requests, 1)
            XCTAssertEqual(allowed, choice)
        }
    }

    func testLaunchesCanonicalMultimodalFace() {
        XCTAssertEqual(
            MultimodalWindowController.launchArguments,
            ["multimodal", "--attach", "--audio", "structured"]
        )
    }

    func testBundledHelperPreservesPathsAndCanonicalFaceArguments() {
        let args = MultimodalWindowController.bundledHelperArguments(sitePackages: "/a path/site-packages")
        XCTAssertEqual(args[0], "-c")
        XCTAssertTrue(args[1].contains("site.addsitedir(sys.argv.pop(1))"))
        XCTAssertEqual(args[2], "/a path/site-packages")
        XCTAssertEqual(Array(args.suffix(3)), ["--attach", "--audio", "structured"])
    }

    func testLaunchEnvironmentPinsTheCurrentAgentInstance() {
        let environment = MultimodalWindowController.launchEnvironment(
            base: ["PATH": "/usr/bin", "JAEGER_INSTANCE_NAME": "old"],
            instance: "lilith"
        )
        XCTAssertEqual(environment["PATH"], "/usr/bin")
        XCTAssertEqual(environment["JAEGER_INSTANCE_NAME"], "lilith")
        XCTAssertEqual(environment["JAEGER_DESKTOP_HELPER"], "1")
    }
}
