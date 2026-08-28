# 🤖 Agent Handoff & Comprehensive Audit Prompt

> **Instructions for the Inspecting / Auditing Agent**: Use this document as your primary context prompt to audit, verify, or build upon the Hermes Agent → JaegerAI migration. Follow the exact repository structure, architectural doctrines, and test verification commands detailed below.

---

## 1. Context & Mission Statement

The objective of this engineering effort was to achieve **100% feature parity between Hermes Agent and JaegerAI**, upgrading JaegerAI to match or exceed Hermes Agent in cognitive capabilities, tool safety, context management, provider support, and multi-channel messaging, while preserving JaegerAI's superior monorepo architecture:

- **`packages/jaeger-agent/`**: Engine mind, cognition loop, memory, context guard, safety.
- **`packages/jaeger-os/`**: Hardware slots, tool registries, schema validation, safety rules.
- **`jaeger_ai/`**: Host application, CLI, gateways (Telegram/Discord/Slack), personas, runtime node.
- **`dev/`**: Benchmark runners (`swe_runner.py`, `batch_runner.py`), test datasets (`dev/evals/`), unit tests.

---

## 2. Core Architectural Doctrines Enforced

1. **Strict Nested Monorepo Structure (`uv` workspace)**:
   - Workspace defined in `pyproject.toml` (`members = ["packages/*"]`).
   - No loose files dumped in the root directory. Subpackages linked via `[tool.uv.sources]`.
2. **At-Most-Once Effect Ledger (`LedgerToolExecutor`)**:
   - Tools with `side_effect="external"` route through `EffectLedger.once(key, tool_name, ...)` backed by SQLite WAL/memory to prevent duplicate side effects after crashes or turn retries.
3. **Thread-Safe ContextVar State**:
   - All session-specific state (`_project_root_var`, `_current_session`, `_post_tool_call_hook_suppressed`) uses `contextvars.ContextVar` to allow concurrent background voice loops, scheduled tasks, and web chats without cross-thread state pollution.
4. **Resilient LLM Error Recovery**:
   - Tool validation errors do not raise unhandled `ValidationError` crashes; they return structured error feedback strings (`"[Tool Error in 'name']: ... Please correct parameters and try again."`) so the LLM self-corrects on its next turn.
5. **Middle-Out Context Compression**:
   - `ContextGuard` triggers `trajectory_compressor.py` when prompt token budgets are exceeded, compressing middle turns while keeping system prompts and recent turns intact.

---

## 3. Exhaustive Summary of Files Created & Upgraded

### A. Core Agent Package (`packages/jaeger-agent/jaeger_agent/`)

| File Path | Changes & Features Added |
|---|---|
| `tool_executor.py` | Added argument coercion error recovery (`type(err).__name__`) and `suppress_post_tool_call_hook()` `ContextVar` context override. |
| `workspace.py` | Converted `_project_root` to thread-safe `_project_root_var` (`ContextVar`), and updated `_resolve_read()` to use `get_project_root()`. |
| `runtime.py` | Expanded provider key mapping (`openrouter`, `groq`, `deepseek`, `vllm`) and made `steer()` session-targeted. |
| `safety.py` | Implemented regex guard in `safety_review()` to block destructive terminal commands (`rm -rf /`, `dd if=...`, `mkfs`, `chmod -R 777 /`). |
| `credentials.py` | Added `os.environ` fallback to `get_credential()` for missing physical secret files. |
| `config.py` | Added optional `organization` and `api_mode` fields to `AgentConfig`. |
| `bridge.py` | Added `self._events.current_session = ""` cleanup in `finally:` block to prevent session leakage. |
| `trace.py` | Converted `Tracer` turn sequence tracking to `threading.local()` for thread safety across multi-session turns. |
| `node.py` | Added clean `runtime.close()` execution in `MindNode.teardown()`. |
| `errors.py` | Added HTTP stream connection drop keywords (`streamclosed`, `incompleteread`, `chunkedencodingerror`) to `TRANSIENT` retry classification. |
| `messages.py` | Added `metadata: Dict[str, Any]` field to `ChatMessage` and `ChatReply`. |
| `contracts.py` | Added `tokens_used` and `elapsed_s` telemetry fields to `TurnResult` and `normalize_turn_result()`. |
| `util/trajectory_compressor.py` | Ported middle-out context compression engine from Hermes Agent. |
| `memory/sqlite_search.py` | Ported SQLite FTS5 full-text search engine. |
| `memory/portability.py` | Ported session JSONL export/import portability tools. |
| `background/cron.py` | Ported background task cron scheduler. |

### B. Host Application & Gateway Package (`jaeger_ai/`)

