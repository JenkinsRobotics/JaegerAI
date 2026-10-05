import Foundation
import XCTest
@testable import JaegerAI

final class LifecycleLeaseBeatTests: XCTestCase {
    private var directory: URL!

    override func setUp() {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("jaeger-lease-\(UUID().uuidString)", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        setenv(
            "JAEGER_LIFECYCLE_LEASE",
            directory.appendingPathComponent("lifecycle-lease.json").path,
            1
        )
    }

    override func tearDown() {
        LifecycleLeaseBeat.stop()
        unsetenv("JAEGER_LIFECYCLE_LEASE")
        if let directory {
            try? FileManager.default.removeItem(at: directory)
        }
    }

    func testMenuBarWritesAndRenewsTheLease() throws {
        let url = directory.appendingPathComponent("lifecycle-lease.json")
        LifecycleLeaseBeat.write()
        let first = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        XCTAssertEqual(first["owner"] as? String, "menubar")
        let beat = try XCTUnwrap(first["beat_at"] as? Double)
        Thread.sleep(forTimeInterval: 0.02)
        LifecycleLeaseBeat.write()
        let second = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        let renewed = try XCTUnwrap(second["beat_at"] as? Double)
        XCTAssertGreaterThan(renewed, beat)
        let mode = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber
        )
        XCTAssertEqual(mode.intValue, 0o600)
    }

    func testStopLeavesTheLeaseSoACrashIsNotAFreshBoot() throws {
        LifecycleLeaseBeat.start()
        let url = directory.appendingPathComponent("lifecycle-lease.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))
        LifecycleLeaseBeat.stop()
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))
    }

    func testQuitRetiresTheLeaseSoARelaunchIsNotALiveOwner() throws {
        LifecycleLeaseBeat.start()
        LifecycleLeaseBeat.retire()
        let url = directory.appendingPathComponent("lifecycle-lease.json")
        let raw = try String(contentsOf: url, encoding: .utf8)
        XCTAssertEqual(raw, "{\"beat_at\": 0.000000, \"owner\": \"menubar\"}\n")
        let mode = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber
        )
        XCTAssertEqual(mode.intValue, 0o600)
    }
}
