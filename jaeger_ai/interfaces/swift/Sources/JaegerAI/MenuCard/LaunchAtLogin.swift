//
//  LaunchAtLogin.swift
//  JaegerAI / MenuCard
//
//  SMAppService.mainApp integration for "Start Jaeger at login".
//  Default: ON per requirement 4.
//

import Foundation
import ServiceManagement

@MainActor
final class LaunchAtLogin: ObservableObject {
    static let shared = LaunchAtLogin()

    @Published var isEnabled: Bool = false {
        didSet {
            guard oldValue != isEnabled else { return }
            setLaunchAtLogin(enabled: isEnabled)
        }
    }

    private init() {
        refresh()
        // If not registered yet, default to ON per requirement 4
        if #available(macOS 13.0, *) {
            if SMAppService.mainApp.status == .notRegistered {
                do {
                    try SMAppService.mainApp.register()
                    refresh()
                } catch {
                    NSLog("[LaunchAtLogin] Default registration failed: \(error)")
                }
            }
        }
    }

    func refresh() {
        if #available(macOS 13.0, *) {
            let status = SMAppService.mainApp.status
            isEnabled = (status == .enabled)
        }
    }

    private func setLaunchAtLogin(enabled: Bool) {
        if #available(macOS 13.0, *) {
            do {
                if enabled {
                    if SMAppService.mainApp.status != .enabled {
                        try SMAppService.mainApp.register()
                    }
                } else {
                    if SMAppService.mainApp.status == .enabled {
                        try SMAppService.mainApp.unregister()
                    }
                }
            } catch {
                NSLog("[LaunchAtLogin] Failed to \(enabled ? "register" : "unregister"): \(error)")
            }
            refresh()
        }
    }
}
