// DroidMenuController.swift — Droid section in the Jaeger menu-bar item.
//
// Communicates directly with the modular Jaeger Gateway HTTP API
// (`ShellEnvironment.gateway().origin.string`, default http://127.0.0.1:33418)
// using `/v1/droid/status`, `/v1/droid/wake`, `/v1/droid/sleep`,
// `/v1/droid/devices?refresh=1`, and `/v1/embodiment/droid/act`.

import AppKit
import AVFoundation
import JaegerShellCore

final class DroidMenuController: NSObject {
    private weak var app: JaegerShellApplication?
    private let session = URLSession(configuration: .ephemeral)
    private var lastSnapshot: DroidStatusSnapshot = .offline
    private var refreshGeneration: Int = 0

    private let stateLine = NSMenuItem(title: "Droid: …", action: nil, keyEquivalent: "")
    private let senseLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let toggleItem = NSMenuItem(title: "Turn On Droid Mode (Wake)", action: #selector(toggle), keyEquivalent: "")
    private let parkItem = NSMenuItem(title: "Park Camera Now (Privacy)", action: #selector(parkCameraNow), keyEquivalent: "")
    private let centerItem = NSMenuItem(title: "Center Camera", action: #selector(centerCamera), keyEquivalent: "")
    private let viewItem = NSMenuItem(title: "Open Droid View", action: #selector(openDroidView), keyEquivalent: "")
    private let micPermission = NSMenuItem(title: "Microphone: …", action: #selector(openMicSettings), keyEquivalent: "")
    private let cameraPermission = NSMenuItem(title: "Camera: …", action: #selector(openCameraSettings), keyEquivalent: "")
    private let refreshDevicesItem = NSMenuItem(title: "Refresh Droid Peripherals", action: #selector(refreshDevices), keyEquivalent: "")

    init(app: JaegerShellApplication? = nil) {
        self.app = app
        super.init()
    }

    private var gatewayOrigin: String {
        ShellEnvironment.gateway().origin.string
    }

    func install(in menu: NSMenu) {
        stateLine.isEnabled = false
        senseLine.isEnabled = false
        senseLine.isHidden = true
        for entry in [toggleItem, parkItem, centerItem, viewItem, micPermission, cameraPermission, refreshDevicesItem] {
            entry.target = self
        }
        toggleItem.isEnabled = false
        parkItem.isEnabled = false
        centerItem.isEnabled = false
        refreshPermissions()

        let permissions = NSMenu()
        permissions.addItem(micPermission)
        permissions.addItem(cameraPermission)
        let permissionsItem = NSMenuItem(title: "Permissions", action: nil, keyEquivalent: "")
        permissionsItem.submenu = permissions

        for entry in [stateLine, senseLine, toggleItem, parkItem, centerItem, viewItem, permissionsItem, refreshDevicesItem] {
            menu.addItem(entry)
        }
    }

    func refresh() {
        refreshPermissions()
        refreshGeneration &+= 1
        let generation = refreshGeneration
        let urlString = gatewayOrigin + "/v1/droid/status"
        guard let url = URL(string: urlString) else {
            apply(.offline)
            return
        }
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 2.5)
        session.dataTask(with: request) { [weak self] data, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode
            let snapshot = DroidStatusParser.parse(statusCode: code, data: data)
            DispatchQueue.main.async {
                guard let self, self.refreshGeneration == generation else { return }
                self.apply(snapshot)
            }
        }.resume()
    }

    private func apply(_ snapshot: DroidStatusSnapshot) {
        lastSnapshot = snapshot
        stateLine.title = snapshot.stateLineTitle
        if let sense = snapshot.senseLineTitle {
            senseLine.title = sense
            senseLine.isHidden = false
        } else {
            senseLine.title = ""
            senseLine.isHidden = true
        }
        toggleItem.title = snapshot.toggleTitle
        toggleItem.isEnabled = snapshot.toggleEnabled
        parkItem.isEnabled = snapshot.parkEnabled
        centerItem.isEnabled = snapshot.centerEnabled
    }

    private func refreshPermissions() {
        let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        let camStatus = AVCaptureDevice.authorizationStatus(for: .video)
        micPermission.title = "Microphone: \(permissionLabel(micStatus))"
        cameraPermission.title = "Camera: \(permissionLabel(camStatus))"
        micPermission.state = micStatus == .authorized ? .on : .off
        cameraPermission.state = camStatus == .authorized ? .on : .off
    }

    private func permissionLabel(_ status: AVAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "Allowed"
        case .denied: return "Denied — click to open Settings"
        case .restricted: return "Restricted"
        case .notDetermined: return "Not asked yet"
        @unknown default: return "Unknown"
        }
    }

    private func postGateway(path: String, payload: [String: Any]) {
        guard let url = URL(string: gatewayOrigin + path) else { return }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10.0)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        session.dataTask(with: request) { [weak self] _, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode
            if let error {
                shellLog("[shell][droid] POST \(path) failed: \(error.localizedDescription)")
            } else {
                shellLog("[shell][droid] POST \(path) -> HTTP \(code ?? 0)")
            }
            DispatchQueue.main.async {
                self?.refresh()
            }
        }.resume()
    }

    @objc private func toggle() {
        let path = lastSnapshot.toggleEndpointPath
        postGateway(path: path, payload: ["reason": "macos_menubar"])
    }

    @objc private func parkCameraNow() {
        postGateway(path: "/v1/droid/sleep", payload: ["reason": "macos_menubar_park"])
    }

    @objc private func centerCamera() {
        postGateway(path: "/v1/embodiment/droid/act", payload: ["action": "center"])
    }

    @objc private func refreshDevices() {
        guard let url = URL(string: gatewayOrigin + "/v1/droid/devices?refresh=1") else { return }
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10.0)
        session.dataTask(with: request) { [weak self] _, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode
            if let error {
                shellLog("[shell][droid] refresh devices failed: \(error.localizedDescription)")
            } else {
                shellLog("[shell][droid] refresh devices -> HTTP \(code ?? 0)")
            }
            DispatchQueue.main.async {
                self?.refresh()
            }
        }.resume()
    }

    @objc private func openDroidView() {
        if let app {
            app.openDroidView()
            return
        }
        if let url = URL(string: ShellEnvironment.webUI().origin.string + "/droid") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func openMicSettings() { openPrivacy("Privacy_Microphone") }
    @objc private func openCameraSettings() { openPrivacy("Privacy_Camera") }

    private func openPrivacy(_ pane: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?" + pane) {
            NSWorkspace.shared.open(url)
        }
    }
}
