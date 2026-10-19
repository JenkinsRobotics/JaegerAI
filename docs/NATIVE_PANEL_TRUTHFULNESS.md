# Native panel truthfulness — first slice

Base: f34449e5 (current source checkout). The continuation document's 0.13-dev pointer is older than the current Gateway/auth implementation; this isolated feature branch leaves both source branches and other worktrees untouched.

Skills uses the existing GatewayClient request path, endpoint resolver and menubar caller authorization. GET /v1/runtime/skills returns name/category/description/lifecycle; the UI preserves lifecycle and does not invent installation status or tool counts. Refresh clears previous data; failures cannot leave a previous catalog looking current. Empty, filtered-empty, loading, transport failure, authorization denial and unsupported endpoint states are explicit. No production sample fallback.

Tasks and Kanban deliberately show native integration unsupported. The old local schedule toggles, timer-produced success and mutable sample board are removed. WebUI /api/crons is a runner-local scheduler, separate from Gateway orchestration tasks. WebUI /api/kanban uses hermes_cli.kanban_db. Both run behind api.auth.check_auth (WebUI session/trusted authentication), not the Gateway menubar caller contract. WebUIEndpoint resolves an address, not an authenticated native session. Do not forward the Gateway bearer token to that service or add a permissive proxy.

Next integration slice: establish a typed authenticated WebUI client/session and instance binding, then load runner-local cron and board projections. Before enabling mutations, preserve approval semantics and durable run identity; uncertain sends must be observed without resend. Native actions remain unavailable until those contracts are implemented.

Validation: Swift build using external /tmp/jaeger-native-panels-build; focused RuntimeSkillsTests for actual wire fields, stable identity, empty versus malformed response; git diff --check. No broad verify.sh run because the user explicitly restricted tests to focused necessary checks. No live endpoint, credential, configuration, scheduler mutation, model call, installed-app change or service restart.
