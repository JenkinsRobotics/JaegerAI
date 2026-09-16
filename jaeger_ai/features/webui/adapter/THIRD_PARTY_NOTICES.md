# Third-party notices

JaegerAI's first-party WebUI contains source derived from Hermes WebUI.
Hermes WebUI is copyright 2025 Hermes Web UI Contributors and licensed under
the MIT License. The complete license text is included at
`jaeger_ai/features/webui/HERMES_WEBUI_LICENSE`; upstream is
https://github.com/nesquena/hermes-webui.

The derived source supplies the browser workbench and translates its
runner-local chat and scheduler interfaces onto JaegerAI's versioned bridge.
Jaeger owns the
agent runtime, sessions, tools, approvals, heartbeat, schedules, and all state
under `~/.jaeger`. Hermes Agent is not included or imported by the Jaeger
runtime or its WebUI launch path.
