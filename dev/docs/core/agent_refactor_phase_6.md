# Phase 6 — completed JaegerAgent cutover

**Status:** complete in JaegerAI 0.10.

The temporary parallel agent path and its environment-variable gate have been
removed. JaegerAI now unconditionally uses the reusable `jaeger-agent` package.
The final ownership boundary is:

| JaegerAgent | JaegerAI |
|---|---|
| Turn loop and backstops | Product runtime/provider selection |
| Provider adapter contracts and implementations | Default model configuration |
| Internal messages and tool-call schemas | Product prompts, tools, skills, and memory |
| Generic JaegerOS tool dispatch | Toolsets, visibility, and autonomy policy |
| Context guard, retry helpers, interruption | UI, TUI, voice, CLI, and installer |
| Session bridge and `slot: mind` node | Runtime factory and host hooks |

JaegerAI retains thin compatibility imports under `jaeger_agent.*`, but the
implementations resolve to `jaeger_agent.*`. The small JaegerAI subclass injects
product toolset resolution, visibility, and per-turn file state; it does not
implement the loop.

## Verification gates

- JaegerAgent's direct package suite covers the extracted kernel and provider
  behavior.
- JaegerAI integration tests prove the real `AgentCore` round-trips through
  `jaeger_agent.AgentBridge` and that portable public types originate in the
  external package.
- JaegerAI's agent suite retains product-hook and end-to-end turn coverage.
- JaegerAgent has an architecture guard that rejects imports from JaegerAI.

The dependency direction is therefore fixed: `JaegerOS <- JaegerAgent <-
JaegerAI`. MCP remains an optional edge protocol rather than the internal
module boundary.
