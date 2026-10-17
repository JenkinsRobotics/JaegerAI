// JaegerShellCore: capture-tap math. Mono mix-down adapted from
// jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/VoiceRecorder.swift:297-307 (Jenkins Robotics);
// RMS replaces the old peak meter (the bridge reports `voice.level {rms}`).
public enum AudioMath {
    public static func mixToMono(_ channels: [[Float]]) -> [Float] {
        guard let first = channels.first else { return [] }
        if channels.count == 1 { return first }
        var mono = [Float](repeating: 0, count: first.count)
        for channel in channels {
            for i in 0..<min(channel.count, mono.count) { mono[i] += channel[i] }
        }
        let inv = 1 / Float(channels.count)
        for i in mono.indices { mono[i] *= inv }
        return mono
    }

    public static func rms(_ samples: [Float]) -> Float {
        guard !samples.isEmpty else { return 0 }
        var sum: Float = 0
        for v in samples { sum += v * v }
        return (sum / Float(samples.count)).squareRoot()
    }
}