| File Path | Changes & Features Added |
|---|---|
| `core/models/external_model.py` | Added `openrouter`, `groq`, `deepseek`, `vllm`, `together` to `_OPENAI_COMPATIBLE`, `_CLOUD_PROVIDERS`, `_CONVENTIONAL_ENV`, and `_PROVIDER_CREDENTIAL_ALIASES`. |
| `core/instance/schemas.py` | Updated `provider: Literal[...]` in `FallbackModel` and `ExternalModelConfig` to include new providers. |
| `interfaces/gateway/telegram_adapter.py` | **[NEW]** Telegram Bot API polling/webhook gateway adapter with whitelist security. |
| `interfaces/gateway/discord_adapter.py` | **[NEW]** Discord Bot gateway websocket event adapter. |
| `interfaces/gateway/slack_adapter.py` | **[NEW]** Slack Events / Socket Mode thread adapter. |
| `interfaces/gateway/manager.py` | **[NEW]** Gateway discovery and lifecycle manager. |
| `core/instance/presets/provider_presets.py` | **[NEW]** Configuration presets for DeepSeek, Groq, OpenRouter, Ollama, LM Studio, and local GGUF/MLX. |

### C. Benchmarking & Evaluation (`dev/`)

| File Path | Changes & Features Added |
|---|---|
| `dev/benchmark/swe_runner.py` | **[NEW]** Automated SWE-bench coding task evaluator. |
| `dev/benchmark/batch_runner.py` | **[NEW]** Batch trajectory scenario runner. |
| `dev/evals/coding_bench.jsonl` | **[NEW]** Coding problem evaluation benchmark dataset. |
| `dev/evals/swe_bench.jsonl` | **[NEW]** Software engineering problem benchmark dataset. |

### D. Production Hardening and Remaining Hermes Ports

| File / Surface | Changes & Features Added |
|---|---|
| `shell_hooks.py` + executor chain | Operator `pre_tool_call` veto and advisory `post_tool_call`; enforced ordering is hooks → checkpoints → effect ledger → direct execution. |
| `checkpoints.py` | Shadow-git snapshots before mutating tools, with best-effort recovery that never falsely claims a clean tree. |
| `tirith.py` + `command_guard.py` | Content-threat scanning integrated into the hardline command guard; no automatic binary downloader. |
| `plugins/mcp/oauth.py` | MCP OAuth discovery, token persistence, refresh, and `httpx` auth integration. |
| `skill_registry/skills_hub.py` | Contained skills-hub sources with archive/path/link/size guards and an install ledger. |
| `subagent_worktree.py` | Opt-in isolated child worktrees; uncertain inspection preserves work and reports the uncertainty to the parent. |
| `main.py` / autostart | Reachable `--daemon` path for the existing heartbeat, cron, board, Deep Think, and gateway runtime; launchd guidance points unattended installs to `autostart enable --daemon`. |
| cognition loop | Unified iteration/tool budgets, automatic acceptance ledgers and receipts, declarative-claim verification, deterministic skill routing, and conservative cross-iteration read caching. |
| code bridge | macOS Seatbelt / Linux bubblewrap execution that fails closed when no supported sandbox is available. |
| release gates | Random-order registry/workspace/identity isolation, repository-wide critical lint, artifact inspection, Swift tests, and dependency auditing with one documented unreachable transitive exception in `SECURITY.md`. |

---

## 4. Verification & Testing Protocol

To verify the codebase, run the following commands from the repository root:

```bash
# 1. Activate environment and set PYTHONPATH
export PYTHONPATH=packages/jaeger-os:packages/jaeger-agent:jaeger_ai

# 2. Run new interface and preset unit tests
.venv/bin/pytest dev/tests/jaeger_ai/interfaces/test_gateway_adapters.py dev/tests/jaeger_ai/core/instance/test_provider_presets.py

# 3. Run full smoke test suite (166 tests)
.venv/bin/pytest dev/tests -m smoke

# 4. Run the host and reusable-agent suites
.venv/bin/pytest dev/tests -q                         # 3,425 passed, 11 skipped
.venv/bin/pytest packages/jaeger-agent/tests -q      # 806 passed

# 5. Reproduce the order-dependence gate
.venv/bin/pytest dev/tests -q --randomly-seed=404
.venv/bin/pytest packages/jaeger-agent/tests -q --randomly-seed=505

# 6. Critical static and dependency gates
.venv/bin/ruff check --select E9,F63,F7,F82 .
.venv/bin/pip-audit --local --skip-editable \
  --ignore-vuln PYSEC-2026-2447  # documented in SECURITY.md; no reachable cache
```

---

## 5. Audit Checklist for Next Agent

If you are tasked with identifying further gaps or expanding JaegerAI, execute the following audit checklist:

1. **Inspect Gateway Authentication Hooks**:
   - Check `jaeger_ai/interfaces/gateway/` to see if additional platform adapters (e.g. WhatsApp, Matrix, Webhooks) should be registered in `GatewayManager`.
2. **Review Tool Execution Safety**:
   - Check `packages/jaeger-agent/jaeger_agent/safety.py` to add any domain-specific command guards for specialized server deployments.
3. **Verify Provider Extensions**:
   - Check `jaeger_ai/core/models/external_model.py` if new LLM API providers (e.g. Cohere, Bedrock, Vertex AI) need custom header options.
4. **Validate Test Coverage**:
   - Run `.venv/bin/pytest dev/tests` to ensure 100% test pass rate across all workspace modules.
