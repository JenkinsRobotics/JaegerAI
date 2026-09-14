# Roundtable / native adapter repair — 2026-09-06

Follow-up: [live container workspaces and Mac connectivity](integrations/agent_workspaces/README.md)
now provides direct read/write GitHub mounts and authenticated live host inventory
to Hermes and OpenClaw. The earlier container-mirror limitation below is superseded
for `/mnt/host/GitHub/JaegerAI`; see the follow-up for remaining privacy approvals.

Scope: defects reproduced from WebUI session `d51f19429096` and its attached
repair prompt. All implementation changes are in this repository. No model
selections, credentials, profile names, ports, container mounts, or launchd
configuration were changed.

## Findings and fixes

| Status | Source / defect | Root cause and repair |
| --- | --- | --- |
| Verified | `jaeger_ai/interfaces/mcp_server.py`, synchronous tools | The installed MCP SDK invokes synchronous tool functions inline. A blocked chat prevented unrelated initialization. Registered tools now await worker-thread execution, preserving their signatures and MCP HTTP/SSE transport. |
| Verified | `hermes_profile_adapters/roundtable.py`, `_parallel_turns` | Timed-out workers retained the mutable result dictionary and output callback, so late answers appeared beneath later-round headings. Closing a round now seals its results and output; callers receive a snapshot. A still-running local member worker prevents another dispatch to that same native session. The chair uses the same bounded mechanism. |
| Verified | Adapter timeout defaults | Missing environment settings previously meant unlimited waits. Jaeger, OpenClaw, and Roundtable now default to 300 seconds, with finite-positive validation. Existing deployment overrides remain authoritative: Roundtable and OpenClaw use 90 seconds; Jaeger's previously unset setting now uses 300. These are configurable limits, not evidence of an outage. |
| Verified | Jaeger / Roundtable automatic chat retries | A lost response does not establish that the native agent did not execute its tools. Dispatched chat turns are no longer automatically replayed. Jaeger may retry initialization up to three times and refresh a rejected stale MCP session. Jaeger and OpenClaw briefly fail fast after repeated transport failures using circuit breakers. |
| Verified | `jaeger.py`, MCP response handling | Plain JSON responses are accepted alongside SSE. JSON-RPC errors and missing responses are raised rather than mistaken for successful tool results. Initialization failures are no longer swallowed. |
| Verified | `roundtable.py`, failure detection | Arbitrary prose containing “error” or “no response” could be classified as failure. Local failures now carry error-category metadata; legacy native error strings use anchored prefixes. A normal answer discussing an earlier error is not rejected. |
| Verified | `roundtable.py`, peer prompts | Full answers were repeatedly embedded in discussion and synthesis prompts. Each peer transcript now has an 18,000-character budget; copied user requests have a 12,000-character budget. Truncation is disclosed and cannot establish agreement. Original native-session input and displayed answers are not truncated by these helpers. |
| Verified | `roundtable.py`, synthesis instructions | The chair is explicitly prohibited from treating one of three participants as a majority, treating timeouts as outages, or relabeling another member's evidence as its own verification. All-failed rounds produce no consensus. These are model instructions, not a formal vote validator. |
| Verified | `roundtable.py`, canonical source path | The full suite found a hard-coded developer home path. Deployment context now derives the actual source path from `__file__` and warns that a container mirror cannot verify the host checkout. |
| Verified | `scripts/run-host-capability-server.py`, donor paths | The full suite also found two hard-coded home paths in the existing launcher. They now derive from the sibling ARES checkout relative to this repository, resolving to exactly the same paths on this machine. Donor code and capability behavior are unchanged. |
| Verified, already fixed before this repair | Import-time Jaeger MCP initialization | Current source already initializes lazily. Added a regression test that fails if importing the module performs network I/O. |

Adapter paths in the table are beneath `jaeger_ai/interfaces/`. Shared transport
policy lives in `hermes_profile_adapters/resilience.py`.

## Verification receipts

- New regression file: `dev/tests/jaeger_ai/interfaces/test_adapter_resilience.py`.
  Its 18 tests passed, including an actual loopback MCP HTTP/SSE server: a second
  client initializes and lists tools while the first client's chat is deliberately
  blocked. Other cases cover late results, busy sessions, bounded context,
  failure classification, stale sessions, circuit recovery, and OpenClaw HTTP 504.
