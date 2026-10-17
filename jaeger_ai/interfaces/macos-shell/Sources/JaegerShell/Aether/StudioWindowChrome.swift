// Derived from AetherStudio @ ece0209 — core/ui/native/StudioWindowChrome.swift
// Copyright (c) Jonathan Jenkins and Jenkins Robotics (AetherStudio). Licensed under the Apache License 2.0
// (see LICENSES/AetherStudio-Apache-2.0.txt). Modified for Jaeger by Jenkins Robotics on 2026-10-17:
// unmodified (verbatim copy below this header).
// Shared macOS presentation adapter. All product UI remains in the web app.
import AppKit
import WebKit

final class StudioWindowChrome: NSObject, WKScriptMessageHandler {
    private weak var window: NSWindow?

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
