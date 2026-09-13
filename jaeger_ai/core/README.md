# core/ — Jaeger AI application services

This is the application's composition and integration layer, not a second
agent framework. JaegerOS owns the host framework; JaegerAgent owns the reusable
agent loop, tools, memory, and multimodal engine. Jaeger AI supplies application
policy, instance configuration, and adapters to those dependencies.

## Navigation

| Area | Responsibility |
|---|---|
| [mind_runtime.py](mind_runtime.py) | Construct and bind the hosted JaegerAgent runtime to the application instance |
| [mind_node.py](mind_node.py), [agent_core.py](agent_core.py) | JaegerOS node/core integration for the application's launch configurations |
| [agent_bridge.py](agent_bridge.py), [agent_observability.py](agent_observability.py) | Application bridge adapter and agent activity reporting |
| [instance/](instance/) | Instance layout, schemas, identity, migrations, and setup |
| [settings/](settings/) | Application settings catalog and shared settings access |
| [models/](models/) | Application model discovery, selection, and provider adapters |
| [runtime/](runtime/) | Application lifecycle helpers, readiness, usage, and process services |
| [diagnostics/](diagnostics/) | Doctor checks, environment probes, and macOS permission checks |
| [safety/](safety/) | Application-side skill safety scanning |
| [bench/](bench/) | Benchmark runners used by application commands |
| [sessions.py](sessions.py), [people.py](people.py) | Application session and people services |
| [messages.py](messages.py), [windowed.py](windowed.py), [version_check.py](version_check.py) | App messages, windowed composition, and update checks |

[context.py](context.py) is an intentional compatibility alias to
`jaeger_agent.core.workspace`. It preserves the same module object and bound
instance state; replacing it with copied globals would create divergent state.

Keep new app-owned services in the existing responsibility folders where they
fit. Do not move reusable agent mechanisms back into this package. See the
[package layout](../README.md) and [agent documentation ownership](../../dev/docs/MOVED_TO_JAEGER_AGENT.md).