- Live MCP: initialization on `127.0.0.1:8792/mcp` took **0.011 seconds while a
  real Jaeger chat was still running**. That chat did not complete within the
  concurrency probe's separate 60-second completion budget. Transport responsiveness
  passed; fast model completion did not.
- `.venv/bin/python scripts/verify-agent-webui.py --url http://100.74.2.15:8787`
  exited 0. Two-turn check-word tests passed for Hermes/default (`d9061afbe0cd`),
  Jaeger (`d886dd5b9a26`), OpenClaw (`4b1921062a54`), and Roundtable
  (`a0a81cf4aa5a`). This verifies routing and session recall, not every member's
  success in every discussion phase.
- Manual inspection of the saved Roundtable smoke transcript: all three initial
  answers arrived; Jaeger's discussion exceeded 90 seconds; no late answer was
  injected into the summary. OpenClaw chaired, explicitly withheld unanimity, and
  recorded the timeout without diagnosing an outage. A subsequent `/quick @jaeger`
  turn recalled the check word.
- Changed Python modules compile; `git diff --check` passes.

Full-suite receipt (fixed ordering):

```text
.venv/bin/python -m pytest dev/tests -x -vv -p no:randomly -o faulthandler_timeout=30 --tb=short
3567 passed, 11 skipped, 1 warning in 96.23s
```

The health supervisor was temporarily unloaded during the suite so its regular
health-file writes would not trigger the live-state isolation guard. A shell EXIT
trap restored it, and `launchctl list` confirmed it running afterward. No test
isolation checks were disabled. The warning is Discord's Python `audioop`
deprecation. A preliminary randomized attempt stalled and was interrupted; both
the fixed-order run above and the final repeatable randomized run completed:

```text
.venv/bin/python -m pytest dev/tests -x -vv --randomly-seed=20260906 -o faulthandler_timeout=30 --tb=short
3567 passed, 11 skipped, 1 warning in 103.48s
```

Final probes after deploying the changed adapter code:

```text
127.0.0.1:8642/health     HTTP 200 0.007s {"ok":true,"status":"ready"}
127.0.0.1:8643/health     HTTP 200 0.007s {"ok":true,"status":"ready","agents":["hermes","jaeger","openclaw"]}
192.168.64.1:8644/health  HTTP 200 0.012s {"ok":true,"status":"ready"}
100.74.2.15:8787/health   HTTP 200 0.091s {"status":"ok","active_streams":0,"active_runs":0}
```

The same three adapter health routes also returned HTTP 200 before deployment.

## Deployment and restart procedure

The inspected launchd jobs execute repository modules with the repository's
`.venv/bin/python`, not historical `~/workspace/*adapter.py` scripts. Hermes WebUI
and OpenClaw run in separate Apple containers; the adapters run on macOS.

After checking that no wanted chat is active, restart only affected services:

```sh
launchctl kickstart -k gui/$(id -u)/com.jenkinsrobotics.jaeger-mcp-http
launchctl kickstart -k gui/$(id -u)/com.jenkinsrobotics.jaeger-hermes-adapter
launchctl kickstart -k gui/$(id -u)/com.jenkinsrobotics.roundtable-hermes-adapter
launchctl kickstart -k gui/$(id -u)/com.jenkinsrobotics.openclaw-hermes-adapter
curl -fsS --max-time 5 http://127.0.0.1:8642/health
curl -fsS --max-time 5 http://127.0.0.1:8643/health
curl -fsS --max-time 5 http://192.168.64.1:8644/health
```

OpenClaw's adapter binds the Apple-container host interface, not loopback.
HTTP health only establishes listener health; use the WebUI smoke for chat routing.

## Remaining limits / not claimed fixed

- Jaeger still has long native turn latency under concurrent load. Transport
  starvation and late-output corruption are fixed; universal sub-90-second
  responses are not established.
- Timeout/cancel does not guarantee native tool work stopped. The same-session
  guard lasts while the adapter's worker remains alive; it cannot track native
  work after a transport disconnect. Automatic replay is intentionally avoided.
- Streaming here emits completed member answers as they arrive, not native token
  deltas. Full native cancellation, durable per-member retry coordination, and
  formal structured voting remain separate work.
- Container `/workspace/GitHub/JaegerAI` is still a stale mirror. This repair does
  not replace mounts or grant permissions; authorized host workspace tools must
  be used to inspect the canonical host checkout.
- No assertion that per-chat model overrides are honored by every native adapter;
  provider settings and model selection behavior were not changed in this repair.
