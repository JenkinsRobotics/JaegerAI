# Jaeger-OS Skill Marketplace — specification

The marketplace lets anyone running Jaeger-OS publish a skill their
agent developed, and lets anyone else install it. A popular skill can
later be folded into a framework release by the maintainers.

**The agent never writes to the framework.** Skills flow:

```
developer's instance  ──package──▶  portable bundle  ──submit──▶  marketplace (GitHub repo)
                                                                        │
   any other instance  ◀──install──────────────────────────────────────┘
                                                                        │
   framework release   ◀──maintainer pulls a popular skill (manual)─────┘
```

The marketplace is the contribution surface. Framework integration is
a separate, maintainer-only decision — it never happens automatically.

---

## Status — what's built vs. what's left

### ✅ Built now (this commit)

- **`package_skill(name)`** agent tool + `core/skill_package.py` — bundles
  a proven instance skill into a portable `.zip` artifact with a
  generated `skill_manifest.json`. Works standalone — no marketplace
  needed to package.
- **The skill-manifest format** (below) — the metadata every published
  skill carries.
- This spec.

### ⏳ Left to finish — needs the GitHub repo to exist first

Everything below depends on **Jaeger-OS being hosted on GitHub**, because
the marketplace *is* a GitHub repo (the catalog model, same as Claude
Code's `anthropics/claude-plugins-community`). In dependency order:

1. **Create the marketplace repo** — e.g. `jenkinsrobotics/jaeger-skills`.
   It holds a top-level `marketplace.json` catalog + a `skills/`
   directory, one subfolder per published skill.
2. **Decide the submission mechanism** — two options:
   - **PR-based** (recommended): `submit_skill` forks the marketplace
     repo, adds the bundle under `skills/<name>/`, updates
     `marketplace.json`, opens a PR. A maintainer reviews + merges.
     Needs the `gh` CLI or a GitHub token.
   - **Issue-based** (simpler v1): `submit_skill` opens a GitHub issue
     with the packaged `.zip` attached + the manifest in the body. A
     maintainer manually adds it to the catalog.
3. **Build `submit_skill(name)`** — packages (reuses `package_skill`)
   then performs the submission. Tier-gated (EXTERNAL_EFFECT — it pushes
   to a public repo) → routes through confirmation.
4. **Build `search_skill(query)`** — fetches `marketplace.json` from the
   marketplace repo's raw URL, filters by name/description/category.
5. **Build `install_skill(name)`** — resolves the skill in the catalog,
   downloads its folder into `<instance>/skills/`, runs its smoke test
   before activating (reuse the skill loader's existing gating).
6. **Marketplace config** — an instance config block:
   ```yaml
   marketplace:
     repo: jenkinsrobotics/jaeger-skills
     catalog_url: https://raw.githubusercontent.com/jenkinsrobotics/jaeger-skills/main/marketplace.json
   ```
   so the registry URL isn't hardcoded.
7. **Review pipeline** (later) — automated checks on every submission:
   smoke test runs, no credential reads, no framework-zone writes,
   manifest is well-formed. Mirrors `claude plugin validate`.
8. **Framework-integration path** (later, maintainer-only) — a
   `jaeger absorb <skill>` maintainer CLI that copies a vetted
   marketplace skill into `src/jaeger_os/skills/` for the next release.
   Never agent-accessible.

### Separate prerequisite — pip-installability

The marketplace assumes users `pip install jaeger-os`. The repo's
`pyproject.toml` is already shaped for this (package discovery, entry
points, extras). Before launch, verify a clean `python -m build` +
`pip install` from a fresh checkout, and decide PyPI vs. git-install.

---

## Skill-manifest format

`package_skill` writes a `skill_manifest.json` into the bundle. This is
the record the marketplace catalog references.

```json
{
  "name": "weather_report",
  "version": 2,
  "description": "Fetches a multi-day forecast and formats it as a brief.",
  "author": "Jarvis @ jenkins-robotics",
  "category": "cognitive",
  "kind": "agent_authored",
  "permission_tier": 0,
  "dependencies": ["requests"],
  "jaeger_core_version": "0.5.7",
  "smoke_test": "pass",
  "entry_files": ["SKILL.md", "weather_report.py", "tests/smoke_test.py"],
  "packaged_at": "2026-05-19T22:40:00Z",
  "package_sha256": "…"
}
```

| Field | Source | Notes |
|---|---|---|
| `name` / `version` | skill folder name (`<name>_v<N>`) | |
| `description` / `category` / `kind` / `permission_tier` | SKILL.md frontmatter | |
| `author` | instance `identity.yaml` name + optional org | so credit travels with the skill |
| `dependencies` | declared in SKILL.md frontmatter (`requires:` / `dependencies:`) | the pip packages `install_skill` must install |
| `jaeger_core_version` | the framework version at package time | install-time compat check |
| `smoke_test` | `pass` / `fail` / `absent` — `package_skill` runs it | the marketplace should reject `fail` |
| `package_sha256` | hash of the bundle | integrity check on install |

---

## Marketplace catalog format (`marketplace.json`)

Lives at the root of the marketplace GitHub repo. `search_skill` /
`install_skill` read it via the raw GitHub URL.

```json
{
  "marketplace": "jaeger-community-skills",
  "schema_version": 1,
  "updated_at": "2026-05-19T00:00:00Z",
  "skills": [
    {
      "name": "weather_report",
      "version": 2,
      "description": "Fetches a multi-day forecast and formats it as a brief.",
      "author": "Jarvis @ jenkins-robotics",
      "category": "cognitive",
      "dependencies": ["requests"],
      "jaeger_core_version": ">=0.5",
      "source": "skills/weather_report/",
      "submitted_at": "2026-05-18T00:00:00Z",
      "reviewed": true,
      "downloads": 0
    }
  ]
}
```

Plugin-style namespacing is NOT needed at v1 — the catalog is a flat
list, and `reviewed: true` is the gate. If name collisions become a
problem, add an `author/` prefix later.

---

## Security model

- **Publishing** is tier-gated (`EXTERNAL_EFFECT`) — pushing to a public
  repo is an outward-facing action, so it routes through confirmation.
- **Installing** runs the downloaded skill's smoke test before
  activation — same gating the loader already applies to instance
  skills. A skill that fails its smoke test is not registered.
- **The agent never writes to `src/jaeger_os/`.** Marketplace skills
  install into `<instance>/skills/` like any agent-authored skill.
- **Framework absorption is maintainer-only** — a human decides which
  marketplace skill ships in a framework release. No automatic path
  from marketplace → framework.
- Installed marketplace skills are still sandboxed by the v2 contract:
  writes confined to `<instance>/skills/`, credentials off-limits,
  permission tiers enforced.

---

## Open decisions for the maintainer

1. **PR-based vs. issue-based submission** for v1. (Recommend issue-based
   to start — no `gh`/token setup needed — then graduate to PR-based.)
2. **PyPI vs. git-install** for the framework itself.
3. **Marketplace repo name + visibility** (public from day one?).
4. **Review SLA** — who reviews submissions, how fast.
5. Whether to adopt the **agentskills.io** open standard for the
   manifest (Hermes + Claude Code both align to it) so skills are
   cross-tool portable, or keep the jaeger-specific manifest above.
