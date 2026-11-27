import XCTest
@testable import JaegerShellCore

final class DroidStatusTests: XCTestCase {
    func testParsesAwakeReadyStatusWithGimbalAndPose() {
        let json = """
        {
          "ok": true,
          "awake": true,
          "sleeping": false,
          "camera": "ready",
          "estop_active": false,
          "pose": { "pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0, "tracking": false },
          "devices": {
            "gimbal_camera": { "name": "Insta360 Link 2" }
          }
        }
        """
        let snap = DroidStatusParser.parse(statusCode: 200, data: Data(json.utf8))
        XCTAssertTrue(snap.reachable)
        XCTAssertTrue(snap.awake)
        XCTAssertFalse(snap.sleeping)
        XCTAssertEqual(snap.stateLineTitle, "Droid: Awake (Camera Ready)")
        XCTAssertEqual(snap.senseLineTitle, "Insta360 Link 2 · pan 0° · tilt 0°")
        XCTAssertEqual(snap.toggleTitle, "Turn Off Droid Mode (Sleep & Park)")
        XCTAssertEqual(snap.toggleEndpointPath, "/v1/droid/sleep")
        XCTAssertTrue(snap.toggleEnabled)
        XCTAssertTrue(snap.parkEnabled)
        XCTAssertTrue(snap.centerEnabled)
    }

    func testParsesAwakeStreamingAndEstopFailSafeSleep() {
        let json = """
        {
          "ok": true,
          "awake": true,
          "sleeping": false,
          "camera": "streaming",
          "estop_active": true,
          "pose": { "pan_deg": -12.5, "tilt_deg": 4.0 },
          "devices": { "gimbal_camera": { "name": "Insta360 Link 2" } }
        }
        """
        let snap = DroidStatusParser.parse(statusCode: 200, data: Data(json.utf8))
        XCTAssertEqual(snap.stateLineTitle, "Droid: Awake (Streaming) · E-Stop ON")
        XCTAssertEqual(snap.senseLineTitle, "Insta360 Link 2 · pan -12.5° · tilt 4°")
        // Sleep / Turn Off and Park MUST remain enabled even under E-Stop!
        XCTAssertEqual(snap.toggleTitle, "Turn Off Droid Mode (Sleep & Park)")
        XCTAssertTrue(snap.toggleEnabled)
        XCTAssertTrue(snap.parkEnabled)
        // Centering is blocked under E-Stop.
        XCTAssertFalse(snap.centerEnabled)
    }

    func testParsesAsleepStatusAndFailClosedWakeUnderEstop() {
        let asleepNormal = """
        {
          "ok": true,
          "awake": false,
          "sleeping": true,
          "camera": "parked",
          "estop_active": false,
          "pose": { "pan_deg": 0, "tilt_deg": -85 },
          "devices": { "gimbal_camera": { "name": "Insta360 Link 2" } }
        }
        """
        let snap = DroidStatusParser.parse(statusCode: 200, data: Data(asleepNormal.utf8))
        XCTAssertEqual(snap.stateLineTitle, "Droid: Asleep (Camera Parked)")
        XCTAssertEqual(snap.senseLineTitle, "Insta360 Link 2 · pan 0° · tilt -85°")
        XCTAssertEqual(snap.toggleTitle, "Turn On Droid Mode (Wake)")
        XCTAssertEqual(snap.toggleEndpointPath, "/v1/droid/wake")
        XCTAssertTrue(snap.toggleEnabled)
        XCTAssertTrue(snap.parkEnabled)
        XCTAssertFalse(snap.centerEnabled)

        let asleepEstop = """
        {
          "ok": true,
          "awake": false,
          "sleeping": true,
          "camera": "parked",
          "estop_active": true,
          "pose": { "pan_deg": -0.0, "tilt_deg": -85.0 }
        }
        """
        let snapEstop = DroidStatusParser.parse(statusCode: 200, data: Data(asleepEstop.utf8))
        XCTAssertEqual(snapEstop.stateLineTitle, "Droid: Asleep (Camera Parked) · E-Stop ON")
        XCTAssertEqual(snapEstop.senseLineTitle, "pan 0° · tilt -85°")
        XCTAssertEqual(snapEstop.toggleTitle, "Turn On Droid Mode (Wake)")
        // Wake is blocked under E-Stop, while Park stays enabled.
        XCTAssertFalse(snapEstop.toggleEnabled)
        XCTAssertTrue(snapEstop.parkEnabled)
        XCTAssertFalse(snapEstop.centerEnabled)
    }

    func testHandlesOfflineAndErrorResponses() {
        let unreachable = DroidStatusParser.parse(statusCode: nil, data: nil)
        XCTAssertEqual(unreachable, .offline)
        XCTAssertEqual(unreachable.stateLineTitle, "Droid: Gateway offline")
        XCTAssertNil(unreachable.senseLineTitle)
        XCTAssertEqual(unreachable.toggleTitle, "Turn On Droid Mode (Wake)")
        XCTAssertFalse(unreachable.toggleEnabled)
        XCTAssertFalse(unreachable.parkEnabled)
        XCTAssertFalse(unreachable.centerEnabled)

        let http501 = DroidStatusParser.parse(statusCode: 501, data: Data(#"{"ok": false, "error": "droid embodiment unavailable"}"#.utf8))
        XCTAssertFalse(http501.reachable)
        XCTAssertEqual(http501.stateLineTitle, "Droid: Gateway offline")
        XCTAssertFalse(http501.toggleEnabled)
        XCTAssertFalse(http501.parkEnabled)
    }
}
