# Subagent contract (`jaeger.subagent.v1`)

Jaeger is always the lead. It hands work to teammates through four tools:

| Tool | Use |
|---|---|
| `delegate(profile, brief)` | Think with an inner helper (Design & Style, Mac App, ...); waits for the answer |
| `call_agent(agent_id, task, allowed_tools=...)` | Hand a bounded task to a roster teammate; waits, or returns `running` from a background parent |
| `run_team(assignments)` | Several teammates in parallel; `results` is a list of contract results |
| `get_agent_result(handoff_id)` | Read a durable result later; never starts or retries work |

## Brief (what goes in)
- **What you need back.** A brief that only says "look into X" is refused (`brief is required: say exactly what you need back`).
- **Scope.** `allowed_tools` narrows what the teammate may use. It never gets more than the lead's own grant (`lead_allowed_tools`).
- **Approval.** `require_approval=true` makes the owner approve the hand-off first. Autonomy decides this by default.
- **Time.** `timeout_seconds`. A timeout is never treated as done.

## Result (what comes back)
Each tool keeps its own fields and adds the following:

| Field | Meaning |
|---|---|
| `contract` | `"jaeger.subagent.v1"` |
| `ok` | true only for a completed, non-stub result (or `running` when accepted) |
| `status` | `completed`, `failed`, `timeout`, `pending_approval`, `running`, `stopped`, `cancelled`, `denied`, `unknown` |
| `done` | the status is final |
| `agent` | who did the work |
| `handoff_id` | the durable record, readable with `get_agent_result` and shown in the Tasks view |
| `summary` | the teammate's answer (a preview when `result_path` holds the full text) |
| `error` | why it is not ok |
| `next` | what the lead should do now (answer in its own voice, end the turn, tell the owner, ...) |

## Rules the lead follows
1. Answer in your own voice and name who did the work.
2. `running`: end the turn and read the result later. Do not resubmit.
3. `timeout` / `failed` / `unknown`: never present it as done.
4. `pending_approval`: tell the owner. Don't do the work yourself.

Code: `packages/jaeger-agent/jaeger_agent/tools/call_agent.py` (`_contract`, `_with_contract`).
