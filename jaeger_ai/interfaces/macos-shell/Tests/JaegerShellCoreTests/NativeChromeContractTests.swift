import XCTest
@testable import JaegerShellCore

final class NativeChromeContractTests: XCTestCase {
    func testScriptSetsTheAttributesAndVarsTheUIStylesOn() {
        let js = NativeChromeContract.script(titlebarHeight: 52.4, trafficLightWidth: 77.6,
                                             bandHeight: 52, trafficLightReserve: 89.6)
        XCTAssertTrue(js.contains("setAttribute('data-native-vibrancy', 'none')"))
        XCTAssertTrue(js.contains("setAttribute('data-jaeger-host', 'macos')"))
        XCTAssertTrue(js.contains("'--jaeger-native-titlebar-height', '52px'"))
        XCTAssertTrue(js.contains("'--jaeger-native-traffic-light-width', '78px'"))
        XCTAssertTrue(js.contains("'--jaeger-native-band-height', '52px'"))
        XCTAssertTrue(js.contains("'--jaeger-native-traffic-light-reserve', '90px'"))
    }

    func testValuesRoundToWholePixels() {
        let v = NativeChromeContract.values(titlebarHeight: 0, trafficLightWidth: 69.5, bandHeight: 0, trafficLightReserve: 0)
        XCTAssertEqual(v[NativeChromeContract.titlebarHeightVar], "0px")
        XCTAssertEqual(v[NativeChromeContract.trafficLightWidthVar], "70px")
        XCTAssertEqual(v[NativeChromeContract.bandHeightVar], "0px")
        XCTAssertEqual(v[NativeChromeContract.vibrancyAttribute], "none")
    }

    func testWindowGeometryMatchesTheMeasuredTarget() {
        XCTAssertEqual(NativeChromeContract.defaultWidth, 1040)
        XCTAssertEqual(NativeChromeContract.defaultHeight, 760)
        XCTAssertEqual(NativeChromeContract.minWidth, 600)
        XCTAssertEqual(NativeChromeContract.minHeight, 520)
        XCTAssertEqual(NativeChromeContract.bandHeight, 52)
        XCTAssertEqual(NativeChromeContract.backgroundLight.hex, "#fcfcfc")
        XCTAssertEqual(NativeChromeContract.backgroundDark.hex, "#121212")
        XCTAssertEqual(NativeChromeContract.background(dark: true), NativeChromeContract.RGB.parse(hex: "#121212"))
        XCTAssertNil(NativeChromeContract.RGB.parse(hex: "#12121"))
    }

    func testTrafficLightsMoveAsAGroupToTheInset() {
        // AppKit's default positions under a 52 pt unified toolbar (close/mini/zoom 14×16, 20 pt apart).
        let frames = [NativeChromeContract.Rect(x: 7, top: 18, width: 14, height: 16),
                      NativeChromeContract.Rect(x: 27, top: 18, width: 14, height: 16),
                      NativeChromeContract.Rect(x: 47, top: 18, width: 14, height: 16)]
        let t = NativeChromeContract.trafficLightTargets(frames)
        XCTAssertEqual(t.map(\.x), [16, 39, 62])  // the reference window's 23 pt pitch
        XCTAssertEqual(t.map(\.top), [15, 15, 15])
        XCTAssertEqual(t[2].width, 14)
        XCTAssertEqual(NativeChromeContract.trafficLightTargets([]), [])
        XCTAssertEqual(NativeChromeContract.trafficLightReserve(zoomMaxX: t[2].maxX), 88)
        XCTAssertEqual(NativeChromeContract.trafficLightReserve(zoomMaxX: nil), 0)
    }
}
