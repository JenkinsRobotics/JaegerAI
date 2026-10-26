# JROS Skill Schema v3

**Status:** draft for 0.3.0. Spec lives here; implementation lands in
`jaeger_os/core/skills/`. Once shipped, this doc is the contract.

## What v3 is

A **single multi-axis manifest envelope** that describes every kind of
skill JROS can load — today's Python skills, today's markdown
playbooks, tomorrow's MCP servers, behavior trees, and learned
policies — without forcing parallel schemas per type.

The envelope is informed by:

- The current shipped `<name>_v<N>/SKILL.md` frontmatter (which
  already uses `category`, `runtime`, `permission_tier`,
  `embodiment_requires` — see
  [computer_use_v1/SKILL.md](../jaeger_os/skills/computer_use_v1/SKILL.md))
- The Lilith-line scaffolding in
  [registry.py](../jaeger_os/core/skills/registry.py) (cognitive vs
  physical category, tier-based permissions, deferred-import
  discovery)
- The procedural-skill catalog in
  [playbook_skills.py](../jaeger_os/core/skills/playbook_skills.py)
  (the nested `SKILL.md` files under `apple/`, `research/`, etc. that
  the `skill` tool already discovers)
- A reviewer pass against industry references (ROS 2 interface
  separation, MoveIt capability/adapter split, HuggingFace model
  cards, MLflow experiment lineage, MCP boundary)

## Design principles

1. **Taxonomy and runtime are different axes.** `physical` is a
   *domain*, `policy_server` is a *runtime*. A learned manipulation
   policy and a markdown playbook for a manipulation procedure both
   live in the `physical` domain but use different `package` and
   `runtime` fields.
2. **Capabilities are the unit of scoring.** A skill is a bundle of
   named callable capabilities. Each capability has its own level,
   bands, scorer, and history. The skill-level "score" is a derived
   summary, never source of truth.
3. **Closed enums for the structural axes.** `package`, `runtime`,
   and `origin` are fixed enums for v3. Adding a variant is a
   deliberate framework change (bump to v4), not a YAML edit.
4. **Artifacts are referenced, not vendored.** Manifests carry
   `path` or `uri` + `sha256` + `size_bytes`. Where the bytes live is
   a separate concern (0.3.0: local path; 0.4.x: content-addressed
   store).
5. **Provenance is data.** Per-instance copies of upstream skills
   carry a `provenance` block that says where they forked from. No
   guessing at review time.

## The envelope

```yaml
# Identity ---------------------------------------------------------
schema: jros.skill/v3      # required, exact string
id: pick_and_place         # required, snake_case, matches dir basename
version: 2.1.0             # required, semver

# Provenance (who authored, where from) ---------------------------
origin: human_authored
# enum: human_authored | agent_authored | marketplace | imported

# Execution shape (how it runs) -----------------------------------
package: code_skill
# enum: code_skill | playbook | tool_bundle | mcp_server
#       | behavior_tree | policy
runtime: in_process
# enum: in_process | subprocess | mcp | ros2_action
#       | policy_server | external

# What it's about (free of execution detail) ----------------------
domains: [physical, manipulation]
# enum elements: cognitive | physical | social | game | media
#                | devops | productivity | research | sensing | other
description: "Pick an object from a flat surface, place at a target pose."

# What it needs from the host or body -----------------------------
embodiment:
  platforms: [linux]            # macos | linux | windows | any
  bodies: [jp01]                # robot platform ids; [] = no body required
  sensors: [camera.rgb]
  actuators: [arm, gripper]

# Authorization ----------------------------------------------------
permissions:
  tier: 3                       # 0..5, see core PermissionTier
  resource_scopes:
    - arm.motion
    - gripper.control
    - camera.rgb

# The actual API the skill exposes -------------------------------
capabilities:
  - id: pick
    signature: "pick(object_id: str) -> PickResult"
    description: "Grasp an object at the inferred grasp pose."
    level:
      current: 7
      bands: [0.5, 0.7, 0.8, 0.9, 0.95]   # → quantised levels 1..5
      scorer: tests/eval_pick.py            # produces {score, passed, total}
  - id: place
    signature: "place(object_id: str, target_pose: Pose) -> PlaceResult"
    description: "Place an object at the requested pose."
    level:
      current: 4
      bands: [0.5, 0.7, 0.8, 0.9, 0.95]
      scorer: tests/eval_place.py

# Static dependencies (resolved at load) --------------------------
dependencies:
  tools: [object_detection_v3]
  capabilities:
    - "spatial_awareness.pick_pose>=5"   # other-skill.capability comparator
  commands: [moveit_node]                # OS-level binary requirements

# Big files referenced, not vendored -------------------------------
artifacts:
  - id: policy
    kind: onnx                  # onnx | torch | gguf | bt_xml | other
    path: artifacts/policy.onnx # local-relative for 0.3.0
    sha256: 5f3e8a...
    size_bytes: 28411203
    license: apache-2.0

# Entrypoint (per-package conventions) ----------------------------
entrypoint:
  module: pick_place.server     # for code_skill / mcp_server / policy
  attr: register                # callable name
# Playbook packages omit `entrypoint`; the `body` field below carries
# the markdown the `skill` tool returns.
# body: |-
#   ## When
#   ## How
#   ...
```

