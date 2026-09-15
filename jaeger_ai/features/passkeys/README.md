# Passkeys

Sign in to the Web UI with Touch ID, Face ID or a hardware key instead of a
password, using the WebAuthn standard.

| File | What it does |
| :--- | :--- |
| `service.py` | Registering a new passkey, logging in with one, listing and deleting them. |

**Turn it on:** register a passkey from the Web UI's settings. Credentials are
stored in your state directory, never in this folder.

**Check it works:** sign out and sign back in with the passkey. Registered keys
are listed in settings and can be removed there.

*Needs the `cryptography` package. Tests skip themselves when it is absent.*

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
