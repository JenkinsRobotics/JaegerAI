import Foundation

/// Projection only. The native host obtains text only after explicit clipboard.read.
public enum ClipboardPreview {
    public static let maxBytes = 100_000
    public static func project(_ text: String?) -> [String: Any] {
        guard let text else { return ["state": "no_text_or_access_unavailable", "max_bytes": maxBytes] }
        guard text.utf8.count <= maxBytes else { return ["state": "over_limit", "max_bytes": maxBytes] }
        return ["state": "text_available", "text": text, "max_bytes": maxBytes, "content_type": "text/plain"]
    }
}
