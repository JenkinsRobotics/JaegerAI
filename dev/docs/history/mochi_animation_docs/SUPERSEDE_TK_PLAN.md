# Supersede `gui/mochi_gui.py` (Tk debug panel) into `gui/mochi_companion.py`

**Date:** 2026-06-10
**Branch:** mochi-v4
**Goal:** every working feature in the legacy Tk panel ends up in the
new companion app.  No regressions.  Tk panel is then disabled in
`config.yaml` and eventually deleted.

## Operator brief

> *"i want to supersede the conceptual mochi manual control tk widget
> i made with the new mochi app we are developing… we don't want to
> lose function but it should be superseded into the new app"*

## Audit — every feature of the Tk panel

| # | Tk feature (`mochi_gui.py`) | Today | Used how often? |
|---|---|---|---|
| 1 | **Node Status bar** — Mode / Size / FPS / Mem (MB) / Tx (MB/s) for the selected node | Real-time updating top strip from `node.<id>.health` broadcasts | Constantly — operator's "is everything alive?" glance |
| 2 | **Nodes table** — multi-node view with Mode / Size / FPS / Mem / Tx columns | Treeview that grows as health broadcasts arrive | Useful for multi-plugin setups |
| 3 | **Mode entry + Turn On / Turn Off / Reset buttons** | Operator types a mode name + clicks a button | Daily, but **typing the name is the worst part** of the UX |
| 4 | **MochiScript dropdown** — auto-populates from `assets/mscripts/*.mscript` + Run / Stop | Pick a script + Run | Daily — scripted sequences are a core demo flow |
| 5 | **Color picker + RGB entry** + target (current / solid_color) | Send `color <r> <g> <b>` or `color solid_color <r> <g> <b>` | Rarely — usually for solid_color fallback or single-static tinting |
| 6 | **Matrix size (WxH) field + Apply** | Send `size <w>x<h>` | One-time per session at most |
| 7 | **Raw Command** entry — operator types arbitrary text | Power-user escape hatch | Rarely, but **must keep** for debugging |
| 8 | **Launch Virtual Display** button | Spawns `gui/mochi_vdisplay.py` as subprocess | Daily |
| 9 | **Launch Performance Monitor** | Spawns `gui/mochi_perf.py` | Occasionally |
| 10 | **Launch Sprite Editor** | Spawns `tools/sprite_editor_gui.py` | Authoring sessions |
| 11 | **Quit Node** button — sends `quit` to ctrl socket | Stops the active node process | End-of-session |
| 12 | **Health subscriber thread** — non-UI plumbing | Listens on `node.` prefix; updates rows 1+2 in real time | Always-on background |
| 13 | **Subprocess tracking** — kills spawned helpers on close | Bookkeeping | Cleanup hygiene |

Twelve user-visible features + one background service.

## Information architecture in the new companion

The new home for each Tk feature, mapped to existing or new
companion surfaces:

| Tk feature | New home | New surface name |
|---|---|---|
| 1. Node Status bar | **Top toolbar** (next to "Open Mini Window") | Persistent status pill |
| 2. Nodes table | **Home tab** → Diagnostics card | "Active nodes" panel |
| 3a. Mode Turn On (named) | **Library card click** (already works) | Native to v4 |
| 3b. Mode Turn Off | **Top toolbar** | "Stop" button next to mini-window toggle |
| 3c. Mode Reset | **Settings → Renderer** (Advanced) | Reset button per node |
| 4a. MochiScript Run | **Library filter TYPE=mscripts → click card** (already works) | Native to v4 |
| 4b. MochiScript Stop | Top toolbar "Stop" | Same control as 3b |
| 5. Color picker | **Settings → Renderer** (Advanced) | "Solid colour fallback" |
| 6. Matrix size | **Settings → Renderer** (Advanced) | "Logical canvas size" |
| 7. Raw Command | **Settings → Diagnostics** (Advanced) | "Send raw ctrl command" |
| 8. Mini display | **Top toolbar "Open Mini Window"** (already works) | Native to v4 — superior version |
| 9. Performance Monitor | **Home tab → Diagnostics** + standalone launcher | "Open perf monitor" |
| 10. Sprite Editor | **Editors tab** | Tile in Editors page |
| 11. Quit Node | **Settings → Diagnostics** | "Stop animation node" |
| 12. Health subscriber | **Backend service** (shared) | New `health_subscriber.py` module |
| 13. Subprocess tracking | **Already in companion** | Same pattern as the mini window |

