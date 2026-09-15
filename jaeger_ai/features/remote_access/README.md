# Remote Access

Decides whether a request arriving from outside this machine is allowed in. Built
for Tailscale, where your devices share a private network.

| File | What it does |
| :--- | :--- |
| `policy.py` | Returns an `AccessDecision` — allow or deny — for each request. |

**Turn it on:** set `JAEGER_REMOTE_TRUSTED_NETWORKS` to the networks you trust,
and `JAEGER_REMOTE_ACCESS_TOKEN` if you want a shared secret as well. Unset, only
this machine can connect.

**Check it works:** open the Web UI from your phone on the same Tailscale
network. From an untrusted network the request is refused.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