## Per-instance copies — what gets added

When an agent or operator forks an upstream skill into
`<instance>/skills/<id>/`, the manifest gains a `provenance` block:

```yaml
provenance:
  upstream_id: pick_and_place
  upstream_version: 2.1.0
  base_sha256: 5f3e8a...        # hash of upstream manifest at fork time
  forked_at: "2026-06-04T18:00:00Z"
  forked_reason: "Fine-tuned for delicate glass objects"
  fork_chain:                   # optional; if the upstream was itself a fork
    - { id: pick_and_place, version: 2.0.0, sha256: 4a1b... }
```

`provenance.base_sha256` is what the `propose_skill` review path
diffs against when an operator considers promoting the fork back
upstream.

## Per-instance runtime state

Alongside `manifest.yaml`, instance copies hold:

```
<instance>/skills/<id>/
  manifest.yaml         # full v3 manifest (with provenance block)
  state.yaml            # current levels + counters
  history.jsonl         # one line per execution, scored
  provenance.yaml       # (optional) extra diff metadata
```

### `state.yaml`

```yaml
schema: jros.skill_state/v1
skill_id: pick_and_place
skill_version: 2.1.0
capabilities:
  pick:
    current_level: 7
    runs_total: 142
    runs_at_current_level: 18
    last_score: 0.91
    last_run_at: "2026-06-04T17:50:11Z"
  place:
    current_level: 4
    runs_total: 137
    runs_at_current_level: 7
    last_score: 0.74
    last_run_at: "2026-06-04T17:50:11Z"
```

### `history.jsonl`

One line per execution:

```jsonl
{"ts":"2026-06-04T17:50:11Z","cap":"pick","score":0.91,"passed":18,"total":20,"artifact":"policy@5f3e8a"}
{"ts":"2026-06-04T17:50:11Z","cap":"place","score":0.74,"passed":15,"total":20,"artifact":"policy@5f3e8a"}
```

## Closed enums (v3)

### `package`

| value | meaning | 0.3.0 status |
|---|---|---|
| `code_skill` | Python module exposing `register(agent)` | implemented |
| `playbook` | Pure markdown procedure surfaced via the `skill` tool | implemented |
| `tool_bundle` | Atomic tool set with no composed capabilities (rare) | reserved |
| `mcp_server` | Out-of-process server speaking MCP | reserved (0.4.x) |
| `behavior_tree` | Composable BT description (XML / JSON) | reserved (0.5.x / JP01) |
| `policy` | Learned-policy artifact loaded by a host adapter | reserved (0.5.x / JP01) |

Reserved values can appear in manifests for forward compatibility,
but the 0.3.0 loader rejects them with a clear "not supported yet"
error. They are listed here so the schema itself doesn't need a
version bump when the loader catches up.

### `runtime`

| value | meaning | 0.3.0 status |
|---|---|---|
| `in_process` | Loaded into the agent process via importlib | implemented |
| `subprocess` | Spawned as a child process; speaks JSON over stdio | reserved (0.4.x) |
| `mcp` | Communicated with via MCP transport | reserved (0.4.x) |
| `ros2_action` | ROS 2 action client | reserved (0.5.x / JP01) |
| `policy_server` | Long-lived inference process | reserved (0.5.x / JP01) |
| `external` | Hosted somewhere else (HTTP) | reserved |

### `origin`

`human_authored | agent_authored | marketplace | imported`

Matches the curator's existing `origin` distinction. The curator
([curator.py](../jaeger_os/core/skills/curator.py)) only ever touches
`agent_authored` skills; everything else is protected from archival
regardless of usage staleness.

### `domains`

