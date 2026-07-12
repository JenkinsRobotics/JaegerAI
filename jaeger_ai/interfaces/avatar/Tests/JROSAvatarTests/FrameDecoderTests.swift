// FrameDecoderTests.swift — round-trip tests for the binary wire
// format the Python AnimationNode publishes.  No live WebSocket;
// just construct the exact bytes the bridge will send and decode.

import XCTest
@testable import JROSAvatar

final class FrameDecoderTests: XCTestCase {

    func makeFrame(w: Int, h: Int, headerExtras: [String: Any] = [:]) -> Data {
        var header: [String: Any] = [
            "w": w, "h": h, "format": "RGBA8",
            "duration_ms": 33, "is_final": false,
            "asset": "test/face.png",
        ]
        for (k, v) in headerExtras { header[k] = v }
        let headerData = try! JSONSerialization.data(
            withJSONObject: header, options: [],
        )
        var data = Data()
        var lenBE = UInt32(headerData.count).bigEndian
        withUnsafeBytes(of: &lenBE) { data.append(contentsOf: $0) }
        data.append(headerData)
        data.append(contentsOf: [UInt8](repeating: 0xAB, count: w * h * 4))
        return data
    }

    func testRoundTripDecodes() throws {
        let raw = makeFrame(w: 8, h: 4)
        let decoded = try FrameDecoder.decode(raw)
        XCTAssertEqual(decoded.header.w, 8)
        XCTAssertEqual(decoded.header.h, 4)
        XCTAssertEqual(decoded.header.format, "RGBA8")
        XCTAssertFalse(decoded.header.isFinal)
        XCTAssertEqual(decoded.header.asset, "test/face.png")
    }

    func testTruncatedThrows() {
        let bad = Data([0, 0, 0, 4, 0x00])  // header length 4 but only 1 header byte
        XCTAssertThrowsError(try FrameDecoder.decode(bad))
    }

    func testUnsupportedFormatThrows() {
        let raw = makeFrame(w: 2, h: 2, headerExtras: ["format": "RGB565"])
        XCTAssertThrowsError(try FrameDecoder.decode(raw)) { err in
            guard case FrameDecodeError.unsupportedFormat(let f) = err else {
                XCTFail("expected unsupportedFormat, got \(err)")
                return
            }
            XCTAssertEqual(f, "RGB565")
        }
    }

    func testPixelSizeMismatchThrows() {
        // Build a payload that lies about its dimensions.
        var header: [String: Any] = [
            "w": 100, "h": 100, "format": "RGBA8",
            "duration_ms": 33, "is_final": false,
            "asset": "test.png",
        ]
        let headerData = try! JSONSerialization.data(
            withJSONObject: header, options: [],
        )
        var data = Data()
        var lenBE = UInt32(headerData.count).bigEndian
        withUnsafeBytes(of: &lenBE) { data.append(contentsOf: $0) }
        data.append(headerData)
        data.append(contentsOf: [UInt8](repeating: 0, count: 16))  // far too small
        XCTAssertThrowsError(try FrameDecoder.decode(data))
    }
}
