# core/ — framework infrastructure

> **Modification tier: C — Framework core.** This is the instance
> machinery, the schema definitions, the prompt assembly, the tool
> implementations, the permission system, the safety scan. Edits here
> affect every JROS deployment. Read first, plan minimal patches, run
> the test suite, and let the entry land in
> `<instance>/audit/self_modification.jsonl`. Full policy:
> [`/docs/SELF_MODIFICATION_BOUNDARIES.md`](../../../docs/SELF_MODIFICATION_BOUNDARIES.md).

## What's in here

| File / dir | Purpose |
|---|---|
| [`prompts.py`](prompts.py) | The system-prompt builder. `JAEGER_OS_CONTEXT` + `MANDATORY_TOOL_RULES` + `SELF_MODIFICATION_BOUNDARIES` + `OPERATING_DISCIPLINE` + the runtime tail. |
| [`instance.py`](instance.py) | `InstanceLayout` dataclass + `InstanceLock` (fcntl-based exclusive lock) + manifest version checks. |
| [`schemas.py`](schemas.py) | Pydantic models for `identity.yaml`, `config.yaml`, `manifest.json`. The trust boundary for instance config. |
| [`tools/`](tools/) | Tool implementations — files, memory, web, code, packages, background processes, board, browser, computer-use, etc. Each tool is a function the agent's tool registry wraps. |
| [`memory.py`](memory.py) | `facts.json` reader/writer + episodic-log appender + semantic search over episodic history. |
| [`permissions.py`](permissions.py) | The `@requires_tier(...)` decorator + tier model + confirmation routing. |
| [`skill_loader.py`](skill_loader.py) | Discovers skills under `<instance>/skills/` and `src/jaeger_os/agent/skills/`, runs smoke tests, registers passers. |
| [`skills_guard.py`](skills_guard.py) | Static scan for prompt-injection / exfiltration / destructive patterns in skill source. Used before activation. |
| [`self_modification_audit.py`](self_modification_audit.py) | Phase-10 path classifier + JSONL audit writer (`audit_write` / `audit_unsandboxed_call`). |
| [`migrations.py`](migrations.py) | Per-release schema-migration runner. Reads modules from `src/jaeger_os/migrations/` and applies them in order. |
| [`external_model.py`](external_model.py) | `ExternalModelClient` — bounded `chat()` for fast-finalize against cloud providers. Adapter selection lives in `agent/runtime_bridge.py`. |
| [`llm_client.py`](llm_client.py) / [`mlx_client.py`](mlx_client.py) | Local-model clients (in-process llama-cpp / MLX). Used by `make_client` in `main.py`. |
| [`credentials.py`](credentials.py) | Encrypted-at-rest credential store under `<instance>/credentials/`. Off-limits to agent reads of the raw file. |
| [`cloud_errors.py`](cloud_errors.py) | Provider-specific exception classification + `retry_call` helper for transient failures. |
| [`playbook_skills.py`](playbook_skills.py) | The compact skill-index embedded in the system prompt. |
