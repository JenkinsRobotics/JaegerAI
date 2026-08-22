"""Framework internals — read-only at runtime.

Everything in this package is shipped with the library and is NOT
agent-writable. The agent's writable scratchpad lives at
`<instance_dir>/skills/` (typically `~/.jaeger/<instance>/skills/`).

Modules:
  • instance.py      — instance dir resolution, lockfile, manifest gate
  • schemas.py       — Pydantic v2 schemas (identity, config, manifest)
  • setup_wizard.py  — first-run flow (interactive)
  • credentials.py   — get_credential + perm enforcement
  • memory.py        — per-instance facts / episodic / schedules I/O
  • cron_runner.py   — schedule firing + daily housekeeping hook
  • log_rotation.py  — daily rotation + retention enforcement
  • migrations.py    — discover + apply per-version migrations
  • skill_loader.py  — discover + register skills (core/ and instance/)
  • llm_model.py     — in-process Gemma adapter for pydantic-ai
  • prompts.py       — system-prompt assembler
  • tools.py         — built-in agent tools (file_write/read, get_time, …)
"""
