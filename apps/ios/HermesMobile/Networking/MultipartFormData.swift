import Foundation

/// Shared `multipart/form-data` body builders for the upload and transcribe
/// endpoints. Kept in one place so `APIClient+Upload` and `APIClient+Transcribe`
/// emit byte-identical field encodings (boundaries, CRLFs, dispositions).
extension Data {
    mutating func appendMultipart(textField name: String, value: String, boundary: String) {
        append(Data("--\(boundary)\r\n".utf8))
        append(Data("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".utf8))
        append(Data("\(value)\r\n".utf8))
    }

    mutating func appendMultipart(fileField name: String, filename: String, data: Data, boundary: String) {
        append(Data("--\(boundary)\r\n".utf8))
        append(Data("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n".utf8))
        append(Data("Content-Type: application/octet-stream\r\n\r\n".utf8))
        append(data)
        append(Data("\r\n".utf8))
    }

    mutating func appendMultipartClosingBoundary(_ boundary: String) {
        append(Data("--\(boundary)--\r\n".utf8))
    }
}
