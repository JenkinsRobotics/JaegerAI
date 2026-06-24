# JROS client protocol

The single wire contract a surface uses to drive the JROS agent
out-of-process. **Transports, not endpoints**: one protocol, many
transports (stdio today via `jaeger bridge`; WebSocket later by bridging
the in-process bus). Source of truth: [`jaeger_os/protocol.py`](../../jaeger_os/protocol.py).
Reference client: [`jaeger_os/client.py`](../../jaeger_os/client.py) (`JrosClient`).

`PROTOCOL_VERSION = "1"`.

## Transport

NDJSON — one JSON object per line. Over stdio: the client spawns
`jaeger bridge` (or `python -m jaeger_os.interfaces.bridge`), writes ops to
the child's stdin, reads frames from its stdout. Boot/model logs go to
stderr and never touch the protocol stream. The instance is selected via
`JAEGER_INSTANCE_NAME` / `JAEGER_INSTANCE_DIR` in the child's env.

## Client → agent (ops)

| op | fields | meaning |
|----|--------|---------|
| `send` | `text`, `session?` | run one turn in `session` (default conversation) |
| `respond` | `id`, `answer` | answer a mid-turn `request` with matching `id` |
| `quit` | — | graceful shutdown |

## Agent → client (frames)

| type | fields | meaning |
|------|--------|---------|
| `ready` | `instance`, `model?` | boot complete; first frame |
| `state` | `busy`, `session?` | `true` brackets a turn (thinking), `false` ends it |
| `tool` | `name`, `phase` (`start`/`done`/`error`), `elapsed_s`, `session?` | live tool activity |
| `request` | `id`, `kind` (`approval`/`clarify`/`secret`), `prompt`, `options[]`, `session?` | mid-turn prompt — answer with a `respond` op |
| `reply` | `text`, `error?`, `session?` | the turn's answer; ends the turn |
| `fatal` | `error` | boot failed; the bridge exits |

Events are tagged with `session` so one agent fans out to multiple
conversations/windows; a client renders only its own.

## Reference flow

```
→ {"type":"ready","instance":"jros-dev","model":"gemma-4-12B"}
← {"op":"send","text":"search the web","session":"a1b2"}
→ {"type":"state","busy":true,"session":"a1b2"}
→ {"type":"tool","name":"web_search","phase":"start","elapsed_s":0.0,"session":"a1b2"}
→ {"type":"tool","name":"web_search","phase":"done","elapsed_s":1.2,"session":"a1b2"}
→ {"type":"reply","text":"...","error":null,"session":"a1b2"}
→ {"type":"state","busy":false,"session":"a1b2"}
```

## Using the SDK

```python
from jaeger_os.interfaces.client import JrosClient

with JrosClient(env={"JAEGER_INSTANCE_NAME": "jros-dev"}) as agent:
    out = agent.turn("hello",
                     on_event=lambda f: print(f["type"]),
                     on_request=lambda f: "allow")
    print(out["text"])
```

Other-language clients implement the same NDJSON frames (the Swift app is
this client in Swift). The in-process surfaces (PySide6/TUI) consume the
same shapes as bus messages via `protocol.event_to_frame`.

## Status / follow-ons

- stdio transport: shipped. WebSocket transport (remote/web): bridge the
  in-process bus to these frames — `event_to_frame` already maps the bus
  messages; only a socket server is missing.
- Interactive `request` over the **stdio bridge** currently surfaces the
  prompt and fails safe to deny (the bridge's stdin is synchronous); the
  in-process window answers fully. Async-stdin in the bridge unlocks the
  Swift round-trip.
