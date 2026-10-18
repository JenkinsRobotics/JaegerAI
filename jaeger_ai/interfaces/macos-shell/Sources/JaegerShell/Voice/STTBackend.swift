// STTBackend.swift — ported from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/STT/STTBackend.swift:29-90
// (Jenkins Robotics); unchanged apart from comments.
import AVFoundation
import Foundation

struct STTResult: Sendable {
    let text: String
    let confidence: Float?
    let elapsedSeconds: Double
}

protocol STTBackend: AnyObject {
    var displayName: String { get }
    var isAvailable: Bool { get }
    func transcribe(samples: [Float], format: AVAudioFormat,
                    completion: @escaping @Sendable (Result<STTResult, Error>) -> Void)
    func cancel()
}

enum STTError: Error, LocalizedError {
    case unavailable(String)
    case authorizationDenied(String)
    case recognitionFailed(String)
    case noSpeechDetected

    var errorDescription: String? {
        switch self {
        case .unavailable(let s): return "STT unavailable — \(s)"
        case .authorizationDenied(let s): return "speech recognition denied — \(s)"
        case .recognitionFailed(let s): return "recognition failed — \(s)"
        case .noSpeechDetected: return "didn't catch any speech"
        }
    }
}
