# Shared Hermes WebUI profiles

JaegerAI owns the adapters used by the shared Hermes WebUI profiles:

- `jaeger` routes browser turns to Jaeger's MCP capability gateway.
- `openclaw` routes browser turns to OpenClaw's authenticated chat endpoint.
- `roundtable` behaves like a streamed group chat: Jaeger, Hermes, and OpenClaw
  answer concurrently, completed answers appear immediately, one concurrent
  discussion round follows, and Jaeger synthesizes a labeled consensus. If
  Jaeger cannot synthesize, OpenClaw is the consensus fallback. A slow or failed
  member is shown explicitly without preventing the rest of the table from
  continuing.

Each Roundtable WebUI session owns three stable member-session identifiers.
Jaeger and OpenClaw receive those identifiers through the gateway session
header. Hermes uses a stable named session through `hermes chat -c NAME
--create-if-missing`, so it is a normal native Hermes conversation that can be
listed and resumed. The three contexts survive debate phases, later user
messages, and adapter restarts without leaking into another table.

Roundtable has no default member deadline. Native sessions are allowed to
finish normally, matching a resumed one-on-one WebUI conversation. Deployments
that require a ceiling may explicitly set `ROUNDTABLE_MEMBER_TIMEOUT`; the
Jaeger and OpenClaw upstream adapters likewise accept
`JAEGERS_ADAPTER_REQUEST_TIMEOUT` and `OPENCLAW_ADAPTER_REQUEST_TIMEOUT`.

## Turn modes and mentions

Roundtable defaults to `ask`: every member answers concurrently, followed by
one discussion round and a strict decision summary. A message may start with
`/ask`, `/collaborate`, `/quick`, `/review`, or `/vote`. Collaboration, review,
and voting language is also detected when no prefix is supplied.

Use `@jaeger`, `@hermes`, `@openclaw`, or `@all` to select participants.
`/quick` chooses one best-suited member when no single mention is supplied.

Operational requests require members to label claims as `[Verified]`,
`[Reported]`, `[Inferred]`, or `[Unknown]`. The rotating chair must keep
unanimous agreement, majority positions, minority objections, evidence, and
unknowns separate. Timeouts may not be described as outages without a concrete
health check.

The source lives in `jaeger_ai/interfaces/hermes_profile_adapters/`. Generated
LaunchAgents and Hermes profile configuration remain machine-local runtime
state; no adapter source code is copied into `~/workspace`.

Install or repair all three services:

```bash
python -m jaeger_ai.interfaces.hermes_profile_adapters.setup install
```

Check their launchd state:

```bash
python -m jaeger_ai.interfaces.hermes_profile_adapters.setup status
```

The default bridge address is `192.168.64.1`, the macOS host address visible
from Apple containers. Override it with `--bridge-host` when the container
network uses another stable host address.

Credentials are read from local environment/token files and are never stored
in this package. Jaeger and Roundtable read `MCP_ARES_HOST_API_KEY` from the
Jaeger Hermes profile `.env` when no explicit adapter environment variable is
set. OpenClaw reads `~/.ares/openclaw/gateway.token`.

The temporary common model default is `glm-5.3-flash:cloud` through Ollama.
Installation applies it to the three WebUI profiles, Jaeger's native external
model configuration, and OpenClaw's native model provider configuration. The
Roundtable prompt also identifies the canonical JaegerAI adapter source so
members do not mistake obsolete scripts in `~/workspace` for deployed code.

## Ollama thinking and usage

The Ollama-compatible adapter requests the streamed usage trailer supported by
current Ollama releases. Jaeger persists provider-reported totals in the
instance's `logs/usage.json` under `models` and shows them with `/usage`:
calls, prompt tokens, cached prompt tokens, and completion tokens. Completion
tokens can include reasoning that was not rendered in the answer, which is why
the provider total is preferable to estimating from visible text.

Ollama's native API accepts `think: true` or an effort level such as `low`,
`medium`, `high`, or `max` on models that support those levels. The shared
Hermes profiles currently request high reasoning effort; GLM 5.3 Flash is the
temporary default for all three agents.

These counters are local operational telemetry. They cover calls routed
through Jaeger's adapter and must not be treated as the authoritative Ollama
Cloud balance, especially when Hermes or OpenClaw call Ollama independently.
Use the Ollama account usage page for exact charges and remaining plan credit.
Pricing is model-specific and should be read from the current model page rather
than copied into configuration.

## Shared host workspaces

The installer registers identity-scoped host workspace access for Jaeger,
Hermes, and OpenClaw. Their general artifacts remain in `~/workspace`, while
the audited host workspace tools can also reach `~/GitHub`, `~/Desktop`,
`~/Documents`, `/Volumes/Jenkins_Robotics`, and `/Volumes/Personal-Drive`.
Only those exact roots are granted; the home directory and `/Volumes` are not
granted wholesale. An offline NAS root remains registered and becomes usable
again when macOS remounts the share.

## Independent recovery supervisor

The installer also registers `com.jenkinsrobotics.agent-fabric-supervisor` as
a host LaunchAgent. It probes Jaeger, Hermes WebUI, OpenClaw, Roundtable, A2A,
and Ollama every 20 seconds. A repair requires three consecutive failures and
has a two-minute per-component cooldown, preventing restart loops caused by a
single slow response. Recovery restarts processes or containers in place and
does not delete native sessions or configuration.

Current evidence is written to `JaegerAI/.jaeger_ai/shared/health/agent-fabric.json`.
Adapter and supervisor logs live beside it under `.jaeger_ai/shared/logs/`.
OpenClaw's own token/config remain in its native `~/.ares/openclaw/` runtime
home; those are external agent state, not Jaeger implementation files. A surviving
agent with approved host command access can request one bounded repair:

```bash
python -m jaeger_ai.core.runtime.fabric_supervisor --repair openclaw
```

Valid targets are `jaeger`, `hermes`, `openclaw`, `roundtable`, `a2a`, and
`ollama`. There is intentionally no restart-everything target.
