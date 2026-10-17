// Hotkey.swift — JaegerShell global hotkey.
// Adapted from Jaeger's own jaeger_ai/interfaces/swift/Sources/JaegerAI/Floating/PillHotkey.swift
// (Jenkins Robotics, same repository; copied, the original is unchanged). Changes: renamed,
// configurable key/modifiers (HotkeySpec from the JaegerHotkey Info.plist key), returns the
// Carbon status, main-queue dispatch instead of @MainActor Task, shell log tags.
//
// Carbon RegisterEventHotKey needs no Accessibility permission (unlike NSEvent global monitors).

import AppKit
import Carbon.HIToolbox
import JaegerShellCore

final class Hotkey {
    static let shared = Hotkey()

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandlerRef: EventHandlerRef?
    private var handler: (() -> Void)?
    private(set) var registered: HotkeySpec?
    private(set) var lastStatus: OSStatus = noErr

    private init() {}

    /// Register `spec` → `handler`. Idempotent. Returns the Carbon status (0 = registered).
    @discardableResult
    func register(_ spec: HotkeySpec, _ handler: @escaping () -> Void) -> OSStatus {
        unregister()
        self.handler = handler

        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let context = Unmanaged.passUnretained(self).toOpaque()
        let installStatus = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, eventRef, userData -> OSStatus in
                guard let userData, let eventRef else { return noErr }
                let me = Unmanaged<Hotkey>.fromOpaque(userData).takeUnretainedValue()
                var hotKeyID = EventHotKeyID()
                let paramStatus = GetEventParameter(
                    eventRef, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                    nil, MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)
                guard paramStatus == noErr, hotKeyID.signature == hotkeySignature, hotKeyID.id == 1 else {
                    return noErr
                }
                DispatchQueue.main.async { me.handler?() }
                return noErr
            },
            1, &eventType, context, &eventHandlerRef)
        guard installStatus == noErr else {
            shellLog("[shell][hotkey] InstallEventHandler failed: \(installStatus)")
            eventHandlerRef = nil
            self.handler = nil
            lastStatus = installStatus
            return installStatus
        }

        var ref: EventHotKeyRef?
        let id = EventHotKeyID(signature: hotkeySignature, id: 1)
        let status = RegisterEventHotKey(spec.keyCode, spec.modifiers, id, GetApplicationEventTarget(), 0, &ref)
        lastStatus = status
        if status == noErr {
            hotKeyRef = ref
            registered = spec
            shellLog("[shell][hotkey] \(spec.label) registered (\(spec.name))")
            return status
        }
        // -9878 = eventHotKeyExistsErr: another app owns the combo. The status-item menu still works.
        shellLog("[shell][hotkey] \(spec.label) registration failed: \(status) (status item still works)")
        if let eventHandlerRef {
            RemoveEventHandler(eventHandlerRef)
            self.eventHandlerRef = nil
        }
        self.handler = nil
        return status
    }

    func unregister() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
            self.hotKeyRef = nil
        }
        if let eventHandlerRef {
            RemoveEventHandler(eventHandlerRef)
            self.eventHandlerRef = nil
        }
        handler = nil
        registered = nil
    }
}

/// "Jsh1" as a big-endian OSType (distinct from the old app's "Jaeg" signature).
private let hotkeySignature: OSType = {
    var result: UInt32 = 0
    for byte in "Jsh1".utf8 { result = (result << 8) | UInt32(byte) }
    return result
}()
