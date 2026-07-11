# Skill manifest schema — `jros.skill/v3`

The form a **code skill** (tool-skill) declares itself in, read at load by
`skill_registry/skill_loader.py`. Playbook skills use SKILL.md frontmatter
instead (see `dev/docs/pipelines/skill_discovery_pipeline.md`); this doc is the
`manifest.yaml` form. Referenced by the startup log.

> This documents what the loader **reads today**, verified against
> `jaeger_os/agent/skills/computer_use/manifest.yaml` and
> `.../macos_computer/manifest.yaml`. Fields with no live consumer are marked
> *(descriptive)* — do not add spec ahead of code.

## Minimal manifest

```yaml
schema: jros.skill/v3          # required — selects this schema
id: computer_use               # required — the skill's stable name (NOT the folder)
version: 1.0.0                 # required — semver; git holds history

origin: human_authored         # human_authored | agent_authored
package: code_skill            # code_skill (registers tools) | playbook (SKILL.md only)
runtime: in_process            # where it runs

description: >                 # the routing nudge the agent reads — write it well
  One-paragraph what/when/why. State the preferred alternative if this is a
  fallback (e.g. "on macOS, prefer macos_computer — 10-30× faster").

entrypoint:
  module: computer_use         # module inside the folder (relative — folder rename-safe)
  attr: register               # called at load to register the skill's tools
```

`id` and `entrypoint.module` are independent of the folder name — the loader
resolves by `id`, so renaming the folder (e.g. dropping a legacy `_v1`) needs no
manifest change, only fixing internal absolute imports.

## Full field set (as used today)

```yaml
domains: [productivity, sensing]     # coarse grouping

embodiment:                          # where the skill can run / what it drives
  platforms: [macos, linux, windows] # discovery hides it off-platform
  bodies: []
  sensors: []
  actuators: []

permissions:
  tier: 2                            # permission tier (see permissions_pipeline.md)
  resource_scopes:                   # what it touches — display / subprocess / fs.workspace / clipboard / …
    - display
    - subprocess

capabilities:                        # one per registered tool surface; each self-benchmarks
  - id: screen_control
    signature: "computer_<screenshot|click|type|press|menu>(...) -> {ok, ...}"
    description: >
      What this capability does.
    level:
      current: 2                     # current competence band
      bands: [0.4, 0.6, 0.75, 0.85, 0.92]   # score thresholds per level
      scorer: tests/smoke_test.py    # runnable scorer — the self-improvement gate

dependencies:                        # *(descriptive today — no resolver wires these yet)*
  tools: []
  capabilities: []
  commands: []
```

## Notes
- **`capabilities[].scorer`** is the live hook into the self-improvement pipeline
  (`skill_self_improvement_pipeline.md`): smoke gate → scored benchmark →
  keep-better / rollback.
- **`tier`/`fallback` routing** for *playbook* discovery lives in SKILL.md
  frontmatter, not here. A code skill nudges routing through its `description`
  (both computer skills do) — there is no manifest-level `tier` reader today, so
  don't add one without a consumer.
- **`dependencies`** is declared but not yet resolved by anything — descriptive.
