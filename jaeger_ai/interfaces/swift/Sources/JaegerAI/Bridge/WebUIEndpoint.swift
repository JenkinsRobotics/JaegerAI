import Foundation

enum WebUIEndpoint {
    /// Use the deployment resolver shared with the operator CLI.
    static func resolve(instance: String? = nil) async throws -> URL {
        try await Task.detached {
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: BridgeProcess.jaegerPath())
            process.arguments = ["webui", "url"] + (instance.map { ["--instance", $0] } ?? [])
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
                  let url = URL(string: address),
                  ["http", "https"].contains(url.scheme ?? ""), url.host != nil else {
                throw BridgeError.launchFailed("Cannot resolve the WebUI address. Run jaeger webui url for details.")
            }
            return url
        }.value
    }
}