After migration:

- **Library / Packs / Learn** stay as they are
- **Home** becomes the operator's real dashboard (was a stub)
- **Editors** absorbs the three editor launchers (sprite / bitmap / mscript)
- **Settings** gains three sub-sections: Skins (existing), Renderer (new),
  Diagnostics (new) + Advanced toggle hiding rarely-used controls
- **Top toolbar** gains a status pill on the left + Stop button next to
  the mini-window toggle

## Phased migration plan

Six commits, one per phase.  Each phase is independently shippable —
the Tk panel stays enabled until the final commit so the operator
never loses functionality mid-migration.

### Phase 1 — Backend service: shared health subscriber

Extract the `_health_poll_loop` pattern from `mochi_gui.py` into a
reusable module (`gui/mochi_health_service.py` or
`gui/_health.py`).  Returns a `HealthService` class with:

- `start()` / `stop()` lifecycle
- Latest snapshot per node (mode / size / fps / mem / tx)
- Qt `Signal` `health_updated(node_id, payload)` that pages can connect

No UI change yet.  Companion creates an instance and shares it across
pages.  Verification: log every health update so operator can confirm
data flows during testing.

**Effort:** ~1.5 hrs.  Cost-of-undoing-mistakes: very low (additive).

### Phase 2 — Top toolbar: status pill + Stop button

Top toolbar gains two elements left of the community icon row:

```
[● animation 60fps 64×64 12MB]   [Stop]   |   ▶ ♥ ◯ ?   |  [Open Mini Window]
   ↑ status pill, fed by                 ↑ deactivates the
     HealthService                          active animation
                                            (sends `mode off`)
```

Status pill colour: green when health is fresh (< 5s), grey when
stale, red on error events.  Click → opens Home → Diagnostics.

**Effort:** ~1.5 hrs.

### Phase 3 — Home page: operator dashboard

Promote the Home stub into a real surface with:

- **Hero row**: status pill writ large, current scene/pack name, mini
  window button (large)
- **Active animation card**: mode name + thumbnail + Stop button
- **Recent animations** strip: last N animations fired (from a small
  history JSON)
- **Diagnostics card**: nodes table from `HealthService` —
  cols: Node / Mode / Size / FPS / Mem / Tx + "Open perf monitor"
  button + "Stop node" per row

This is the headline new view.  Replaces the StubPage placeholder.
Where the operator lands by default after the (deferred) reaction
button row + scene wheel ship in Phase B / C of the original plan.

**Effort:** ~3 hrs.

### Phase 4 — Settings: Renderer + Diagnostics sub-sections

