# Third-party notices

JaegerAI pins the `JenkinsRobotics/hermes-webui` fork under
`vendor/hermes-webui`. Hermes WebUI is copyright 2025 Hermes Web UI
Contributors and licensed under the MIT License. The complete license text is
included at `vendor/hermes-webui/LICENSE`; upstream is
https://github.com/nesquena/hermes-webui.

The fork supplies the browser workbench and translates its runner-local chat
and scheduler interfaces onto JaegerAI's versioned bridge. Jaeger owns the
agent runtime, sessions, tools, approvals, heartbeat, schedules, and all state
under `~/.jaeger_ai`. Hermes Agent is not included or imported by the Jaeger
runtime or its WebUI launch path.
