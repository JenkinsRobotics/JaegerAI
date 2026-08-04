# STATUS

> Truthful, or it's worthless. Any commit that changes behavior updates
> this file in the same commit — see `CONVENTIONS.md` → "STATUS stays
> truthful." This is a seed; replace everything below once the repo has
> real history.

## Current state — {{DATE}}

- **Repo:** `{{REPO_NAME}}` — {{DESCRIPTION}}
- **Version:** see `VERSION` / `pyproject.toml`'s `dynamic` version field
- **JaegerOS pin:** not yet set — fill in once `pyproject.toml.example`
  has a real dependency range (see README checklist)
- **What works:** nothing yet — this is a freshly-scaffolded template
  instance
- **What's stubbed:** every `*.example` file under `src/{{package_name}}/`
  — `module.yaml`, `config.py`, `node.py`, the module-contract test
- **Known gaps:** (list real ones here as they appear; delete this line
  once there's real content)

## How to update this file

1. Ship a behavior change.
2. In the same commit, add or edit a line above reflecting the new truth.
3. If something moves from "planned" to "shipped," delete it from
   `../roadmap/` (or mark it done there) — don't leave the same fact
   living in two docs, per `CONVENTIONS.md` law 1.