Settings page goes from a flat skin list to three sub-cards (matches
the Library's chip-row visual rhythm):

- **Skins** (existing) — already lists `tv1`; picker UI when > 1
- **Renderer** (new, Advanced) — gathered Tk renderer knobs:
  - Logical canvas size (W×H entry + Apply)
  - Solid colour fallback (colour picker + target combo)
  - "Reset to defaults" button
- **Diagnostics** (new, Advanced) — debug surface:
  - Raw ctrl command entry + Send
  - "Stop animation node" + "Stop LLM node" buttons (the Tk panel's
    Quit Node, scoped)
  - Recent log lines (last 50 from companion's own logger)

Both Renderer + Diagnostics live behind an **Advanced** toggle at
the top of Settings (off by default) so casual users don't see the
sharp knobs.

**Effort:** ~2.5 hrs.

### Phase 5 — Editors page: in-app launcher tiles

Editors goes from stub → grid of tiles, one per content editor.
Tile content:

- Thumbnail / icon
- Editor name
- One-line description
- Last-used timestamp
- "Open" button → spawns the editor as a subprocess (same pattern
  as the mini window)

Three tiles in v1:

- **Sprite Editor** → `tools/sprite_editor_gui.py`
- **Bitmap Editor** → `tools/bitmap_editor_gui.py`
- **MochiScript Editor** → `tools/mscript_editor_gui.py`

Plus a "Mochi Studio" tile that launches `tools/mochi_studio.py` for
the all-in-one composite editor.

Subprocess tracking + cleanup on companion close (same code path
the mini-window launcher uses today).

**Effort:** ~2 hrs.

### Phase 6 — Sunset the Tk panel

Final commit of the migration:

- `config.yaml` flips `mochi_gui.enabled: false`
- Add a `# legacy — superseded by mochi_companion (Phase 6 of
  SUPERSEDE_TK_PLAN.md)` comment
- README updated: companion is THE GUI; mochi_gui only mentioned in
  "legacy / archive" footnote
- A `tools/launch_legacy_tk.sh` one-liner kept around for emergency
  fallback (operator can still launch it manually if they need
  something the companion missed)
- File NOT deleted yet — kept in tree for one release cycle in case
  Phase 1-5 missed an edge case

Plus a small "Goodbye Tk" log entry in the companion startup so the
provenance is captured.

**Effort:** ~30 min.

## Total estimate

```
Phase 1   ~1.5 hrs   shared health service
Phase 2   ~1.5 hrs   top toolbar status pill + stop button
Phase 3   ~3.0 hrs   Home page dashboard
Phase 4   ~2.5 hrs   Settings sub-sections (Renderer + Diagnostics)
Phase 5   ~2.0 hrs   Editors tiles
Phase 6   ~0.5 hrs   sunset Tk panel
          ─────────
          ~11 hrs    six focused commits over 2-3 sessions
```

## What this migration does NOT do

- Doesn't touch the animation node, transport, agent, or anything
  outside `gui/`.  Pure operator-surface work.
- Doesn't add new product features beyond moving + improving
  existing Tk ones.  (Scene wheel, reaction row, triggers panel
  remain on the original Phase B/C roadmap.)
- Doesn't delete the Tk file — kept for one release as safety net.
- Doesn't merge `mochi-v4` to main — that's a separate operator
  decision once the migration lands.

## Verification per phase

Each phase ends with a manual run:
1. `python main.py` (Tk + companion both up)
2. Test the new companion surface (the migrated feature)
3. Test the equivalent in the Tk panel side-by-side
4. Verify both produce identical behaviour on the bus

When Phase 6 lands, `mochi_gui` is disabled in config.  Verification
becomes: every Tk feature is reachable in the companion.

## Open question for the operator

**Top toolbar real estate.**  After Phase 2 + the existing
community icons + Open Mini Window, the toolbar has:

```
[Status pill] [Stop] | YouTube Patreon Discord Help | [Open Mini]
```

That's a lot.  Plausible alternatives if it gets cramped:

A. **Keep as proposed** — five elements is roughly Wondershare's right side
B. **Move community icons to a hamburger menu** so the toolbar is just
   Status + Stop + Open Mini, and the community shortcuts hide behind ☰
C. **Move Open Mini Window into Home** — drop it from the toolbar
   since Home becomes the primary surface

My lean is **A** (keep as proposed) — Wondershare's toolbar is also
busy and it works visually.  Will reconsider mid-Phase 2 if it
feels cluttered.

## Sign-off

Operator review of this plan before Phase 1 starts.  If approved,
commits ship in the order above on `mochi-v4`.
