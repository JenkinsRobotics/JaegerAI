# Skill sharing pipeline — runtime tiers + promotion path

> Companion to [[marketplace_spec]]. That doc covers the *internet*
> hop: agent → packaged bundle → public GitHub marketplace → other
> users. This doc covers the *runtime* hops *before* that:
> agent → shared-on-this-machine → official-in-framework.
>
> The operator framed the problem as: "an agent edited a skill,
> theoretically it was a good edit — what's the pipeline for that
> improvement to reach other agents? Ideally the modified or new skill
> lives alongside the official one as a branch other agents can use."
>
> This is the design that answers that.

---

## 1. The four-tier resolution model

JROS today has two skill locations:

```
jaeger_os/skills/                         (a) official, framework-shipped, read-only
.jaeger_os/instances/<name>/skills/       (b) per-instance, agent-writable
```

A skill in (b) shadows the same-named skill in (a). The agent edits
(b) freely; (a) is git-tracked and only the maintainer changes it.

This works for one agent. It doesn't answer "how does Lilith's
improved `web_search` reach the Operator instance running on the same
laptop without the operator manually copying files?"

The proposal: **insert a third tier between (a) and (b), and a fourth
tier above (a) for the network hop.**

```
┌────────────────────────────────────────────────────────────┐
│ (d) MARKETPLACE — public github catalog                    │  ← marketplace_spec.md
│     anybody on the internet, manual maintainer review      │
└─────────────────────▲──────────────────────────────────────┘
                      │ submit_skill  (EXTERNAL_EFFECT, asks)
                      │
┌─────────────────────┴──────────────────────────────────────┐
│ (a) OFFICIAL — jaeger_os/skills/                           │
│     git-tracked, framework-shipped, READ-ONLY at runtime   │
│     maintainer absorbs from (c) or (d) by hand             │
└─────────────────────▲──────────────────────────────────────┘
                      │ ./run.sh skill absorb <name>   (operator + maintainer only)
                      │ never agent-accessible
                      │
┌─────────────────────┴──────────────────────────────────────┐
│ (c) SHARED — .jaeger_os/shared_skills/                     │   ← NEW in 0.3.0
│     per-machine pool, multi-agent visible                  │
│     resolution: highest version wins, all instances see it │
└──────────▲──────────────────────────────────────▲──────────┘
           │ accept_skill (operator-gated)        │ read at every turn
           │                                      │
┌──────────┴──────────────┐  ┌────────────────────┴─────────┐
│ (b1) AGENT — instance A │  │ (b2) AGENT — instance B      │
│   .jaeger_os/instances/ │  │   .jaeger_os/instances/      │
│   <a>/skills/           │  │   <b>/skills/                │
│   agent-writable        │  │   agent-writable             │
└─────────────────────────┘  └──────────────────────────────┘
           │ propose_skill (agent verb, asks operator)
           ▼
       (becomes a pending entry in (c)'s inbox)
```

### What each tier is for

| Tier | Path | Writer | Reader | Lifetime | Versioned? |
|------|------|--------|--------|----------|------------|
| (a) Official | `jaeger_os/skills/` | maintainer (humans) | all instances on every machine | survives upgrades, ships with framework | by git tag |
| (c) Shared | `.jaeger_os/shared_skills/` | operator (via `accept_skill`) | all local instances | survives across instances, lives on the operator's machine | yes (`v1/`, `v2/`...) |
| (b) Per-instance | `.jaeger_os/instances/<n>/skills/` | the agent in `<n>` | only `<n>` | tied to that instance's lifetime | yes |
| (d) Marketplace | GitHub repo | submitters | network | network-lived | by tag |

---

## 2. Resolution order at load time

When the skill loader resolves a skill called `web_search`:

```python
candidates = []
candidates += list_skills(layout.shared_dir)       # (c)
candidates += list_skills(layout.instance_skills)  # (b)
candidates += list_skills(framework_skills_path)   # (a)

# Pick highest semantic version. Ties broken by tier: instance > shared > official.
# (so a local agent can still override a shared version it doesn't like)
chosen = max(candidates, key=lambda s: (s.version, s.tier_rank))
```

This makes shared (c) *the* place to promote across instances, while
still letting any individual agent override locally if they want to
fork.

**Resolution properties we want:**

