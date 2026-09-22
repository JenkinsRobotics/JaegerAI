# ARES Financial Intelligence

The `ares-finance` extension gives ARES a loopback finance sidecar, a `/finance` dashboard tab, 19 agent/MCP tools, and bidirectional Monarch Money automation.

## Architecture

- **Sidecar:** FastAPI on `http://127.0.0.1:3848` (`python -m server.server` or `./start.sh`)
- **Store:** SQLite at `server/data/finance.db` (override with `ARES_FINANCE_DB`)
- **Dashboard tab:** `dashboard/index.html` (Overview, Budgets, Subscriptions, Wallet, Analytics)
- **Agent tools:** `tools.finance_tools` (see `manifest.json` `tools.definitions`)
- **MCP:** stdio, `python -m server.mcp_server`

ARES loads `scripts`, `stylesheets`, `sidecar`, `permissions`, and `settings_schema` from this manifest. Start the sidecar yourself; ARES only proxies loopback origins after consent.

## Operator setup

1. `pip install -r requirements.txt` in this directory (prefer a venv).
2. `./start.sh`
3. Symlink into `${ARES_HOME:-$HOME/.ares}/extensions/ares-finance`
4. In the Finance tab, connect Monarch (session token **or** email/password/TOTP).
5. Sync. Until that succeeds, every figure is seeded demo data (`data_provenance.is_demo = true`).

The dashboard token field writes through `/api/auth/monarch-token` into the local `auth_tokens` table, which `_authenticate()` actually reads. Email/password goes through `/api/auth/connect` and persists a `.mm_session` file.

## Tool matrix

| Tool | Kind | Notes |
|---|---|---|
| `finance_summary` | Read | Net worth; includes provenance |
| `list_accounts` | Read | All synced accounts |
| `refresh_bank_accounts` | Mutation | Aggregator refresh + sync |
| `check_institution_health` | Read | MFA / reconnect flags |
| `list_categories` | Read | Local cache of taxonomy |
| `create_category` | Mutation | Fails if the group does not exist |
| `delete_category` | Mutation | Refuses system categories |
| `get_budgets` | Read | Live Monarch unless `live=false`; both dates or neither |
| `set_budget` | Mutation | Before/after snapshot |
| `list_recurring_bills` | Read | Live unless `live=false`; both dates or neither |
| `search_transactions` | Read | Ledger search |
| `spending_by_category` | Read | Date-window spend |
| `edit_transaction` | Mutation | Before/after snapshot |
| `create_transaction` | Mutation | Writes the new row locally |
| `recommend_card` | Local | Wallet multiplier engine |
| `list_cards` | Local | Wallet contents |
| `monarch_status` | Status | Demo vs real, last sync |
| `monarch_setup` | Auth | Never invent credentials |
| `sync_monarch` | Sync | Accounts, tx, categories, budgets, bills |

## Agent rules

- If `data_provenance.is_demo` is true, say so. Do not present demo net worth as the user's.
- Ask the user for Monarch credentials. Never invent email, password, token, or TOTP.
- Mutations fail closed without a session. Retry after `monarch_setup` + `sync_monarch`.
- Prefer exact category names or Monarch UUIDs. Demo ids (`cat_dining`) are rejected.

## REST (sidecar)

| Method | Path |
|---|---|
| GET | `/health`, `/api/status`, `/api/summary`, `/api/accounts`, `/api/categories`, `/api/budgets`, `/api/recurring-bills`, `/api/transactions`, `/api/cards`, `/api/analytics/spending`, `/api/institutions/health` |
| POST | `/api/sync`, `/api/accounts/refresh`, `/api/budgets`, `/api/categories`, `/api/transactions`, `/api/transactions/update`, `/api/auth/monarch-token`, `/api/auth/connect`, `/api/recommend-card`, `/api/cards` |
| DELETE | `/api/categories/{id}`, `/api/cards/{id}` |
