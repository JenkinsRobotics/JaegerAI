# Cost Tracking

Records what every turn cost — tokens in, tokens out, money — and enforces
budgets, so a runaway agent stops instead of quietly spending.

| File | What it does |
| :--- | :--- |
| `store.py` | The durable ledger, plus the budget check that returns a `BudgetDecision` (allow or deny). |
| `tools.py` | Lets the agent report its own spend. |

**Turn it on:** always on. Budgets are set in your instance settings; with no
budget set it records but never blocks.

**Check it works:** ask the agent what this session has cost.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