- Instance never reaches into another instance's skills directly —
  that's a sandbox break. Promotion always goes through (c).
- Shared skills shadow official by version. If the framework ships
  `web_search v3` but the operator accepted `web_search v4` from
  Lilith's improvement, every instance gets v4 until the framework
  catches up.
- The framework can never be silently replaced. Tier (a) is read-only
  at runtime; the loader copies, never edits.

---

## 3. The promotion verbs

Three new agent-callable verbs + one operator-only CLI verb.

### `propose_skill(name, version, notes)` *(agent verb)*

What the agent calls when it wants its improved skill to be available
to other instances on this machine.

- Tier-gated to **EXTERNAL_EFFECT** (it affects state outside the
  agent's own sandbox).
- Routes through ask-user confirmation by default — operator sees:
  > "Lilith wants to publish `web_search v4` from its instance to
  > shared. Diff vs current shared (`v3`):
  >
  > +12 lines / -4 lines. Notes: 'handles empty-result case better.'
  >
  > Accept? [y/N/diff]"
- Outcome: the skill is *copied* (not moved) into
  `.jaeger_os/shared_skills/_inbox/<name>-<version>-<instance>/`.
  It does **not** auto-promote — the operator still has to accept it.
  The inbox is a quarantine.

### `list_shared_skills()` *(agent verb, read-only)*

Returns the names + versions of skills currently in shared. Tier-gated
to **CORE** (read-only, no side effects). Lets one agent ask "what's
in the shared pool I could learn from?"

### `pull_shared(name)` *(agent verb)*

Copies a shared skill into the instance's own skills dir, so the agent
can read it / fork it / adapt it. Tier-gated **STATE_WRITE** (its own
sandbox only). Skips ask-user — it's a sandboxed copy.

This is the symmetric verb to `propose_skill`. propose pushes up; pull
brings down.

### `./run.sh skill accept <name>-<version>-<instance>` *(operator CLI)*

The promotion gate. Operator reviews the inbox entry — runs smoke test
+ shows the diff vs current shared — then either accepts (moves it to
`.jaeger_os/shared_skills/<name>/<version>/`) or rejects (deletes
the inbox entry).

Sister verbs:
- `./run.sh skill list` — show shared + inbox
- `./run.sh skill diff <name> <a> <b>` — inter-version diff
- `./run.sh skill reject <name>-<version>-<instance>`
- `./run.sh skill absorb <name>` — for *maintainers only* — copies
  current shared version into framework skills (tier a). This is what
  the marketplace_spec calls the framework-integration step. It's a
  CLI rather than an agent verb because (a) is sacred.

---

## 4. Sandboxing — the security model

The whole point of tier (b) being agent-writable is that we trust the
agent inside its own sandbox. Sharing breaks that trust boundary; we
have to make it safe.

### What the agent **cannot** do

- Read another instance's `(b)` skills directly. `_resolve_read` only
  permits the agent's own instance dir + the official + the shared
  pool. Cross-instance reads return `SandboxError`.
- Write to `(c)` without the operator. `propose_skill` writes to the
  inbox, not the active pool. The active `shared_skills/<name>/`
  directory is operator-write-only.
- Write to `(a)`. The framework dir is read-only at runtime, period.

### What the operator gets at acceptance time

Before promoting an inbox entry to shared, the operator sees:

1. **Diff** vs the current shared version (or "new skill" if none).
2. **Smoke test result** — `skill_manifest.json`'s declared smoke test
   runs in a clean throwaway instance dir, output captured.
3. **Tool surface declared** — which tools the new skill calls. If it
   newly calls something the prior version didn't, that's flagged
   loudly. ("`web_search v4` adds calls to `delete_file` — accept?")
4. **Permission posture** — the highest tier any of its tool calls
   sits at. Skills calling EXTERNAL_EFFECT tools get a different color.
5. **Provenance** — instance name that proposed it, timestamp, agent's
   notes.

This mirrors the package-acceptance flow most package managers use
(npm install --review style) but local-first and with a real smoke
test in the loop.

### Audit trail

Every promotion writes to `.jaeger_os/shared_skills/_log.jsonl`:

```json
{"ts": "2026-...", "action": "accept", "name": "web_search", "version": "4", "from": "lilith", "by": "operator", "diff_lines": 16}
{"ts": "2026-...", "action": "reject", "name": "delete_repo", "version": "1", "from": "lilith", "reason": "calls rm -rf on workspace"}
```

So when something goes wrong we can rewind: which skill, which version,
which agent proposed it, when the operator accepted.

---

## 5. What this enables

### Fleet learning, opt-in

Run two instances on the same machine — say `lilith` (companion) and
`operator` (computer_use heavy). They each improve their own skills.
Lilith's improved `summarize_url` benefits Operator the moment the
operator promotes it. Operator's improved `accessibility_click`
benefits Lilith likewise. No file shuffling, no manual export.

### Safe forking

Operator instance wants `web_search v4` but with one tweak. It calls
`pull_shared("web_search")` → gets v4 into its own dir → edits to v4.1
locally → if good, proposes back to shared. Now both instances run v4.1
once the operator accepts; v4 is gone.

### Path to the marketplace

A shared skill that has lived through several version bumps and proved
itself is the natural candidate for `submit_skill` to publish to the
public marketplace. Shared → marketplace is just a `submit_skill` call
with the operator's confirmation. (See marketplace_spec for the
network-side details.)

