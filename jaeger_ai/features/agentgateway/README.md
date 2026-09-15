# Agentgateway

Installs and runs the public `agentgateway` binary, which exposes Jaeger's tools
to outside programs over two standard protocols: MCP on port **8811** and A2A on
port **8812**.

**This is not the Jaeger Gateway.** The Jaeger Gateway is a different process
(`jaeger_ai/core/gateway/`, port 8810) that owns chat sessions. This folder only
manages the third-party binary. The two used to both be called "gateway", which
is why this one was renamed.

| File | What it does |
| :--- | :--- |
| `service.py` | Starts, stops and reports on the binary. |
| `install.py` | Downloads and installs the binary if it is missing. |
| `config.py` | Writes the YAML config the binary reads. |
| `constants.py` | Port numbers and default paths. |
| `cli.py` | Backs the `jaeger gateway` command. |

**Turn it on:** `jaeger gateway start` (`jaeger gateway daemon` is the *other*
gateway — see the warning above).

**Check it works:** `jaeger gateway status`, or `curl http://127.0.0.1:8811/mcp`.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
