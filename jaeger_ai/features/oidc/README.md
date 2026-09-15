# OIDC Sign-In

Lets people sign in to the Web UI with an existing identity provider (Google,
Okta, Authentik, Keycloak) instead of a local password.

| File | What it does |
| :--- | :--- |
| `service.py` | The whole sign-in exchange, plus the allow-list check that decides who may in. |

**Turn it on:** set `JAEGER_OIDC_CLIENT_ID` and `JAEGER_OIDC_CLIENT_SECRET`.
Restrict who can sign in with `JAEGER_OIDC_ALLOW_CLAIM` and
`JAEGER_OIDC_ALLOW_VALUES` (for example, claim `email` and your own address).
With no client ID set, the feature is off and the Web UI behaves as before.

**Check it works:** load the Web UI signed out — you are sent to your provider.
A user outside the allow-list is refused after authenticating, not before.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
