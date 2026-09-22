# ARES Financial Intelligence

Offline-first finance sidecar for **ARES** and **JaegerAI**. Local SQLite cache, Monarch Money read/write automation, MCP tools, and a `/finance` dashboard.

Version **1.2.0**.

## What it does

- Force bank refreshes through Monarch aggregators (Plaid / Finicity / MX)
- Create and delete **custom** categories (system categories are refused)
- Read and set monthly budgets with before/after diffs
- Audit recurring bills and subscriptions
- Recategorize or create transactions
- Card-reward optimizer against your wallet

Demo rows are seeded so the HUD works offline. Every read includes `data_provenance`. If `is_demo` is true, those numbers are **not** the user's finances.

Mutations talk to the live Monarch API. They resolve categories by live UUID/name, never by demo ids such as `cat_dining`. Unknown category groups fail closed — they are not silently assigned to the first group.

## Install

```bash
cd ares-finance
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -r requirements-dev.txt   # for tests
```

## Run the sidecar

ARES proxies loopback sidecars; it does not spawn this process for you.

```bash
./start.sh
# listens on 127.0.0.1:3848  (override with FINANCE_PORT)
```

Health check: `GET http://127.0.0.1:3848/health`

## Connect to ARES

1. Start the sidecar (`./start.sh`).
2. Copy or symlink this repo into the ARES extension directory as `ares-finance/`:

```bash
mkdir -p "${ARES_HOME:-$HOME/.ares}/extensions"
ln -sfn "$(pwd)" "${ARES_HOME:-$HOME/.ares}/extensions/ares-finance"
```

3. Confirm `manifest.json` is visible to ARES (`id` = `ares-finance`, sidecar origin `http://127.0.0.1:3848`).
4. Open the Finance tab. Approve the sidecar proxy if ARES asks.
5. Connect Monarch (token **or** email + password + optional TOTP secret), then **Sync Monarch**.

MCP (stdio):

```json
{
  "mcpServers": {
    "ares-finance": {
      "command": "/ABS/PATH/ares-finance/.venv/bin/python",
      "args": ["-m", "server.mcp_server"],
      "cwd": "/ABS/PATH/ares-finance"
    }
  }
}
```

Do not put passwords in `manifest.json`. Prefer `monarch_setup` or the dashboard auth modal. Unattended cron may use env vars from `.env.example`.

## Tests

```bash
./.venv/bin/pytest
```

All default tests use a fake Monarch client. They never touch a live account.

Optional live smoke (read-only: institution health + category list):

```bash
ARES_FINANCE_LIVE=1 ./.venv/bin/pytest -m live
```

## Safety

| Operation | Guard |
|---|---|
| Reads | `data_provenance.is_demo` tells the agent when figures are fake |
| Mutations | Require a Monarch session; demo SQLite ids are never sent |
| `create_category` | Unknown groups error out |
| `delete_category` | System categories refused |
| `set_budget` / `edit_transaction` | Live name/UUID resolution + before/after snapshot |
| Sidecar | Loopback only (`127.0.0.1`) |

## License

MIT — Jenkins Robotics.