Multi-valued; a skill can be `[physical, manipulation]` or `[cognitive,
game]`. The closed set for v3:

```
cognitive | physical | social | game | media
| devops | productivity | research | sensing | other
```

`other` is the escape hatch — but skills using it are encouraged to
propose a new domain via a doc patch instead of letting `other`
accumulate.

## Resource scopes (v3 closed vocabulary)

Permission scopes are the operator-facing contract for *what a skill
is allowed to touch*. Tier alone isn't enough: a "tier 2" skill that
reads files in `~/.ssh` is very different from a "tier 2" skill that
sends an outbound HTTPS request.

### Host-side scopes (v3)

| scope | grants |
|---|---|
| `net.outbound` | Any outbound HTTP/TCP. Prefer narrower. |
| `net.outbound:<host>` | Outbound to a host pattern (`api.openai.com`, `*.github.com`) |
| `fs.workspace` | Read/write under `<instance>/workspace/` |
| `fs.host` | Read host filesystem outside workspace (rare; requires explicit grant) |
| `subprocess` | Spawn child processes |
| `display` | Show GUI windows / take screenshots |
| `audio.in` | Microphone input |
| `audio.out` | Speaker output |
| `clipboard` | Read or write the system clipboard |

### Robot-side scopes (reserved, declared not enforced in 0.3.0)

| scope | grants | enforced in |
|---|---|---|
| `camera.rgb` | RGB camera frames | 0.5.x / JP01 |
| `camera.depth` | Depth camera frames | 0.5.x / JP01 |
| `arm.motion` | Arm joint commands | 0.5.x / JP01 |
| `gripper.control` | Gripper open/close/force | 0.5.x / JP01 |
| `base.motion` | Drive base motion commands | 0.5.x / JP01 |
| `imu.read` | IMU stream | 0.5.x / JP01 |
| `lidar.read` | Lidar stream | 0.5.x / JP01 |

The vocabulary extends at JP01. Adding scopes is a deliberate
framework change tracked in this doc, not a free-for-all per skill.

## Capability blocks — scoring + leveling

Every capability declares its scorer and level bands:

```yaml
capabilities:
  - id: pick
    signature: "pick(object_id: str) -> PickResult"
    description: "..."
    level:
      current: 7
      bands: [0.5, 0.7, 0.8, 0.9, 0.95]
      scorer: tests/eval_pick.py
```

### Scorer contract

A scorer is an executable script. When run, it prints ONE JSON object
to stdout:

```json
{"score": 0.91, "passed": 18, "total": 20, "notes": "..."}
```

Same shape as the existing
[skill_benchmark.py](../jaeger_os/core/skills/skill_benchmark.py)
contract. v3 inherits it verbatim.

### Level computation

- Bands are sorted ascending; default `[0.5, 0.7, 0.8, 0.9, 0.95]`
  yields levels 1..5.
- Level *raises* by one when the capability's last `N=3` runs all
  scored above the next-higher band threshold. This is conservative
  by design — one good run doesn't promote.
- Level *holds* when scores fluctuate within the current band.
- Level *drops* by one when last `N=3` runs all scored below the
  current band's floor. The library doesn't lie about regressions.

The `max` level is the number of bands. Levels > number-of-bands are
not v3-valid; if a skill wants higher resolution it adds bands.

### Skill-level summary (derived)

For routing convenience, the loader exposes a `skill.level_summary`
property:

```python
skill.level_summary == min(cap.level.current for cap in skill.capabilities)
```

The minimum is intentional: a skill that excels at `pick` but is
weak at `place` should be routed as the lower number. Callers that
want the average or maximum compute it themselves.

## Loader behavior

### Discovery

The unified loader scans:

1. `jaeger_os/skills/` (core, read-only)
2. `<instance>/skills/` (instance, agent-writable)

For each candidate directory, it tries (in order):

1. `manifest.yaml` — v3 canonical. Parse and validate.
2. `SKILL.md` with `schema: jros.skill/v3` in frontmatter — v3 in the
   legacy SKILL.md container. Parse the frontmatter.
