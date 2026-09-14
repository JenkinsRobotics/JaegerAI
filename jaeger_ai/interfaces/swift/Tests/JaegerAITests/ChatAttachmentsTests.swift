import XCTest
import AppKit
@testable import JaegerAI

final class ChatAttachmentsTests: XCTestCase {
    func testImagesAndToolModeReachTheWireWithoutDuplicateSpeech() throws {
        let images = ["data:image/jpeg;base64,one", "data:image/jpeg;base64,two"]
        let request = BridgeProcess.chatRequest(text: "compare", session: "one",
                                                agenticTools: false, images: images,
                                                speakReplies: true)
        let data = try JSONSerialization.data(withJSONObject: request)
        let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(decoded["agentic_tools"] as? Bool, false)
        XCTAssertEqual(decoded["client_owned_speech"] as? Bool, true)
        XCTAssertEqual(decoded["output_mode"] as? String, "speech")
        let blocks = try XCTUnwrap(decoded["content"] as? [[String: Any]])
        XCTAssertEqual(blocks.count, 3)
        XCTAssertEqual(blocks[0]["text"] as? String, "compare")
        XCTAssertEqual(blocks.dropFirst().compactMap { ($0["image_url"] as? [String: String])?["url"] }, images)
    }

    func testMutedTextOnlyRequestNeedsNoImagePayload() {
        let request = BridgeProcess.chatRequest(text: "hello", session: "one",
                                                agenticTools: true, images: [], speakReplies: false)
        XCTAssertEqual(request["output_mode"] as? String, "text")
        XCTAssertNil(request["content"])
    }

    func testRealImageIsEncodedAndInvalidImageRetainsAnError() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let bitmap = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 16, pixelsHigh: 12,
                                                   bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false,
                                                   isPlanar: false, colorSpaceName: .deviceRGB,
                                                   bytesPerRow: 0, bitsPerPixel: 0))
        let photo = folder.appendingPathComponent("board.png")
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:])).write(to: photo)
        let document = folder.appendingPathComponent("notes.txt")
        try Data("notes".utf8).write(to: document)
        let encoded = try ChatAttachments.prepare([photo, document])
        XCTAssertEqual(encoded.count, 1)
        XCTAssertTrue(encoded[0].hasPrefix("data:image/jpeg;base64,"))
        let bytes = try XCTUnwrap(Data(base64Encoded: String(encoded[0].split(separator: ",")[1])))
        XCTAssertNotNil(NSBitmapImageRep(data: bytes))
        try Data("not an image".utf8).write(to: photo)
        XCTAssertThrowsError(try ChatAttachments.prepare([photo]))
        XCTAssertThrowsError(try ChatAttachments.prepare(Array(repeating: photo, count: 5)))
    }
}
