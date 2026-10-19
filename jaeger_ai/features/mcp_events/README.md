# ARES MCP Events (isolated implementation; connection unqualified)

This optional feature is a separate loopback-only MCP 2.0 resource server. It does
not register with the existing general MCP server or change the Gateway. Importing
it has no runtime side effects. Production invocation is explicit:

```sh
python -B -m jaeger_ai.features.mcp_events /absolute/path/events-config.json
```

**Not deployed, linked, or accepted by ChatGPT.** The tests use a fake ChatGPT
receiver through injected transport. They establish local behavior, not external
TLS interoperability, account eligibility, OAuth consent, or wake-up of a real dot.

## Boundary and wire contract

`POST /mcp` requires verified OAuth on every operation, including discovery.
`GET /.well-known/oauth-protected-resource` is the sole unauthenticated endpoint.
No anonymous health, registration, token, approval or administration endpoints.
There are exactly three tools: `list_messages`, `get_thread`, `send_message`.
Writes currently allow only ARES → GrokBot messages. Gateway independently owns
caller identity, participant/thread checks and message idempotency. An incoming
OAuth bearer is never forwarded. The Gateway adapter consumes only the existing
`read_token("ares")` interface, never token provisioning or caller overrides.

The facade implements `server/discover`, `tools/list`, `tools/call`, `events/list`,
`events/subscribe`, `events/unsubscribe`. Requests use protocol `2026-07-28`, required
body `_meta` and matching HTTP metadata. Header disagreement is `-32020`; unsupported
versions are `-32022`. No legacy initialize, polling/streaming Events delivery,
server sessions, shell, files, REA, goals, handoffs or approval tools are offered.

The event is `message.created` with required `recipient: "ares"` and optional
`thread`. The callback belongs to the subscribing chat; the facade does not accept
or forge a ChatGPT conversation ID. To wake the intended conversation, the user
must subscribe **from that exact dot conversation**, after the plugin is linked.
External title/preview strings remain data. Full message text is read separately
through the scoped `get_thread` tool.

## OAuth integration and remaining work

The resource server verifies RS256 signatures using a deployment-pinned public key,
issuer, canonical resource audience, expiry, not-before, subject binding and scopes.
Only one configured owner subject maps to ARES. It rejects Gateway caller tokens
inbound and never uses OAuth tokens as downstream Gateway credentials. Required
scopes are `messages:read`, `messages:write`, and `events:read`; subscriptions require
both read scopes. The IdP must issue access tokens specifically for this resource.

Use an established OAuth 2.1 authorization server. Its authorization-code flow must
require S256 PKCE, exact approved redirect URIs, resource binding at authorization
and token exchange, consent, and supported client identification (predefined client,
CIMD or DCR). **This feature is a resource server, not an authorization server.**
It deliberately does not manufacture login, consent, PKCE, registration or refresh
token endpoints. No IdP, client, account or credentials have been registered.
Startup validates an operator-supplied public IdP metadata snapshot for S256 and
endpoint consistency; that check cannot prove that the IdP actually enforces PKCE.
The identity provider must be configured and its complete consent/code/PKCE flow
verified separately before production readiness can be claimed. Pinned signing-key
rotation requires a reviewed config update and a facade restart; no arbitrary
JWT `jku`/`x5u` fetches are performed.

Subscription delivery stops at the inbound token's expiry unless refreshed. TTLs
are finite, default one hour, ceiling one day, floor one minute (or earlier token
expiry); `ttlMs: null` receives a finite grant. This conservative reauthorization
policy avoids treating expired authorization as ongoing permission. Every delivery
also rechecks Gateway access to its thread. `Events.disconnect(owner)` durably denies
the owner, removes subscriptions/outbox rows, and deletes signing-key bundles.
The explicit local operator command is `python -B -m jaeger_ai.features.mcp_events
/absolute/public-config.json --disconnect`; do not execute it without approval for
that runtime instance. It opens no listener and makes no Gateway or network calls.
The production factory now requires an IdP advertising back-channel logout and
explicit `logout_client_id` / `logout_public_key_file`. It wires
`POST /oauth/backchannel-logout` to a pinned RS256 OpenID Connect Back-Channel
Logout verifier and then to durable `Events.disconnect`. This authenticated route
is separate from the three MCP tools. It requires an issuer-signed `logout+jwt`,
the configured logout-client audience, matching owner, bounded `iat`/`exp`, `jti`,
the standard logout event, and no `nonce`. Only account-wide `sub` logout is
supported; session-only `sid` logout is rejected. It does not accept access tokens
or shared static keys. Access-token verification separately rejects logout tokens.
Successful duplicate logout is idempotent; no raw logout token is persisted.
Native key-deletion failures leave a durable cleanup job while access is already
denied. Jobs retry on subsequent worker polls/restarts.