3. Legacy `<name>_v<N>/SKILL.md` (no v3 schema declared) — generate
   a stub v3 manifest at load time:

   ```yaml
   schema: jros.skill/v3
   id: <name>
   version: 0.<N>.0           # legacy v<N> → 0.<N>.0
   origin: human_authored
   package: code_skill
   runtime: in_process
   domains: [other]            # operator can refine
   permissions:
     tier: <from SKILL.md or default 0>
     resource_scopes: []
   capabilities:
     - id: legacy
       signature: "register(agent)"
       level:
         current: 1
         bands: [0.5]
         scorer: tests/smoke_test.py
   entrypoint:
     module: <discovered>
     attr: register
   ```

   …and emit a deprecation entry in `audit.log`:
   `[skill] generated v3 stub for legacy '<name>_v<N>'; port at your convenience`.

### Resolution

Within each zone, the loader keeps the **highest semver per skill
`id`**. Across zones, **instance wins over core** (same as today).

### Validation

The loader rejects manifests that:

- Lack `schema: jros.skill/v3`.
- Have a `package` or `runtime` value not in the 0.3.0
  implemented set.
- Declare resource scopes outside the v3 vocabulary.
- Have `capabilities` empty (every skill must expose at least one
  capability — `register(agent)` counts).
- Have `permissions.tier` outside `0..5`.

### Loaded shape

The loader returns a `LoadedSkill` discriminated by `package`:

```python
LoadedSkill(
  id: str,
  version: str,
  package: Literal["code_skill","playbook",...],
  manifest: Manifest,            # the full validated v3 manifest
  zone: Literal["core","instance"],
  folder: Path,
  source: PythonModule | PlaybookBody | ...,  # package-specific
)
```

`source` carries whatever the runtime needs:

- `code_skill` → the importlib-loaded module
- `playbook` → the markdown body string (already the case in
  `playbook_skills.py`)
- reserved kinds → not produced in 0.3.0

## What v3 does NOT do (deferred)

- **Content-addressed artifact store** (0.4.x). v3 manifests carry
  `sha256` + `path` so 0.4.x can drop in a content store without
  schema changes.
- **Signed bundles + lockfiles** (0.4.x). Manifests carry enough
  identity for a future signing layer to wrap them.
- **MCP / subprocess runtime adapters** (0.4.x). Reserved enums.
- **ROS 2 action wire protocol** (0.5.x / JP01). Reserved `runtime`
  value; capability *signatures* can already describe long-running
  goal/feedback shape via type annotations.
- **Sim/eval harnesses** (0.5.x / JP01). The capability scorer
  contract is the seed; sim-backed scorers are runtime-side work.
- **Federated learning aggregation** (Lilith / fleet line).
- **Run records keyed by skill/capability/artifact hash** (0.4.x —
  graduates `history.jsonl` into a real run store).

## Migration plan (concrete)

| step | what | when |
|---|---|---|
| 1 | Land v3 envelope spec (this doc) | 0.3.0 |
| 2 | Implement unified loader: read v3 from `manifest.yaml` or `SKILL.md` frontmatter; generate stub for legacy `<name>_v<N>` | 0.3.0 |
| 3 | Retire `registry.py`; fold its tier validation + deferred-import behavior into the unified loader | 0.3.0 |
| 4 | Wire capability scoring + level computation against `skill_benchmark.py` output | 0.3.0 |
| 5 | Port `computer_use_v1` and `macos_computer_v1` to v3 `manifest.yaml` | 0.3.0 |
| 6 | Give each playbook (`apple/apple-notes/SKILL.md` etc.) a v3 `manifest.yaml` so the catalog is properly registered | 0.3.0 → 0.4.0 |
| 7 | Drop legacy stub generation; require v3 manifests | 0.4.0 |

## Open questions parked for later

- **Capability composition.** A skill that calls another skill's
  capability — is that a dependency edge or a delegated call? v3
  models it as a dependency (`dependencies.capabilities`). The
  *call* mechanics are a runtime concern.
- **Versioned signatures.** A capability's signature is a string in
  v3. Eventually we'll want typed signatures (Pydantic / Protobuf).
  Held until we see the first signature compatibility break.
- **Cross-skill identity.** Two skills could both declare
  `capabilities[].id: pick`. v3 keeps them separate (qualified by
  skill id). A capability-id ontology / namespace is a Lilith-line
  concern.
- **Operator-facing scope UI.** The wizard / chat surface needs to
  show resource scopes when a skill asks to be loaded. Plumbing,
  not schema.

## Reviewers / sign-off

- 0.3.0 implementation lands against this doc verbatim.
- Schema changes require a doc patch in the same PR.
- v4 bump is reserved for breaking changes (new `package` /
  `runtime` enums that change loader behavior, new required fields).
- v3.x patches can ADD optional fields, refine docs, add reserved
  enums.
