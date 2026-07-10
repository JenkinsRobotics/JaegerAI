# JROS architecture — framework vs. operator state

This is the canonical reference for where every persistent file in a JROS
deployment belongs. **The boundary is the contract** — the upgrade guarantee,
the multi-instance guarantee, and the "where do I put my stuff" answer all
derive from it.

> **0.6 note.** This doc previously described a *three*-layer model (System /
> Runtime / User) with a separate user dir at `~/jaeger/agents/<name>/`. **0.2.6
> removed the User layer** (`UserConfig`, `resolve_user_dir()` deleted) and
> folded everything an agent owns into one self-contained instance folder. The
> model below is the current two-bucket reality.

---

## TL;DR

| Bucket | Where it lives | Git? | Touched by upgrades? |
|---|---|---|---|
| **Framework** | `<install_root>/jaeger_os/` (the editable-installed package) + the operator surface (`jaeger`, `install.sh`, `pyproject.toml`, `.venv/`) | tracked | **Yes — that's the upgrade** |
| **Operator state** | `<install_root>/.jaeger_os/` | ignored | Schema migrated; content preserved |

If the boundary blurs in your head, ask: *can the upgrade safely replace this?*
Framework → yes. Operator state → never (only schema-migrated, never discarded).

`<install_root>` is `$JAEGER_HOME` (default `~/jaeger`); both buckets sit side by
side under it, so `ls <install_root>` shows the framework and your data together.

---

## The OS analogy

JROS borrows the OS pattern: the **framework** is the installed program, the
**operator state** is your data, and upgrades replace the former while migrating
(never deleting) the latter.

| Concern | macOS | **JROS** |
|---|---|---|
| Program | `/Applications/…`, `/System/` | `<install_root>/jaeger_os/` (the package) |
| Your data | `~/Library/Application Support/<App>/` | `<install_root>/.jaeger_os/instances/<name>/` |
| Survives upgrades | your `~/Library` data | everything under `.jaeger_os/` |

---

## Bucket 1 — Framework (git-tracked)

**What:** the JROS code — the agent loop, the loader, built-in skills and
prompts, the model registry, the tool catalog, schemas, all the defaults.

**Where:** `<install_root>/jaeger_os/`. JROS installs **editable** (PEP 660):
the clone *is* the live package, so the framework is readable and hackable in
place. (A wheel install would land it in `site-packages/jaeger_os/`.)

**Who owns it:** the JROS project. `jaeger update` (git pull + editable
reinstall) replaces it; your `.jaeger_os/` is untouched.

**NOT here:** anything an agent authors or accrues — personas, custom skills,
memory, logs, credentials. Those are operator state. Downloaded model *weights*
are operator state too (`<install_root>/.jaeger_os/models/`); only the *registry*
of models is framework.

---

## Bucket 2 — Operator state (gitignored)

**What:** everything JROS creates and manages per agent — and the shared model
cache. Lives under `<install_root>/.jaeger_os/`:

```
<install_root>/.jaeger_os/
├── instances/<name>/        one self-contained folder PER AGENT:
│   ├── config.yaml           runtime config (the wizard's answers)
│   ├── identity.yaml         persona binding (name, role, character)
│   ├── distribution.yaml     install-method stamp (for `jaeger update`)
│   ├── manifest.json         core-version pin (drives migration)
│   ├── permissions.json      the agent's permission grants
│   ├── memory/               SQLite + facts/episodic/sessions
│   ├── logs/                 audit log + rotating runtime logs + bench output
│   ├── skills/               the agent's own authored skill versions
│   ├── credentials/          API keys / tokens (0600; never read directly)
│   ├── workspace/            agent ↔ operator file exchange
│   └── run/                  pidfiles / sockets for the live process
├── models/                  shared GGUF weight cache (survives instance deletes)
└── jaeger.env               machine-wide operator env
```

**Self-contained:** to share or back up an agent, zip its `instances/<name>/`
folder — there is no separate "user dir" to track since 0.2.6. To hand someone
your Lilith, hand them the folder.

**Multi-instance:** `instances/lilith/` and `instances/eren/` coexist with fully
separate state and share the one framework install.

**Update contract:** JROS may **rename / add / restructure** anything under
`instances/<name>/` between minor releases; a migration preserves your content
(memory, skills, …) while the *layout* is JROS's to change. `manifest.json` pins
the version so `jaeger update` knows what to migrate. Don't hand-edit here except
where documented (e.g. `config.yaml`).

---

## How JROS finds model weights

Weights are heavy (1–30 GB) and aren't framework, so they live in the operator
cache and resolve (see `jaeger_os/core/models/model_resolver.py`) in this order:

1. `<install_root>/.jaeger_os/models/<key>/<file>` — the operator cache (production)
2. `jaeger_os/models/<file>` — package-local dev convenience (symlinks to LM Studio)
3. `~/.lmstudio/models/…` — existing LM Studio cache (scanned, not copied)
4. a Hugging Face Hub download on first use

The cache survives instance deletion and is shared across instances. The legacy
`~/.jaeger/models/` location is still honoured as a fallback for old installs.

---

## For upstream development

Before choosing a file path, ask which bucket a thing belongs to:

- Changes for **every** agent, shipped by JROS? → **Framework** (in the package).
- Per-agent state JROS creates/manages at runtime? → **Operator state**
  (`<install_root>/.jaeger_os/instances/<name>/…`).

If a feature spans both (e.g. a skill the operator customises), ship a **default
in the framework** and let the agent **write its override** into its instance
`skills/` — the loader's instance-wins-over-core resolution handles the
fall-through.

---

*Last updated: 0.6 — rewritten from the pre-0.2.6 three-layer model to the
current two-bucket (framework + operator state) reality; see CHANGELOG 0.2.6 for
the User-layer removal and the 2026-06-25 packaging note in
`dev/docs/reality/STATUS.md` for the editable-install model.*
