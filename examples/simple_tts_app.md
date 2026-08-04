# Example — simple TTS app (kokoro standalone)

**Verdict: all exists ✓ — the trivial case, proving the floor.**

The smallest thing that is still "an app" in this ecosystem: speak text
out loud, nothing else. No agent, no bus of sensors, no body. This
example exists to prove the floor has zero framework gaps before the
harder examples start finding them.

## Tiers used

MODULE only. No WORKSPACE, no APP, no DISTRIBUTION are *required* —
`kokoro_tts` ships its own standalone CLI, which is the module's own
"face" (`CONVENTIONS.md`'s module-repo shape: "every module runs by
itself — no agent, no app").

## Modules required

| Module | Status | Slot | Notes |
|---|---|---|---|
| `kokoro_tts` | **EXISTS ✓** | `tts` | `jaeger_kokoro_tts/nodes/kokoro_tts/module.yaml`, real shipped module |

No other module is needed. `kokoro_tts`'s `module.yaml` (verbatim from
the shipped repo):

```yaml
module: kokoro_tts
slot: tts
version: 1.0.0
consumes: [/act/speech, /act/speech_stop]
produces: [/sense/spoken, /sense/tts_chunk]
tools: [text_to_speech]
factory: jaeger_kokoro_tts.nodes.kokoro_tts:make_tts_node
config: kokoro_tts
requires_libraries: [kokoro, sounddevice, numpy]
```

## Topics

All existing, none new:

- `/act/speech` (in) — text + voice + rate
- `/act/speech_stop` (in) — barge-in / interrupt
- `/sense/spoken` (out) — done-ack, correlation-ID matched
- `/sense/tts_chunk` (out) — per-chunk amplitude, drives lip-sync elsewhere (unused here)

## Capability declarations

None. TTS is a software module, not a body — there is no
`topology.yaml`, no controller, no permission tier. This is the
cleanest illustration that MODULE tier and PACKAGE/WORKSPACE tier are
genuinely independent: a module needs zero hardware-capability
machinery to be complete.

## App/workspace shape

Two equally valid shapes, both zero-gap:

1. **Bare module CLI** — no workspace at all.
   ```bash
   pip install jaeger-kokoro-tts
   python -m jaeger_kokoro_tts --smoke
   ```
   (Mirrors this template's own `{{package_name}}/__main__.py.example`
   standalone-use convention.)

2. **5-line workspace binding `slot: tts`** — if this needs to run
   *inside* a JaegerOS instance (e.g. as part of a larger manifest
   later), the entire workspace-side binding is:
   ```toml
   [[node]]
   id = "tts"
   tier = 3
   backend = "thread"
   slot = "tts"
   config_key = "kokoro_tts"
   enabled = true
   ```
   No `topology.yaml` needed — there's no controller, no physical
   body, nothing to declare a capability against. `unit.yaml` and
   `SAFETY_CHECKLIST.md` don't apply either; both are body-tier
   concerns.

## Framework gaps exposed

None load-bearing. One cosmetic friction, not a contract gap: this
template's `workspace/` scaffold (`topology.yaml.example`,
`unit.yaml.example`) is written assuming a physical/simulated body
exists, so a software-only binding like this one has to skip most of
the scaffolded files rather than fill them in. Not worth a framework
change — the 5-line `manifest.toml` snippet above is already the
complete answer — but worth naming so a future contributor doesn't go
looking for a "software-only workspace" variant that doesn't need to
exist.
