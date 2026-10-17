// Derived from AetherStudio @ ece0209 — core/ui/native/StudioWindowChrome.swift
// Copyright (c) Jonathan Jenkins and Jenkins Robotics (AetherStudio). Licensed under the Apache License 2.0
// (see LICENSES/AetherStudio-Apache-2.0.txt).
// Modified by Jenkins Robotics, 2026-10-17: the aetherWindow handler accepts messages only from the
// main frame of the configured 127.0.0.1 WebUI origin (`allowedOrigin`, checked with
// JaegerShellCore.WindowChromePolicy) and logs/counts rejections. Everything else is verbatim.
// Shared macOS presentation adapter. All product UI remains in the web app.
import AppKit
import JaegerShellCore
import WebKit

final class StudioWindowChrome: NSObject, WKScriptMessageHandler {
    private weak var window: NSWindow?
    /// Jenkins Robotics 2026-10-17: the only origin whose main frame may drive the window.
    var allowedOrigin: LoopbackOrigin?
    private(set) var accepted = 0
    private(set) var rejections: [String] = []

    func install(in configuration: WKWebViewConfiguration) {
        configuration.userContentController.add(self, name: "aetherWindow")
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: """
                document.documentElement.dataset.aetherNativeWindow = "true";
                document.addEventListener("mousedown", (event) => {
                  if (event.button !== 0) return;
                  const target = event.target instanceof Element ? event.target : null;
                  if (!target?.closest("[data-aether-window-drag-region]")) return;
                  if (target.closest("button, input, select, textarea, a, [role='button'], [role='tab'], [role='menuitem']")) return;
                  window.webkit?.messageHandlers?.aetherWindow?.postMessage({
                    action: event.detail > 1 ? "doubleClick" : "drag"
                  });
                }, true);
                """,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
    }

    func attach(to window: NSWindow) {
        self.window = window
        window.styleMask.insert(.fullSizeContentView)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenPrimary]
        window.minSize = NSSize(width: 900, height: 600)
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        // Jenkins Robotics 2026-10-17: main frame + configured loopback origin only.
        let info = message.frameInfo
        let frame = BridgeFrame(isMainFrame: info.isMainFrame, scheme: info.securityOrigin.protocol,
                                host: info.securityOrigin.host, port: info.securityOrigin.port)
        guard WindowChromePolicy.accepts(frame, allowed: allowedOrigin) else {
            rejections.append(frame.description)
            shellLog("[shell][aetherWindow] rejected \(frame.description)")
            return
        }
        accepted += 1
        guard
            message.name == "aetherWindow",
            let payload = message.body as? [String: Any],
            let action = payload["action"] as? String,
            let window
        else { return }

        if action == "drag", let event = NSApp.currentEvent {
            window.performDrag(with: event)
            return
        }
        guard action == "doubleClick" else { return }
        switch UserDefaults.standard.string(forKey: "AppleActionOnDoubleClick")?.lowercased() {
        case "minimize":
            window.miniaturize(nil)
        case "none":
            break
        default:
            window.performZoom(nil)
        }
    }

}
