import XCTest
@testable import JaegerShellCore

final class ForegroundLeaseTests: XCTestCase {
    func isolated(_ body: (String, String) throws -> Void) throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try body(root.appendingPathComponent("lease.json").path, root.appendingPathComponent("stop.json").path)
    }
    func fixture(_ body: String, _ path: String) throws {
        try Data(body.utf8).write(to: URL(fileURLWithPath: path))
    }
    func testExpiredOfflineTakeoverUsesRealHeartbeatAndPreservesLeaseOnRelease() throws {
        try isolated { path, stop in
            try fixture(LeaseContract.body(beatAt: 0), path)
            let owner = ForegroundLease(path: path, stopPath: stop)
            try owner.acquire() // no network service exists or is needed
            let data = try String(contentsOfFile: path, encoding: .utf8)
            XCTAssertEqual(LeaseContract.decide(contents: data, now: Date().timeIntervalSince1970), .alive)
            let mode = try FileManager.default.attributesOfItem(atPath: path)[.posixPermissions] as? Int
            XCTAssertEqual(mode, 0o600)
            owner.relinquish()
            XCTAssertEqual(try String(contentsOfFile: path, encoding: .utf8), data)
        }
    }
    func testLiveLockAndStaleButLivePIDCannotBeTakenOver() throws {
        try isolated { path, stop in
            let first = ForegroundLease(path: path, stopPath: stop)
            try first.acquire()
            let second = ForegroundLease(path: path, stopPath: stop)
            XCTAssertThrowsError(try second.acquire())
            first.relinquish()
            try fixture("{\"owner\":\"menubar\",\"beat_at\":0,\"shell_pid\":\(ProcessInfo.processInfo.processIdentifier)}", path)
            let before = try Data(contentsOf: URL(fileURLWithPath: path))
            XCTAssertThrowsError(try second.acquire())
            XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: path)), before)
        }
    }
    func testRecentLegacyOwnerForeignAndCorruptLeaseRefused() throws {
        try isolated { path, stop in
            for contents in [LeaseContract.body(beatAt: Date().timeIntervalSince1970), "garbage", "{\"owner\":\"other\",\"beat_at\":0}"] {
                try fixture(contents, path)
                XCTAssertThrowsError(try ForegroundLease(path: path, stopPath: stop).acquire())
                XCTAssertEqual(try String(contentsOfFile: path, encoding: .utf8), contents)
            }
        }
    }
    func testStopBlocksStartupAndFurtherBeatsWithoutClearingOrResuming() throws {
        try isolated { path, stop in
            try fixture("{\"engaged\":true}", stop)
            XCTAssertThrowsError(try ForegroundLease(path: path, stopPath: stop).acquire())
            XCTAssertFalse(FileManager.default.fileExists(atPath: path))
            try fixture("{\"engaged\":false}", stop)
            let owner = ForegroundLease(path: path, stopPath: stop)
            try owner.acquire()
            let before = try Data(contentsOf: URL(fileURLWithPath: path))
            try fixture("{\"engaged\":true}", stop)
            XCTAssertThrowsError(try owner.heartbeat())
            XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: path)), before)
            try fixture("{\"engaged\":false}", stop)
            XCTAssertThrowsError(try owner.heartbeat())
            owner.relinquish()
            try fixture("broken", stop)
            XCTAssertThrowsError(try ForegroundLease(path: path, stopPath: stop).acquire())
        }
    }
}