### Path back into the framework

`./run.sh skill absorb` is the maintainer-only inverse — copies a
mature shared skill back into `jaeger_os/skills/` as the new official
version, removing it from shared. This is what closes the loop: an
agent's improvement, validated across instances, can graduate into the
framework next release.

---

## 6. Implementation outline

In dependency order; estimates are rough:

### 6.1 Loader + resolution *(2 days)*
- New `layout.shared_skills_dir` property → `.jaeger_os/shared_skills/`
- Loader scans (c) before (b) before (a), picks highest version
- Sandbox: `_resolve_read` allows shared dir (read-only) for the agent

### 6.2 `propose_skill` + inbox *(1.5 days)*
- Agent verb that copies `<instance>/skills/<name>/v<n>/` to
  `shared_skills/_inbox/<name>-<version>-<instance>/`
- Wire to EXTERNAL_EFFECT tier → ask_user prompt
- Manifest validation before accepting the proposal

### 6.3 Operator review CLI *(2 days)*
- `./run.sh skill list/accept/reject/diff` subcommands
- Diff is just `difflib.unified_diff` between manifest + skill files
- Smoke test runs in a throwaway tmp instance, output captured

### 6.4 `pull_shared` + `list_shared_skills` *(0.5 day)*
- Sandboxed copy and listing — trivial once the loader knows about (c)

### 6.5 Audit log *(0.5 day)*
- Append to `_log.jsonl` on accept/reject/absorb

### 6.6 Tests *(1 day)*
- Two-instance integration: lilith proposes → operator accepts →
  the other instance loads the new version on its next turn
- Sandbox tests: instance A can't read instance B's skills directly

Total: ~7 days of focused work. Fits in 0.3.0's Tier 1 1.3 slot
([[odysseus_review_and_0.3.0_plan]] § Tier 1).

---

## 7. What this doc deliberately doesn't try to solve

- **Auto-merge across instances.** No automatic policy. The operator
  remains the merge button. Auto-merge is a way to wake up to a
  surprise.
- **Conflict resolution between two agents' edits of the same skill.**
  Resolved by version number — last accepted wins. If both propose
  v4 with different code, the operator picks one (and the loser can
  re-fork from the winner's v4).
- **Cross-machine sync.** Out of scope — that's the marketplace's job.
  This doc is per-machine only.
- **Trust delegation.** No "auto-accept from instances tagged
  trusted." Every promotion is an operator decision in v1. Maybe a
  later policy switch, but not 0.3.0.

---

## 8. Names that need agreeing on

A few terminology calls before this lands:

- `propose_skill` vs `publish_skill` vs `share_skill` — *propose* is
  the most honest (it goes into an inbox, not directly live).
- `accept_skill` vs `approve_skill` vs `merge_skill` — *accept* matches
  the verb the user actually performs.
- `.jaeger_os/shared_skills/` vs `.jaeger_os/skills_shared/` vs
  `.jaeger_os/skill_pool/` — match the convention in
  [[instance_layout]] (everything-`<noun>_dir`). Suggest
  `shared_skills/`.

Locking these names in is the first commit, before any code lands.