**External integration is still a qualification blocker, not merely a test that
has not run.** No real IdP/client has been chosen or configured to send these
logout tokens to this receiver. Its account/subject/client mapping must be reviewed
against the actual provider. Register this receiver with an approved existing
provider/application only after separate approval. ChatGPT plugin unlink is not
known to produce this OIDC signal. The supported protocol unsubscribe is implemented,
but a direct ChatGPT unlink → IdP account/logout relationship remains unestablished.
Do not claim instant host disconnect coverage until the actual lifecycle signal is
confirmed. Expiry and local operator revocation remain fail-closed bounds. The
separate ARES Gateway credential cannot establish OAuth connection liveness.

The original patch has no IdP receiver; the revised implementation adds this
standard authenticated entry point. It does not invent an OpenAI disconnect event
or provide a fake authorization server. S256 metadata checking is a configuration
check, not an implementation or proof of authorization-code/PKCE enforcement.

## Storage, delivery, limits

A separate private SQLite file holds subscriptions and summary outbox rows, never
bearer tokens or signing keys. Source-tree state paths are rejected. Runtime uses a
single process with an exclusive file lease. Production signing secrets are stored
through the explicit maintained macOS Keyring backend under service
`ai.jaeger.events`, account = deterministic subscription ID. No fallback plaintext
backend. Install the optional `mcp-events` dependency group in a separately approved
environment; this work did not install packages or read/write actual Keychain items.
Tests use temporary test-only secret stores. Native Keychain behavior remains an
external acceptance item.

Subscription identity hashes authenticated owner, callback URL, event and canonical
arguments. Creation/refresh is idempotent. Challenges are signed, random, single-use
and bounded by the ten-second request deadline. Verification is cached for five
minutes per owner/URL/signing key. Replacement keys are verified and dual-signed
for five minutes. Signing secrets must have `whsec_` plus strict base64 encoding of
24–64 decoded bytes.

Production callbacks must use HTTPS. DNS is resolved and every answer validated
at each POST, then supplied to a connector-only pinned resolver. TLS retains the
original URL hostname and normal certificate validation. Mixed private/public
answers fail closed. Private, local, reserved, mapped and transition addresses,
redirects, proxy environment settings and connection reuse are blocked. No test
switch permits private callback destinations in production.

Requests are capped at 32 KiB; webhook bodies and responses at 256 KiB. Summary
preview is 240 characters, title 256 characters. A ten-second total deadline covers
DNS/connect/TLS/response. At most five attempts use 2/4/8/16/32-second exponential
backoff (the ten-second worker cadence and bounded batch can delay these). Only network failures,
408, 429 and 5xx retry; 410 deletes the subscription, 413 abandons the event.
For 410/413, the transport uses headers immediately and never reads the response
body. Oversized/truncated/stalled bodies, cleanup errors and enclosing-deadline
cancellation cannot convert an observed terminal status into a retry. IDs
and exact bodies remain stable across attempts, with fresh signing timestamps.
`webhook-id` equals `eventId`. HMAC-SHA256 follows Standard Webhooks' byte format.

