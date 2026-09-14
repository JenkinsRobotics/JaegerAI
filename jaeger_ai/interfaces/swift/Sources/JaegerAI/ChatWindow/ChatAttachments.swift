import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Decode bounded image thumbnails before crossing the chat transport. Non-image
/// documents keep their explicit filesystem references for the agent's file tools.
enum ChatAttachments {
    enum AttachmentError: LocalizedError {
        case tooMany, unreadable(String)
        var errorDescription: String? {
            switch self {
            case .tooMany: return "Attach up to four images per message."
            case .unreadable(let name): return "Couldn't read \(name). Use an image smaller than 20 MB."
            }
        }
    }

    static func prepare(_ urls: [URL]) throws -> [String] {
        let images = urls.filter { UTType(filenameExtension: $0.pathExtension)?.conforms(to: .image) == true }
        guard images.count <= 4 else { throw AttachmentError.tooMany }
        return try images.map { url in
            let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0, size <= 20 * 1024 * 1024,
                  let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                    kCGImageSourceCreateThumbnailFromImageAlways: true,
                    kCGImageSourceThumbnailMaxPixelSize: 2048,
                    kCGImageSourceCreateThumbnailWithTransform: true,
                    kCGImageSourceShouldCacheImmediately: true,
                  ] as CFDictionary) else {
                throw AttachmentError.unreadable(url.lastPathComponent)
            }
            let data = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
                throw AttachmentError.unreadable(url.lastPathComponent)
            }
            CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.88] as CFDictionary)
            guard CGImageDestinationFinalize(destination) else { throw AttachmentError.unreadable(url.lastPathComponent) }
            return "data:image/jpeg;base64," + (data as Data).base64EncodedString()
        }
    }
}
