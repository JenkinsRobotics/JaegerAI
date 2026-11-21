# Multi-Agent Team Hard Eval

Hard collaboration stress tests for JaegerAI's multi-agent stack
(`RuntimeHost`, delegation, shared blackboard, private memory isolation).

## Sources (public multi-agent eval patterns)

Network clone was unavailable in this environment, so scenarios are
**re-implemented in-repo** from the public design patterns of:

| Source | Pattern borrowed |
|--------|------------------|
| [TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany) | Multi-step workplace task with role handoffs and durable artifacts |
| [MultiAgentBench](https://github.com/MultiAgentBench/MultiAgentBench) | Coordination metrics: coverage, dependency order, re-plan after failure |
| [MetaGPT](https://github.com/geekan/MetaGPT) | Software-company role split (PM / specialist / engineer / QA) under a lead |
| Hidden-profile / information-asymmetry puzzles (classic team cognition) | No single agent holds the full answer; merge requires all shards |

## Scenario: Operation Split-Key (`operation_split_key`)

A **lead orchestrator** must clear a mission by coordinating four
specialists. The final clearance code is **not** known to any one agent.

| Role | Private knowledge | Public contribution |
|------|-------------------|---------------------|
| Lead | Mission goal only | Plan, delegate, re-plan, synthesize |
| Archivist | Vault id + alpha shard | Posts redacted intel to blackboard |
| Cryptanalyst | Numeric seed only | Computes beta from vault id + seed |
| Engineer | Assembly recipe | Writes intermediate token artifact |
| QA | Verification rule | Signs final clearance or rejects |

### Why this is hard

1. **Information asymmetry** — private episodic/semantic memory never leaks.
2. **Strict dependency graph** — engineer cannot run before alpha+beta exist.
3. **Mid-run failure** — first cryptanalyst attempt fails; lead must cancel + re-delegate.
4. **Anti-forge** — lead cannot plant a fake clearance without QA evidence chain.
5. **Trust matrix** — untrusted peers cannot receive sensitive capability grants.
6. **Evidence receipts** — final pass requires all four specialist receipts on the board.

## Run

```bash
# Deterministic protocol test (no live LLM required)
python dev/benchmark/multiagent_team_hard.py

# Pytest gate
python -m pytest dev/tests/jaeger_ai/core/test_multi_agent_team_hard.py -q
```
