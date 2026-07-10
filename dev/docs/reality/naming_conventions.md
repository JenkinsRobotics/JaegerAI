# JROS naming & organization conventions

Conventions for tools, skills, and repo layout — aligned with
hermes-agent's practice where it fits, kept where JROS is already
distinct. Follow these when adding a tool or skill.

## Tools

- **Name:** `snake_case`, a verb or noun. Group related tools into a
  **prefix family** — `web_search` / `web_extract`, `list_*`,
  `board_*`, `computer_*`. A single-capability tool gets a bare name
  (`calculate`, `terminal`, `todo`).
- **Implementation:** one file per category under `core/tools/`
  (`web.py`, `files.py`, `memory.py`, …). The LLM-facing wrapper is
  registered in `main.py:_register_builtins` with `@agent.tool_plain`.
- **Description (the docstring the model sees):** lead with a one-line
  *trigger* ("Use when …") and, for a tool confusable with another, a
  one-line *boundary* ("For X use Y instead"). Keep it factual — drop
  `MANDATORY` / `NEVER` / `LAST RESORT` rhetoric; routing-critical
  imperatives live once, in `MANDATORY_TOOL_RULES` (`core/prompts.py`),
  not repeated in every docstring.
- **Classification:** every tool belongs to a toolset in
  `core/toolsets.py` (`CORE` or a named class). Add a new tool to one.

## Skills

- **Folder:** `snake_case` base name + a numeric version suffix —
  `computer_use_v2/`. The `_v<N>` is load-bearing (`skill_loader.py`
  resolves highest-version-wins, instance-over-core) — **keep it**;
  it's a JROS strength, not a gap.
- **`SKILL.md`:** YAML frontmatter — `name` (matches the folder base),
  `version`, `kind`, `category`, `runtime`, `permission_tier`,
  `registers_tools`, `description`. The `description` is **one
  sentence, ends with a period, no marketing words.**
- **A skill is a toolset.** The loader captures exactly the tools a
  skill's `register()` adds and exposes them as a named toolset (see
  `core/toolsets.py`). A skill therefore *owns its own tool list* — no
  edit elsewhere when you add one.
- **Tests:** `tests/smoke_test.py` (gates activation) and an optional
  scored `tests/benchmark.py`.

## Skill vs. tool — the decision rule

- Make it a **tool** when it needs an API key/credential, must-run
  precise logic, or handles binary/streaming data.
- Make it a **skill** when it's instructions + a process composed from
  shell and existing tools. Default to a skill.

## Repo layout

```
src/jaeger_os/
  core/         agent loop, loader, schemas, base tools, toolsets
  core/tools/   one file per tool category
  skills/       versioned core skills (<name>_v<N>/)
  prompts/      the system-prompt source
  interfaces/   TUI and other front-ends
  plugins/      bridges to external libs/hardware (TTS, STT, MCP, …)
benchmark/      levels/ (routing) + timing/ (per-prompt wall-clock)
docs/           design notes, A/B writeups
```
