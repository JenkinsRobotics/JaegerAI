//
//  MultimodalWindowController.swift
//  Jaeger AI / Multimodal
//
//  Opens the imported PySide6 multimodal workspace from the native menu card.
//  The workspace is a thin face attached to the normal Swift bridge. The
//  bridge remains the sole owner of Gemma, memory, tools, and AgentRuntime.
//

import AppKit
import AVFoundation
import Foundation

@MainActor
final class MultimodalWindowController {
    static let shared = MultimodalWindowController()

    static let launchArguments = ["multimodal", "--attach", "--audio", "structured"]

    static func bundledHelperArguments(sitePackages: String) -> [String] {
        ["-c", "import site, sys; site.addsitedir(sys.argv.pop(1)); "
            + "from jaeger_ai.interfaces.pyside6.multimodal.__main__ import main; "
            + "raise SystemExit(main())", sitePackages, "--attach", "--audio", "structured"]
    }

    private var process: Process?
    private var launchInProgress = false

    private init() {}

    static func show(agent: AgentBridge) {
        Task { await shared.present(agent: agent) }
    }

    static func launchEnvironment(
        base: [String: String],
        instance: String
    ) -> [String: String] {
        var environment = base
        environment["JAEGER_INSTANCE_NAME"] = instance
        environment["JAEGER_DESKTOP_HELPER"] = "1"
        return environment
    }

    /// Consent belongs to the installed app, whose Info.plist contains the
    /// camera purpose string. Ask before the embedded Python helper starts
    /// its device initialization; both executables share the app's metadata.
    static func prepareCameraPermission(
        status: AVAuthorizationStatus = AVCaptureDevice.authorizationStatus(for: .video),
        request: () async -> Bool = { await AVCaptureDevice.requestAccess(for: .video) }
    ) async -> Bool {
        switch status {
        case .authorized: return true
        case .notDetermined: return await request()
        default: return false
        }
    }

    private func present(agent: AgentBridge) async {
        if let process, process.isRunning {
            activate(process)
            return
        }
        guard !launchInProgress else { return }
        guard agent.isConnected else {
            showFailure(
                title: "Jaeger AI is still starting",
                message: "Wait for the agent to be ready, then open Multimodal again."
            )
            return
        }

        launchInProgress = true
        defer { launchInProgress = false }

        let instance = agent.status?.instance ?? AgentBridge.defaultInstanceName

        let path = BridgeProcess.jaegerPath()
        guard FileManager.default.isExecutableFile(atPath: path) else {
            showFailure(
                title: "Couldn’t open Multimodal",
                message: "The Jaeger AI launcher is not executable at \(path)."
            )
            return
        }

        // Denying video must not prevent text/audio use of the workspace.
        _ = await Self.prepareCameraPermission()

        let child = Process()
        child.executableURL = URL(fileURLWithPath: path)
        child.arguments = Self.launchArguments
        child.currentDirectoryURL = URL(
            fileURLWithPath: (path as NSString).deletingLastPathComponent
        )
        child.environment = Self.launchEnvironment(
            base: ProcessInfo.processInfo.environment,
            instance: instance
        )
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/JaegerMultimodal")
        if FileManager.default.isExecutableFile(atPath: helper.path),
           let pythonHome = Bundle.main.object(forInfoDictionaryKey: "JaegerPythonHome") as? String,
           let sitePackages = Bundle.main.object(forInfoDictionaryKey: "JaegerPythonSite") as? String {
            child.executableURL = helper
            child.arguments = Self.bundledHelperArguments(sitePackages: sitePackages)
            child.environment?["PYTHONHOME"] = pythonHome
        }
        child.standardOutput = FileHandle.standardOutput
        child.standardError = FileHandle.standardError
        child.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                self?.processDidTerminate()
            }
        }

        do {
            try child.run()
            process = child
        } catch {
            showFailure(
                title: "Couldn’t open Multimodal",
                message: error.localizedDescription
            )
            return
        }

        // Qt needs a moment to create its first native window before AppKit can
        // ask the child application to raise it.
        try? await Task.sleep(for: .milliseconds(500))
        activate(child)
    }

    private func activate(_ process: Process) {
        guard process.isRunning else { return }
        NSRunningApplication(processIdentifier: process.processIdentifier)?
            .activate(options: [.activateAllWindows])
    }

    private func processDidTerminate() {
        process = nil
    }

    func stopForApplicationQuit() {
        process?.terminationHandler = nil
        if process?.isRunning == true { process?.terminate() }
        process = nil
    }

    private func showFailure(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
