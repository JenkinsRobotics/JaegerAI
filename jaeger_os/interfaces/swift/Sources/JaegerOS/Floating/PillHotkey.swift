//
//  PillHotkey.swift
//  JaegerOS / Floating
//
//  Global hotkey registration for ⌥Space → toggle the pill.
//
//  Why Carbon ``RegisterEventHotKey`` (HIToolbox) instead of
//  ``NSEvent.addGlobalMonitorForEvents``:
//
//    - Global NSEvent monitors REQUIRE the operator to grant the
//      app Accessibility permission (System Settings ▸ Privacy &
//      Security ▸ Accessibility).  That's a friction wall on first
//      launch.
//    - Carbon's hotkey API has been the canonical Mac shortcut
//      registration since 10.0, requires zero permissions, and the
//      modern AppKit / Cocoa app delegate flow (NSApp + RunLoop)
//      dispatches its events for free.  Apple has not deprecated
//      it despite the broader Carbon retirement — it's the same
//      mechanism Spotlight / Alfred / Raycast use.
//
//  Scope: ⌥Space only for 0.3.0.  When the operator's first session
//  shows the binding clashes with something else, this file gains a
//  customisation surface (user-preference key + re-registration
//  helper); not needed for the testing-things-out pass.
//

import AppKit
import Carbon.HIToolbox

@MainActor
final class PillHotkey {

    static let shared = PillHotkey()

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandlerRef: EventHandlerRef?
    private var handler: (() -> Void)?

    private init() {}

    /// Register ⌥Space → ``handler``.  Idempotent — re-registering
    /// replaces the previous handler so SwiftUI scene churn doesn't
    /// pile up listeners.  Either Carbon call failing unwinds state
    /// fully so a partial registration can't leave a stale handler
    /// behind with no hotkey driving it.
    func register(_ handler: @escaping () -> Void) {
        unregister()
        self.handler = handler

        // Install the application-level event handler that Carbon
        // dispatches hotkey events through.  ``InstallEventHandler``
        // routes kEventHotKeyPressed events into our trampoline.
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )
        let context = Unmanaged.passUnretained(self).toOpaque()
        let installStatus = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, eventRef, userData -> OSStatus in
                guard let userData,
                      let eventRef
                else { return noErr }
                let me = Unmanaged<PillHotkey>
                    .fromOpaque(userData)
                    .takeUnretainedValue()
                // Pull the hotkey id out and validate it before
                // dispatching.  A future multi-hotkey pass could
                // share this same handler, in which case the id
                // discriminator is what tells events apart; today
                // we only trust events whose signature matches the
                // ``"JROS"`` four-char code we registered with.
                var hotKeyID = EventHotKeyID()
                let paramStatus = GetEventParameter(
                    eventRef,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &hotKeyID
                )
                guard paramStatus == noErr,
                      hotKeyID.signature == OSType(fourCharCode("JROS")),
                      hotKeyID.id == 1
                else {
                    return noErr  // not our event, but don't fail Carbon
                }
                Task { @MainActor in me.handler?() }
                return noErr
            },
            1,
            &eventType,
            context,
            &eventHandlerRef
        )
        guard installStatus == noErr else {
            NSLog("[JaegerOS][hotkey] InstallEventHandler FAILED: \(installStatus)")
            eventHandlerRef = nil
            self.handler = nil
            return
        }

        // ⌥Space — keyCode 49 is Space; ``optionKey`` (= 2048) is
        // the Carbon modifier mask for Option.
        var ref: EventHotKeyRef?
        let id = EventHotKeyID(
            signature: OSType(fourCharCode("JROS")),
            id: UInt32(1)
        )
        let status = RegisterEventHotKey(
            UInt32(kVK_Space),
            UInt32(optionKey),
            id,
            GetApplicationEventTarget(),
            0,
            &ref
        )
        if status == noErr {
            hotKeyRef = ref
            NSLog("[JaegerOS][hotkey] ⌥Space registered")
            return
        }

        // Conflict (-9878 = eventHotKeyExistsErr → Spotlight /
        // Alfred / Raycast / another app owns ⌥Space) or any other
        // failure: tear down the event handler we just installed
        // and clear ``handler`` so the singleton isn't sitting on
        // dead state.
        NSLog("[JaegerOS][hotkey] ⌥Space registration FAILED: \(status)"
              + " (likely already bound by another app — the menu-bar"
              + " ‘Open Pill Launcher’ item still works)")
        if let eventHandlerRef {
            RemoveEventHandler(eventHandlerRef)
            self.eventHandlerRef = nil
        }
        self.handler = nil
    }

    /// Unregister + tear down.  Called on app shutdown; also useful
    /// when re-registering with a different combo.
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
    }
}

/// Carbon expects a 4-byte ``OSType`` for hotkey signatures so
/// dispatchers can recognise their own events.  Encode the ASCII
/// "JROS" tag into a big-endian UInt32 for that purpose.
private func fourCharCode(_ s: StaticString) -> UInt32 {
    var result: UInt32 = 0
    let bytes = Array(s.description.utf8.prefix(4))
    for byte in bytes {
        result = (result << 8) | UInt32(byte)
    }
    return result
}
