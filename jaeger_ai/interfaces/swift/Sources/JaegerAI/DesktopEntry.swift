import Foundation

/// Executable-level launch verification without creating NSApplication,
/// windows, an agent bridge, device streams, or any model/GPU work.
@main
enum DesktopEntry {
    @MainActor
    static func main() {
        if CommandLine.arguments.contains("--verify-launch") {
            let report = launchReport()
            if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) {
                FileHandle.standardOutput.write(data)
                FileHandle.standardOutput.write(Data("\n".utf8))
            }
            exit(report["ok"] as? Bool == true ? 0 : 1)
        }
        JaegerAIApp.main()
    }

    @MainActor
    static func launchReport(bundle: Bundle = .main) -> [String: Any] {
        let launcher = BridgeProcess.jaegerPath()
        let icon = bundle.url(forResource: "AppIcon", withExtension: "icns")
        let identity = bundle.bundleIdentifier == "com.jenkinsrobotics.JaegerAI"
        let named = bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String == "Jaeger AI"
        let executable = FileManager.default.isExecutableFile(atPath: launcher)
        let helper = bundle.bundleURL.appendingPathComponent("Contents/MacOS/JaegerMultimodal").path
        let helperReady = FileManager.default.isExecutableFile(atPath: helper)
            && ["JaegerPythonHome", "JaegerPythonSite"].allSatisfy {
                guard let path = bundle.object(forInfoDictionaryKey: $0) as? String else { return false }
                return FileManager.default.fileExists(atPath: path)
            }
        let dock = bundle.object(forInfoDictionaryKey: "LSUIElement") as? Bool == false
        let privacy = ["NSMicrophoneUsageDescription", "NSCameraUsageDescription"].allSatisfy {
            !(bundle.object(forInfoDictionaryKey: $0) as? String ?? "").isEmpty
        }
        return [
            "ok": identity && named && executable && helperReady && icon != nil && dock && privacy,
            "application": "Jaeger AI", "bundle": bundle.bundlePath,
            "version": bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
            "launcher": launcher, "launcher_executable": executable,
            "multimodal_helper": helper, "multimodal_helper_ready": helperReady,
            "icon": icon?.path ?? "missing", "single_native_dock_owner": dock,
            "device_privacy_descriptions": privacy,
            "agent_started": false, "gpu_work_requested": false,
        ]
    }
}
