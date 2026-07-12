# skills/ — core skills (v2-contract packages shipped with the framework)

Each entry here is a **versioned skill folder**, NOT a single Python
file. Skills are higher-order than tools — they have their own docs,
their own smoke test, and they can be overridden at runtime by the
agent writing a higher-versioned copy under `instance/<name>/skills/`.

For atomic, single-function capabilities like `get_time` or `file_write`,
see [`../tools/`](../tools/) — those are TOOLS, not skills.

## The v2 skill contract

Every skill folder must follow this shape:

```
skills/<name>_v<N>/
├── SKILL.md                  ← what / when / how / depends-on
├── <python_module>.py        ← exposes `register(agent)` to wire tools
└── tests/
    └── smoke_test.py         ← runs as a subprocess before activation
```

- **SKILL.md** — short markdown answering four questions:
  1. **What** does this skill do?
  2. **When** should the agent trigger it?
  3. **How** is it called? (inputs, outputs, side effects)
  4. **What** does it depend on?
- **Python module** — must expose a `register(agent)` function that
  attaches one or more tools via `@agent.tool_plain`.
- **smoke_test.py** — the loader runs it as a subprocess before
  activating the skill. Non-zero exit → skill is skipped, failure logged
  in `instance/<name>/logs/audit.log`.

## Versioning + override

Folder names end in `_v<N>` (e.g. `weather_v1/`, `weather_v2/`):

- Within a zone, the **highest `_v<N>` wins** (so `weather_v2` shadows `weather_v1`).
- Across zones, **instance wins over core** — i.e. an `instance/<name>/skills/weather_v2/`
  shadows this `core` directory's `weather_v1/`.
- This is the framework's "improve a shipped skill without touching the
  shipped code" pattern. See `core/skill_loader.py` for the resolution.

## Current core skills

| skill | purpose |
|---|---|
| [`macos_computer/`](macos_computer/) | **Recommended on macOS.** Capability-ladder Mac control — AppleScript → browser CDP → Accessibility → screenshot fallback. Focus-preserving where possible. The flagship skill for Jaeger on a Mac. |
| [`computer_use/`](computer_use/) | Universal cross-OS computer control via the screenshot loop. Portable but slow; use as a fallback when the platform doesn't expose a faster object surface, or for canvas/game UIs without semantic objects. |

(The collection is intentionally small — Jaeger ships the agent's
primitive surface as TOOLS in [`../tools/`](../tools/), not as
skills. Skills are for composed, larger capabilities.)

A minimal **copy-me template** for authoring a new skill — the
SKILL.md + module + smoke-test + benchmark contract at its smallest —
lives at [`../../../docs/skill_template/`](../../../docs/skill_template/).
It is kept out of this auto-loaded directory on purpose, so it never
registers a tool into a running agent.

## Where agent-authored skills go

When the agent writes a new skill at runtime via `file_write`, it lands
in **`../instance/<instance_name>/skills/<name>_v<N>/`**, NOT here.
This directory is read-only to the agent (it's part of the installed
framework). See the [top-level README](../README.md) and
[`../instance/README.md`](../instance/README.md) for the full split.
