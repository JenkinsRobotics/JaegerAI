//
//  MultimodalWindowController.swift
//  Jaeger AI / Multimodal
//
//  Opens the imported PySide6 multimodal workspace from the native menu card.
//  The normal Swift bridge and that workspace both own a complete AgentRuntime,
//  so they must not hold the same instance/model lock at once. This controller
//  performs an orderly handoff and reconnects the normal bridge on close.
//

import AppKit
import Foundation

@MainActor
final class MultimodalWindowController {
    static let shared = MultimodalWindowController()

    static let launchArguments = ["multimodal", "--audio", "structured"]

    private var process: Process?
    private weak var owningAgent: AgentBridge?
    private var instanceName = AgentBridge.defaultInstanceName
    private var launchInProgress = false
    private var reconnectOnExit = true

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
        return environment
    }

    private func present(agent: AgentBridge) async {
        if let process, process.isRunning {
            activate(process)
            return
        }
        guard !launchInProgress else { return }
        guard !agent.isBusy else {
            showFailure(
                title: "Multimodal workspace is waiting",
                message: "Let the current agent task finish, then open Multimodal again."
            )
            return
        }

        launchInProgress = true
        defer { launchInProgress = false }

        let instance = agent.status?.instance ?? AgentBridge.defaultInstanceName
        instanceName = instance
        owningAgent = agent
        reconnectOnExit = true

        // Release the one AgentRuntime/model/instance lock before the dedicated
        // multimodal face acquires it. It reconnects in processDidTerminate().
        if agent.isConnected {
            await agent.shutdownForQuit()
        }

        let path = BridgeProcess.jaegerPath()
        guard FileManager.default.isExecutableFile(atPath: path) else {
            showFailure(
                title: "Couldn’t open Multimodal",
                message: "The Jaeger AI launcher is not executable at \(path)."
            )
            await agent.tryConnect(instance: instance)
            return
        }

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
        child.standardOutput = FileHandle.standardOutput
        child.standardError = FileHandle.standardError
        child.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                await self?.processDidTerminate()
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
            await agent.tryConnect(instance: instance)
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

    private func processDidTerminate() async {
        process = nil
        guard reconnectOnExit, let agent = owningAgent else { return }
        await agent.tryConnect(instance: instanceName)
    }

    func stopForApplicationQuit() {
        reconnectOnExit = false
        process?.terminationHandler = nil
        if process?.isRunning == true { process?.terminate() }
        process = nil
        owningAgent = nil
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
