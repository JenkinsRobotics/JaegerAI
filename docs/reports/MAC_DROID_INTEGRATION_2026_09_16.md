# Mac droid integration acceptance

Date: 2026-09-16
Scope: the permanent Jaeger agent on Matthew's Mac; Egypt is one mission, not a separate agent

## Result

The native Jaeger MCP server on `127.0.0.1:8792/mcp` and native Jaeger A2A
server on `127.0.0.1:8796` are the host agent-framework contract. The Jaeger-owned
Agentgateway ports `8811` and `8812` bridge Apple containers to those loopback backends.
Apple application actions stay behind Jaeger's controlled chat path.

## Six work items

1. **Capability inventory — complete.** MCP publishes `capability_inventory`,
   protocol endpoints, the Apple capability groups routed through `chat`, and
   the `JaegerAgentController+WorkLedger` completion authority.
2. **24/7 host and memory — verified with one external limitation.** The
   `com.jenkinsrobotics.agent-fabric-supervisor` LaunchAgent is running and its
   one-shot report marked Jaeger, Hermes Agent, OpenClaw, Roundtable, A2A, and
   Ollama healthy. Honcho configuration remains profile-isolated, but the
   configured LAN service reset the acceptance health connection and needs a
   separate service/network repair.
3. **Apple application foundation — integrated.** Calendar, Reminders,
   Contacts, Mail, Notes, Shortcuts, Files/Spotlight, media, notifications, and
   system actions remain in the existing audited tool layer. Frameworks reach
   them through Jaeger chat, preserving grants, approvals, and verification.
4. **Daily workflow protocol probes — complete.** `jaeger gateway verify`
   performs an official MCP SDK handshake, lists tools, calls bridge health and
   capability inventory, and validates the official A2A AgentCard.
5. **Framework readiness — complete for installed runtimes.** Codex and Claude
   Code report `jaeger-local` connected. Hermes Agent profiles use
   `jaeger-host`; its Mac CLI link is repaired during framework setup. OpenClaw
   uses `jaeger-host` through the Agentgateway container bridge. The generated
   contract lives at `~/.jaeger/agent-network.json`.
6. **Release gate — implemented and passing; elapsed soak remains ongoing.**
   Automated protocol/config tests, a live MCP chat, a live A2A task, server
   status, and the fabric supervisor pass. A multi-day unattended trial cannot
   be truthfully completed within this change; the verifier and supervisor
   provide its repeatable health gate.

## Live evidence

- Focused MCP, A2A, Gateway, contract, and framework configuration tests:
  **91 passed**. Authenticated supervisor probes: **3 passed**.
- Full release regression: root smoke **169 passed**, `jaeger-agent`
  **913 passed**, and JaegerOS **283 passed**.
- Native verification: MCP and A2A both `ok`; MCP registered ten tools.
- Live MCP chat with all tools disabled returned `MCP_READY`.
- Live A2A JSON-RPC task completed and returned `A2A_READY`.
- Jaeger WebUI server panel reported all eight managed services Ready.
- A clean stop/start exposed and migrated three retired Hermes WebUI container
  keys in the live instance configuration. The bridge, native MCP, Gateway,
  supervisor, Web UI, and OpenClaw then restarted cleanly.
- The macOS Swift app rebuilt and signed successfully.
- Codex and Claude Code both reported the direct Jaeger MCP server connected.
- Hermes Agent tested `jaeger-host` successfully. The OpenClaw Apple container
  remains pinned to 2026.7.1; its config producer preserves that version's
  schema while routing `jaeger-host` through the authenticated container
  bridge. Its live probe discovered 19 capabilities.

## Security and state

Framework state remains outside the repository. The two local Agentgateway
tokens were rotated without displaying their new values. The container-facing
MCP and A2A proxy routes require the private bearer; unauthenticated checks over
loopback, LAN, and Tailscale all returned HTTP 401, while authenticated
OpenClaw still discovered 19 capabilities. Only Jaeger WebUI is intended for
interactive Tailscale access.
