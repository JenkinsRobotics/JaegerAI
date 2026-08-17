// FrameDecoder.swift — turns a raw WebSocket binary message
// (4-byte length prefix + JSON header + RGBA pixel bytes) into a
// FrameHeader + NSImage we can hand to RendererView.

import AppKit
import Foundation

/// Per-frame metadata that rides alongside each pixel buffer.
/// Matches `jaeger_os.nodes.animation.base.FrameBuffer` on the
/// Python side; see `dev_docs/0.5.0_swift_renderer_plan.md` for
/// the wire format.
struct FrameHeader: Decodable {
    let w: Int
    let h: Int
    let format: String           // "RGBA8" today; future formats opt-in
    let durationMs: Int
    let isFinal: Bool
    let asset: String

    enum CodingKeys: String, CodingKey {
        case w, h, format, asset
        case durationMs = "duration_ms"
        case isFinal = "is_final"
    }
}

enum FrameDecodeError: Error {
    case truncated
    case headerNotJSON
    case unsupportedFormat(String)
    case pixelSizeMismatch(expected: Int, actual: Int)
    case imageConstructionFailed
}

struct DecodedFrame {
    let header: FrameHeader
    let image: NSImage
}

enum FrameDecoder {
    /// Parse one binary message: [4-byte BE length L][L JSON bytes][pixels].
    /// Returns the decoded header + an NSImage built from the
    /// pixel buffer.  Throws if the message is malformed or the
    /// pixel buffer doesn't match the declared size.
    static func decode(_ data: Data) throws -> DecodedFrame {
        guard data.count >= 4 else { throw FrameDecodeError.truncated }
        let headerLen = Int(
            UInt32(data[0]) << 24
            | UInt32(data[1]) << 16
            | UInt32(data[2]) << 8
            | UInt32(data[3])
        )
        guard data.count >= 4 + headerLen else {
            throw FrameDecodeError.truncated
        }
        let headerData = data.subdata(in: 4..<(4 + headerLen))
        let pixelData = data.subdata(in: (4 + headerLen)..<data.count)

        let header: FrameHeader
        do {
            header = try JSONDecoder().decode(
                FrameHeader.self, from: headerData,
            )
        } catch {
            throw FrameDecodeError.headerNotJSON
        }
        guard header.format == "RGBA8" else {
            throw FrameDecodeError.unsupportedFormat(header.format)
        }
        let expected = header.w * header.h * 4
        guard pixelData.count == expected else {
            throw FrameDecodeError.pixelSizeMismatch(
                expected: expected, actual: pixelData.count,
            )
        }
        guard let image = makeImage(
            width: header.w, height: header.h, rgba: pixelData,
        ) else {
            throw FrameDecodeError.imageConstructionFailed
        }
        return DecodedFrame(header: header, image: image)
    }

    private static func makeImage(
        width: Int, height: Int, rgba: Data,
    ) -> NSImage? {
        var data = rgba
        return data.withUnsafeMutableBytes { (raw: UnsafeMutableRawBufferPointer) -> NSImage? in
            guard let base = raw.baseAddress else { return nil }
            let colorSpace = CGColorSpaceCreateDeviceRGB()
            let bitmapInfo = CGBitmapInfo(
                rawValue: CGImageAlphaInfo.premultipliedLast.rawValue,
            )
            guard let provider = CGDataProvider(
                dataInfo: nil,
                data: base,
                size: rgba.count,
                releaseData: { _, _, _ in /* base owned by Data */ },
            ) else { return nil }
            guard let cg = CGImage(
                width: width, height: height,
                bitsPerComponent: 8, bitsPerPixel: 32,
                bytesPerRow: width * 4,
                space: colorSpace, bitmapInfo: bitmapInfo,
                provider: provider, decode: nil,
                shouldInterpolate: false, intent: .defaultIntent,
            ) else { return nil }
            return NSImage(
                cgImage: cg,
                size: NSSize(width: width, height: height),
            )
        }
    }
}
