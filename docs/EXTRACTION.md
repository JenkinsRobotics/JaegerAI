# JaegerAgent extraction plan

The extraction is organized around ownership, not file count. A component
moves only when it can run without importing JaegerAI.

## Ownership boundary

| JaegerAgent (reusable module) | JaegerAI (application) |
| --- | --- |
| Agent runtime and event protocols | Desktop/TUI/voice surfaces |
| Session-aware bus bridge | Installer, updater, and CLI product flow |
| Shared mind messages | Default model and provider configuration |
| Engine-neutral turn loop | Bundled skills, tools, memory, and characters |
| Model/tool adapter interfaces | Product permission and autonomy defaults |
| `slot: mind` node | Compatibility adapter during migration |

JaegerAgent depends on JaegerOS. JaegerAI depends on JaegerAgent. JaegerAgent
must never import JaegerAI.

MCP can expose tools or connect remote processes, but it is an edge adapter.
The local module uses JaegerOS topics, tools, and capabilities directly.

## Completed milestones

1. **Boundary** — public runtime protocol, messages,
   event sink, bridge, module manifest, and mind node. JaegerAI `0.10` runs its
   real `AgentCore` through this bridge using a compatibility runtime.
2. **Loop kernel** — moved the engine-neutral iteration/backstop/interrupt
   behavior with its existing deterministic tests.
3. **Provider interfaces** — moved base message/tool-call types and adapter
   contracts; concrete product configuration remains in JaegerAI.
4. **Tool execution** — moved generic JaegerOS tool dispatch and capability
   access. JaegerAI keeps its product-specific tool bundle.
5. **Sessions and context** — moved portable history/context services behind
   explicit storage interfaces.
6. **Remove duplicate implementation** — JaegerAI imports the completed package
   and contains no second agent-loop implementation. Thin import-path shims remain
   for 0.9 callers and contain no runtime logic.

The extracted kernel is now covered directly in JaegerAgent; JaegerAI retains
integration tests for its injected product behavior and end-to-end chat path.
