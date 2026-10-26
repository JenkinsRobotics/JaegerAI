# bridge — monolith break-out module (split plan, NOT yet cut)

Original file: jaeger_ai/interfaces/bridge.py, 220,695 bytes, 4,741 lines. Headless NDJSON stdio bridge — the agent pipeline behind the native app. Swift shell spawns `jaeger bridge`, exchanges newline-delimited JSON over stdin/stdout, same agent turn the TUI runs, one hop out of process.

Hardening in its docstring: FAST READY (ready when transport is usable, model boots on background thread, agent_state frames booting -> ready|failed), worker-thread turns (stdin loop never blocks on a turn, respond/quit stay processable mid-turn), interactive permissions (tier-2+ approval frames, once/always/deny, always persists to <instance>/permissions.json, timeout => deny, fail-safe), clean-exit `bye` marker, stdout carries ONLY protocol JSON (logs to stderr).

Proposed split, keeping the wire protocol EXACTLY v1:
- bridge-transport — emit, stdin loop, stdout/stderr separation, pidfile.
- bridge-boot — layout resolution, model boot background thread, ready/failed frames.
- bridge-turns — worker-thread turns, queue/block semantics, chat turns.
- bridge-permissions — BridgeConfirmationProvider, approval frames, respond handling.

Rules: protocol lives in jaeger_os/contract/protocol.py + protocol_v1_fixtures.json, the single wire contract. Do NOT change frame names, protocol version, timeout-deny, or bye semantics in the split. Test against the v1 fixtures after each group.

Overlap with jaeger-agent: bridge drives the agent turn, it does not replace jaeger-agent's loop. Do NOT copy jaeger-agent's loop into this module, and do NOT edit jaeger-agent.
