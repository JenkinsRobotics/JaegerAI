# Outstanding work

State at `1.1.0`. This is the module's own engineering debt — what is
known-unfinished, with the measurement behind each item — not a product
roadmap. Product roadmaps and design exploration live in the application
(see [`ARCHITECTURE.md` §0](ARCHITECTURE.md#0-what-belongs-here-at-all));
this file exists because the numbers below are enforced by
`tests/test_module_boundary.py` and need somewhere to be explained.

Nothing here is broken or half-applied. Every item is scheduled work.

---

## 1. Move the product tool families to the application

**~20 tools · ~20 of the 37 remaining app imports · cross-repo**

Decided, not started. Deliberately left out of `1.1.0` so a large
two-repo change did not land on top of someone else's in-flight work.

| file | tools | app imports |
| --- | ---: | ---: |
| `tools/models.py` | 4 — list / download / locate models | 5 |
| `tools/plugins.py` | 3 — bridges, activate | 6 |
| `tools/host.py` | 7 — modes, autonomy | 4 |
| `tools/persona.py` | character traits (people already moved) | 3 |
| `tools/messaging.py` | 3 — send_message | 2 |
| `tools/diagnostics.py` | 2 | 1 |
| `tools/bench.py` | the runner shim | 3 |

These are product surface: a model downloader, plugin bridges, autonomy
policy, character traits. The application owns R&D and initiation.

**Why it is now cheap.** `1.0.7` established that a host's tools,
toolsets and skills are treated identically to the module's own
(`tests/test_host_contributions.py`). A tool moved to JaegerAI comes back
through the registry indistinguishable from one that shipped here — so
this costs the agent no capability, and exercises the host-contribution
path instead of merely trusting it.

Mochi is the reference for the shape: bind by slot, keep engine knowledge
in one named binding file, let the manifest carry policy.

---

## 2. The `main` / `_pipeline` host-adapter seam

**8 imports · single-repo, then a JaegerAI follow-up**

`jaeger_ai.main` is imported for `_pipeline`, `_get_agent`,
`_fast_finalize_sync`, `voice_warm_status`. All of it collapses to one
question — *give me the live agent, its layout, and its system prompt* —
which is a host adapter, not app logic.

Doing this also frees `tools/bench.py`, which currently imports
`jaeger_ai.core.bench` for the runner. The **corpus** already lives here
(`jaeger_agent/bench/`, 81 cases); only the runner is upstream. Once the
seam exists, the agent can run the corpus that measures it.

---

## 3. STT: `listen.py` never took the bus rewire

**Architectural, not a rename**

`tools/listen.py` loads `pywhispercpp` **in-process** rather than going
through the `stt` slot's node, and imports `jaeger_ai.main` for
`voice_warm_status`. The TTS path took the 0.4 rewire — `speak()`
publishes `SpeechCommand` and waits for `SpokenAck` — and hearing never
did.

Compare `tools/speak.py` after `1.0.2` for the target shape. Note this is
a real behaviour change, not a cleanup: it moves synthesis of transcripts
out of the agent process.

---

## 4. Reduce the remaining app imports

**37 across 20 files. Ratchet: `tests/test_module_boundary.py`**

The ratchet fails when the count rises **and** when it falls — progress
must edit the budget, or a stale number hides the next regression.

Already inverted, as worked examples:

| what | how | version |
| --- | --- | --- |
| usage telemetry | `usage.set_sink(...)`, host registers | `1.0.3` |
| person index | the agent's own facts store | `1.0.5` |
| instance shapes | `instance.Layout` Protocol, structural | `1.0.6` |

Remaining clusters after items 1–3: `instance.schemas` stragglers,
`core/trace.py`, `bus_confirm.py`.

---

## 5. Known-failing bench case: `skill_arxiv`

**Model judgment, not a module defect — do not "fix" it in the module**

Investigated at `1.1.0`. The mechanism is intact: `arxiv` is
discoverable, `use_skill(name="arxiv")` loads it, its `requires_tools`
are registered, and all 107 skills are in the enum on the `use_skill`
schema. The E4B can see the skill and chooses `web_search` anyway —
identically in the 2026-08-05 run, so it is stable, not a regression.

Improving it means prompt and routing tuning, which is app-side R&D. If
someone does chase it, the lever is skill-selection prominence, not the
skill registry.

---

## 6. Smaller items

- **17 skills declare `requires_tools` a bare install lacks** —
  `computer_*`, `generate_image_fal`, `ha_*`, `send_message`,
  `delegate_task`. All host-provided, so this cannot fail. It matters
  because `use_skill` *warns* the model when a skill's tools are missing,
  and a skill that always warns is one the model always avoids. Surfaced
  by `python3 -m jaeger_agent selfcheck`.
- **`duckduckgo_search`** is the only import the self-check still lists
  besides `jaeger_ai`. It is the legacy backend behind `ddgs`; drop it
  when the fallback chain no longer needs it.
- **Moved docs cite pre-extraction paths** (`agent/loop/...`,
  `jaeger_os/main.py`). Flagged at the top of `ARCHITECTURE.md` rather
  than rewriting nineteen files. Fix opportunistically.

---

## Verifying before and after any of the above

```bash
python3 -m jaeger_agent selfcheck      # 19 checks, no model, under a second
python3 -m pytest -q                   # 418
ruff check <changed files>             # CI lints changed files only
```

The self-check is the cheap gate — it catches a schema that will not
serialise, a toolset naming a tool nothing provides, a skill offered but
unloadable, a declared dependency that does not import. That last one
found `croniter` in one second, after a benchmark had found it the
expensive way.

The bench answers the different question — *does the model route well?* —
and needs a live model and an instance. Corpus here, runner in JaegerAI.