Limits: 60 authenticated MCP requests/minute, 32 active subscriptions,
6 events/thread/subscription/minute, 20 events/subscription/minute, and 100 queued
events/day across this facade. Rate-limited events are recorded as dropped, not
replayed. ARES's outgoing messages never enqueue events. Persistent per-subscription
event keys prevent repeats from Gateway polling; a crash after receiver ACK and
before local ACK can still redeliver the same event ID, so the receiver must dedupe.
There is no protocol replay cursor (`cursor: null`). The worker polls only Gateway
inbox REST data every ten seconds, at most two pages per tick, and persists each
completed page before the next request. At most four delivery attempts run per tick,
even after a poll failure. Cancellation uses a separate lifecycle lock, cancels the
in-flight task, and checks the current subscription generation before sending or
applying a result. A 410 cannot revive prefetched rows or an identical resubscription; it never opens
the Gateway database. New subscriptions do not replay old messages. Durable pending
summaries survive process reconstruction. On each poll, expired subscriptions and their outbox tombstones retire, signing-key
cleanup is queued, and terminal summary bodies are erased. Audit/logout receipts
expire after seven days; budget entries expire after two days. Daily admissions are
stored separately so unsubscribe cannot reset the cap. No automatic SQLite VACUUM
is performed; disk high-water sizing remains an operational choice.
Audit rows contain only fixed categories, times and hashed subscription handles,
never keys, tokens, callback URLs, bodies or exception text.

## Proposed configuration — document only

No values below have been installed. `example.invalid` and angle-bracket values
are deliberately unresolved choices, not accounts, DNS names or working endpoints.
The fixed local topology is exact; canonical HTTPS resource and issuer must be
chosen together with the eventual connection/IdP owner.

```json
{
  "port": 8797,
  "gateway_url": "http://127.0.0.1:33418",
  "state_file": "/Users/matthewjenkins/.jaeger/mcp-events/events.sqlite3",
  "resource": "https://jaeger-events.example.invalid",
  "issuer": "https://identity.example.invalid",
  "subject": "<verified Matthew IdP subject>",
  "public_key_file": "<absolute pinned RS256 public PEM path>",
  "authorization_server_metadata_file": "<absolute reviewed public metadata JSON path>",
  "logout_client_id": "<approved provider client audience for account logout>",
  "logout_public_key_file": "<absolute pinned provider logout-signing public PEM path>"
}
```

No logout endpoint is registered externally by this code. A private IdP may reach
the private receiver; a public IdP may require separately approved callback ingress.
Secure MCP Tunnel is not assumed to transport arbitrary IdP logout requests.

The bind host is fixed `127.0.0.1`; only the port is configurable. No inbound proxy
may reach the general MCP port or Gateway. OAuth discovery for an `/mcp` resource
is advertised through the standard metadata URL and a 401 challenge. This plan
uses the origin as the canonical audience, with `/mcp` as its endpoint.

### Preferred investigation: OpenAI Secure MCP Tunnel

Private MCP is officially supported without public ingress. Proposed local target:
`http://127.0.0.1:8797/mcp`, profile `jaeger-events`, with a reviewed tunnel identity
associated with Matthew's actual Platform organization and target ChatGPT workspace.
Use the current official CLI's HTTP target option `--mcp-server-url` and verify its
current help before generating a profile; do not invent a tunnel ID or key. Keep
application OAuth enabled; the tunnel credential authenticates transport, not ARES.
OAuth discovery may traverse the tunnel; browser-facing IdP reachability is separate.

**Unverified:** Events discovery/subscription through this tunnel, propagation of
OAuth headers/resource identity, callback delivery compatibility, Matthew's Tunnels
permissions and workspace eligibility. The published tunnel guide establishes
private MCP support, not Events acceptance for this account. No tunnel binary,
profile, credentials or organization/workspace registration were created here.
Do not switch to public ingress merely because these questions remain open.

### Alternatives only after explicit approval

Tailscale Funnel: propose HTTPS 443 on a dedicated approved Funnel hostname,
forwarding only `/mcp`, OAuth resource metadata and the authenticated
`/oauth/backchannel-logout` route to loopback 8797. Require exact
path allowlisting in a local reverse proxy (Funnel alone may expose all paths),
TLS, disabled request-body/header logging, existing OAuth checks, and no forwarding
of Gateway or general MCP. No tailnet ACL, Tailscale state, DNS or Funnel command
was changed. Current account policy/CLI behavior needs inspection at approval time.

Cloudflare: propose a named approved tunnel with ingress rules only for the three
facade paths to `http://127.0.0.1:8797`, followed by catch-all HTTP 404. Keep application
OAuth; interactive Cloudflare Access login cannot be assumed compatible with MCP.
A dedicated DNS hostname, proxy restrictions, tunnel credentials and path behavior
need separate approval and acceptance. No Cloudflare/tunnel registration occurred.

