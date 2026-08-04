# Example — simple chatbot (mind + chat face, no voice)

**Verdict: exists ✓ as a config subset of the JaegerAI distribution —
but the taxonomy's clean "mind is a swappable MODULE" framing is
(planned), not yet built.**

Text-in, text-out, in-character, no voice modules, no hardware. This
is the case that stresses the DISTRIBUTION tier's most interesting
claim: that the mind is *itself* a MODULE (`slot: mind`) bundled inside
a distribution, the same shape as `kokoro_tts` filling `slot: tts`.

## Tiers used

DISTRIBUTION (JaegerAI, running with voice/hardware modules disabled)
+ APP (a chat face — TUI or the Swift app, either works) +, nominally,
MODULE for the mind. That last one is where the honesty is required —
see below.

## Modules required

| Module | Status | Slot | Notes |
|---|---|---|---|
| mind (agent loop, tools, persona) | **EXISTS as core code, NOT yet a discovered MODULE** | `mind` (**planned**) | Lives in `jaeger_os/agent/` + `jaeger_os/personality/` today — not behind `discover_modules()`, no `module.yaml`. The 0.9 roadmap's "mind-as-module, in-repo first" item is exactly this: extracting it into the same slot-shape as engine modules, planned before the repo split, not shipped yet. |
| `kokoro_tts` (`tts`), `whisper_stt` (`stt`) | **EXISTS ✓, disabled** | `tts`, `stt` | The "no voice modules" requirement is satisfied by simply not enabling these nodes in the manifest — the module system already supports absence cleanly (no code path assumes voice is present). |

What this means concretely: **today**, "a chatbot with no voice" is a
config fact (voice nodes' `enabled = false`), not a module-swap fact.
The distribution doesn't shrink to omit the mind's machinery because
the mind isn't separable yet — it's still fused into the same process
as everything else. The end-user-visible behavior (text chat, no
voice) is real and shippable today; the *mechanism* the taxonomy
describes (mind as a pluggable module like any other) is the gap.

## Topics

None needed beyond what's already used internally by the agent loop
and persona pipeline — this example produces no bus traffic outside
the existing `/sense/transcript`-shaped internal path (bypassed
entirely here since input is typed, not spoken). No new topics.

## Capability declarations

None — no hardware package is loaded. The capability layer
(`jaeger_os/hardware/`) never enters this example's boot path at all.

## App/workspace shape

DISTRIBUTION, not WORKSPACE — there's no body to bring up. The shape
is Jaeger-AI's own manifest pattern (`jaeger.toml` for the TUI path,
`jaeger.windowed.toml` for the Swift/windowed path), with every
voice/hardware `[[node]]` block either absent or `enabled = false`.
The chat face is APP tier: TUI is stack-embedding (same process), the
Swift app is protocol-connected (`jaeger bridge` NDJSON over stdio) —
either satisfies "a chat app face."

## Framework gaps exposed

1. **Mind-as-module doesn't exist yet.** `jaeger_os/agent/` is core
   framework-adjacent code, not something `discover_modules()` finds
   or a `module.yaml` describes. Until this lands (0.9 roadmap item 3,
   explicitly sequenced *before* the repo split), "distribution minus
   modules" is really "distribution minus config," which happens to
   look identical from the outside but has a different swap story: you
   can't point a manifest at a *different* mind implementation the way
   you can point `slot: tts` at a different TTS engine.
2. **No "suite app" template shape.** `CONVENTIONS.md` already flags
   this: the DISTRIBUTION/APP combination this example needs has no
   scaffolded starting point in this template — "start from Jaeger-AI
   itself and pin forward" is the only guidance today. A minimal
   suite-app skeleton (a `jaeger.toml`-shaped manifest with no
   hardware, no voice, just mind + one chat face) would make this
   example's "app/workspace shape" section above something you could
   actually `git clone` instead of hand-assemble.
