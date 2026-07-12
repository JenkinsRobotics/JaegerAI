//
//  SettingsView.swift
//  JaegerOS / MenuCard
//
//  The macOS Settings/Preferences window (⌘, or the menu-card gear).
//  Tabbed like the reference OneDrive prefs.
//
//  Scope note: the agent's own config (model, engine, persona, voice,
//  permissions — the ~100 fields in config.yaml/identity.yaml) is owned
//  by the Python side and edited through the PySide6 settings window /
//  ``jaeger config``.  Swift can't safely rewrite that YAML, so this
//  window covers the *app-local* prefs (TTS, launch behaviour) + About,
//  and links out for the agent config.  A later pass routes agent-config
//  edits through the bridge.
//

import SwiftUI

struct SettingsView: View {
    // The agent-centric HUD replaces the old tabbed prefs, matching the PySide6
    // agent_settings window. App prefs (below) remain reachable under "App".
    var body: some View {
        AgentSettingsHUD()
            .frame(width: 900, height: 600)
    }
}

private struct GeneralSettings: View {
    @ObservedObject private var tts = TTSManager.shared

    var body: some View {
        Form {
            Section("Voice") {
                Toggle("Auto-speak replies", isOn: $tts.autoSpeakEnabled)
                Text("Speak the agent's reply aloud after each turn.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

private struct AgentSettingsInfo: View {
    @ObservedObject private var agent = AgentBridge.shared

    var body: some View {
        Form {
            Section("Agent") {
                LabeledContent("Instance", value: agent.status?.instance
                               ?? AgentBridge.defaultInstanceName)
                LabeledContent("Model", value: agent.status?.modelName ?? "—")
                LabeledContent("Status", value: agent.isConnected ? "running" : "stopped")
            }
            Section {
                Text("Persona, model, engine, voice, and permission settings "
                     + "are owned by the agent. Edit them in the JROS chat "
                     + "app's Settings, or with `jaeger config` / "
                     + "`jaeger personality`.")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

private struct AboutSettings: View {
    var body: some View {
        VStack(spacing: 12) {
            JaegerMechIcon(size: 56)
            Text("JROS").font(.title2).bold()
            Text("Real-world local agentic agent framework")
                .font(.callout).foregroundStyle(.secondary)
            Link("github.com/JenkinsRobotics/JROS",
                 destination: URL(string: "https://github.com/JenkinsRobotics/JROS")!)
                .font(.callout)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}
