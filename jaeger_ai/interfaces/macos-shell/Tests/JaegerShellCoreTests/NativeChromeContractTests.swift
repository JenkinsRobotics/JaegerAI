import XCTest
@testable import JaegerShellCore

final class NativeChromeContractTests: XCTestCase {
    func testScriptSetsTheAttributesTheUIStylesOn() {
        let js = NativeChromeContract.script(titlebarHeight: 52.4, trafficLightWidth: 77.6)
        // shell.css keys the sidebar vibrancy and macOS layout on these.
        XCTAssertTrue(js.contains("setAttribute('data-native-vibrancy', 'sidebar')"))
        XCTAssertTrue(js.contains("setAttribute('data-jaeger-host', 'macos')"))
        XCTAssertTrue(js.contains("'--jaeger-native-titlebar-height', '52px'"))
        XCTAssertTrue(js.contains("'--jaeger-native-traffic-light-width', '78px'"))
    }

    func testValuesRoundToWholePixels() {
        let v = NativeChromeContract.values(titlebarHeight: 0, trafficLightWidth: 69.5)
        XCTAssertEqual(v[NativeChromeContract.titlebarHeightVar], "0px")
        XCTAssertEqual(v[NativeChromeContract.trafficLightWidthVar], "70px")
    }
}