### Connection acceptance and rollback

After exact separate approval for the selected setup: verify IdP metadata and
S256 behavior; install optional dependencies; provision only Events signing-key
storage; start this facade alone; verify private MCP discovery and exact tools;
link the plugin in the intended dot; subscribe to ARES messages there; deliver a
controlled approved message; independently observe that exact conversation wake;
then test refresh, expiration, unsubscribe and disconnect. A 2xx callback ACK alone
is not a conversation-wake proof. No outbound Grok message is authorized by this
implementation task, so real-message acceptance needs its own explicit scope.

Rollback: revoke the owner locally, stop only the new facade process, remove the
new plugin connection and selected transport profile/routing, and delete only
Events Keychain accounts and its separate state when approved. Never restart or
modify the Gateway, existing bridge, main checkout or other worktrees. Record
remote unlink/revocation evidence before removing local state. Risks include public
exposure if a proxy path rule is wrong, OAuth misconfiguration, callback exfiltration,
revocation delays, duplicate delivery after crash, finite token lifetimes and dropped
rate-limited events. No setup or rollback action has been executed.

## Sources checked 2026-10-19

- [Official MCP Events integration](https://developers.openai.com/plugins/build/mcp-events)
- [OpenID Back-Channel Logout](https://openid.net/specs/openid-connect-backchannel-1_0.html)
- [Official plugin authentication](https://developers.openai.com/plugins/build/auth)
- [MCP 2026-07-28 HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic/index)
- [Events protocol design reference linked by OpenAI](https://github.com/modelcontextprotocol/experimental-ext-triggers-events/blob/main/docs/design-sketch-proposal.md)
- [Official Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

## Reproduce isolated verification

Use the existing interpreter without package installation. `dev/tests/conftest.py`
forces temporary caller credentials and operator state. `PYTHONPATH` must include
the repository and its two workspace packages. Run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/jaeger-agent:packages/jaeger-os:. \
  /Users/matthewjenkins/.jaeger/venv/bin/python -B -m pytest \
  dev/tests/jaeger_ai/core/test_mcp_events.py \
  dev/tests/jaeger_ai/core/test_agent_bridge*.py \
  dev/tests/jaeger_ai/core/test_gateway_caller_auth.py \
  -q -o cache_dir=/tmp/jaeger-events-pytest
PYTEST_ADDOPTS='-o cache_dir=/tmp/jaeger-events-verify-cache' ./scripts/verify.sh
```

The E2E test hosts a real isolated Gateway and facade on ephemeral loopback ports,
with Gateway background startup disabled. Only the receiver uses injected simulated
transport. Separate tests exercise the real destination validator and connector
pinning with synthetic DNS answers; no public webhook or provider is called.


## Qualification classification

| Piece | Code status | Outstanding qualification |
| --- | --- | --- |
| OAuth resource verification | Implemented, signature/issuer/audience/time/subject/scope negatives tested | Actual provider tokens/key lifecycle |
| Authorization/consent/code exchange/S256 PKCE | External authorization-server component; deliberately no local stub or substitute | Provider selection, policy/client/resource/redirect setup and enforcement proof are missing external prerequisites |
| Account revocation receiver | Implemented signed OIDC route to durable denylist, callback cancellation and retryable key cleanup | Actual IdP sender/client/subject mapping and private reachability are not configured |
| ChatGPT disconnect semantics | MCP unsubscribe implemented; no invented host unlink API | Concrete unlink signal to this server/IdP remains unknown; qualification blocked |
| Native Keychain | Explicit maintained macOS backend implemented; backend mocked in unit tests | Optional dependency install and native acceptance require approval |
| HTTPS callback pinning/signing | Production implementation plus validator/pinning/tamper tests | Real remote TLS and ChatGPT callback acceptance |
| Restart and isolation | Real SQLite and fresh-process test secret reload; real temporary Gateway HTTP E2E | Operator-state deployment is intentionally not exercised |
| Tunnel/account/exact dot wake | Document-only connection plan | Eligibility, setup and actual wake are unverified |
