import Foundation

enum WebUIEndpoint {
    /// CLI prints one bare browser URL, then an optional labelled remote URL.
    /// Ignore diagnostic lines, but reject ambiguous bare addresses.
    static func parseAddress(_ output: String) -> URL? {
        let candidates = output.split(whereSeparator: \.isNewline).compactMap { line -> URL? in
            let value = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.contains(where: { $0.isWhitespace }),
                  let parts = URLComponents(string: value),
                  ["http", "https"].contains(parts.scheme ?? ""),
                  let host = parts.host, !host.isEmpty,
                  parts.user == nil, parts.password == nil,
                  let url = parts.url else { return nil }
            return url
        }
        return candidates.count == 1 ? candidates[0] : nil
    }

    /// Use the deployment resolver shared with the operator CLI.
    static func resolve(instance: String? = nil) async throws -> URL {
        try await Task.detached {
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: BridgeProcess.jaegerPath())
            process.arguments = ["webui", "url"] + (instance.map { ["--instance", $0] } ?? [])
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            try process.run()
            let timeout = Task {
                try? await Task.sleep(for: .seconds(15))
                if !Task.isCancelled && process.isRunning { process.terminate() }
            }
            defer { timeout.cancel() }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let address = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard process.terminationStatus == 0,
                  let url = parseAddress(address) else {
                throw BridgeError.launchFailed("Cannot resolve the WebUI address. Run jaeger webui url for details.")
            }
            return url
        }.value
    }
}
