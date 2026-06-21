# Final value review: VoiceLLM + Hermes

**Date:** 2026-06-06 (post-0.4.0)
**Purpose:** identify any unabsorbed value before the operator
closes these reference repos.

JROS 0.4.0 has shipped — Tracks A + B + C-skeleton landed, voice
mode is fully node-shaped, the agent's tool surface routes
through the bus.  Before the operator archives VoiceLLM and
Hermes, this review answers one question per repo:

> "Is there anything in here we haven't already absorbed that
> we'd lose if the repo went away?"

The honest answer for both: **almost no — JROS has surpassed
them.**  Three small things from VoiceLLM are worth keeping a
mental note of for 0.4.x; one file from Hermes is worth keeping
as a reference for Track D.  Everything else is superseded.

---

## VoiceLLM

### Already absorbed (no action needed)

| VoiceLLM module | Where it lives in JROS |
|---|---|
| `core/bus.py` (queue.Queue Bus) | `jaeger_os/transport/inproc_bus.py` (Track A.3) |
| `<ignore>` / `<reply>` LLM-gated speech | `jaeger_os/core/voice/llm_gate.py` (B.3 commit `ee8bb9b`) |
| Wake word + follow-up window | `jaeger_os/plugins/whisper_stt/continuous.py` |
| Self-speech filter (AEC + reference buffer) | `jaeger_os/core/audio/` (speexdsp) |
| Mic-pause during TTS | `WhisperSTTContinuous.set_paused` |
| Chimes (wake + follow-up earcons) | `jaeger_os/core/audio/ChimePlayer` |
| Per-subsystem plugin layout (stt/, tts/, audio/) | `jaeger_os/nodes/{tts,stt,vision,motor,light}/` |

### Unabsorbed but worth noting (0.4.x consideration only)

1. **MLX-LM backend** (`plugins/mlx_llm/backend.py`).  JROS uses
   `llama-cpp-python` for Gemma; MLX is Apple Silicon native and
   typically 1.5–2× faster on M-series.  This was on the
   roadmap's library-review wishlist; still a worthwhile 0.4.x
   perf upgrade if Gemma decode latency becomes a bottleneck.
   **Risk if VoiceLLM goes away**: low — the reference
   implementation is ~50 lines and the upstream `mlx-lm` package
   is the actual source.

2. **WebRTC VAD segmenter** (`audio/vad.py`).  JROS's STT uses
   Whisper's own energy gate (`energy_threshold` in
   `WhisperSTTContinuous`).  WebRTC VAD is Google's
   production-grade voice-activity detector; could be a quality
   upgrade for the STT segmentation step if energy-gating
   produces too many false positives in noisy environments.
   **Risk if VoiceLLM goes away**: zero — `webrtcvad` is a
   PyPI package with public docs.

3. **Explicit orchestrator FSM**
   (`core/runners/orchestrator.py`).  The IDLE → THINKING →
   RESPONDING → IDLE state machine that JROS's voice_loop
   already follows IMPLICITLY through scattered booleans.
   Promoting to an explicit FSM would make the voice loop
   more testable + introspectable.  Worth keeping in mind if
   barge-in or mid-turn cancellation grows new edge cases.
   **Risk if VoiceLLM goes away**: low — pattern is 100 lines,
   easy to re-derive.

### Operator's M3 metrics

`metrics.csv` has the operator's actual end-to-end timing runs
on the M3 hardware (wake→listen→stt→tts).  Useful historical
baseline for "what does this stack feel like on Apple Silicon",
NOT code to absorb.  If you want to preserve the numbers for
future comparison, copy `metrics.csv` somewhere outside the
VoiceLLM tree before deletion.

### Verdict — VoiceLLM

**Safe to close.**  JROS has surpassed it:
- Production-grade voice pipeline (persistent Kokoro player,
  dual sounddevice/avaudio backends, deterministic teardown)
- Full LLM agent capabilities (tools, memory, skills, persona)
- Skill system v3 with capability scoring
- Bench infrastructure
- Multi-instance support

The three "noted" items above are tracked in the
`dev/docs/library_review/voicellm.md` library review and the
0.4 roadmap as future-perf / future-quality candidates; the
PATTERNS are documented, the IMPLEMENTATIONS are not load-bearing
on VoiceLLM continuing to exist.

---

## Hermes

### Already absorbed or superseded

| Hermes file | JROS equivalent |
|---|---|
| `model_resolver.py` | `jaeger_os/core/instance/model_resolver.py` (more sophisticated; tier-aware; sleep-cycle support) |
| `main.py` framework dispatcher | n/a — JROS is the framework now |
| `python_hermes_agent/` (XML/JSON format experiments) | n/a — JROS uses its own tool-call format via `jaeger_os/agent/schemas/` |

### Worth preserving (Track D candidate)

1. **`supervisor.py`** — restart-on-crash supervisor with
   exponential backoff (doubles per crash, caps at 60s, resets
   after a good run).  Crash details appended to a structured
   log.  Designed for `python supervisor.py -- python main.py`
   wrapping.

   This is **exactly the pattern Track D needs** for the
   per-node supervisor.  Worth porting verbatim (with light
   adaptation for our Node base class) when Track D lands.

   **Action:** copy a frozen reference of supervisor.py to
   `dev/docs/library_review/hermes_supervisor.py` BEFORE
   deletion so we have the canonical reference for the Track D
   work.

2. **`agent_doctor.py`** — pre-flight diagnostic that exits 0
   iff every check passes; designed so a systemd unit can gate
   startup on its exit code.  JROS has `./launch --health` which
   does similar checks but agent_doctor's structure (rigorous
   exit-code gating, JSON output mode, designed for unattended
   robot startup) is more complete.

   **Action:** when JROS gains an unattended-robot mode (Track
   D / Track E), study agent_doctor.py's check structure as the
   reference for `./launch --health --strict`.

### Verdict — Hermes

**Safe to close** once `supervisor.py` is copied to
`dev/docs/library_review/`.  Everything else is either
superseded by JROS or framework-experimentation work that
served its purpose (proving the tool-call format space).

Hermes's most lasting contribution to JROS is already absorbed:
the clone-and-venv install pattern that `./run.sh setup` follows
came from Hermes's design.

---

## Operator action checklist

Before deleting VoiceLLM:
- [ ] (Optional) Copy `metrics.csv` somewhere outside VoiceLLM
      if the M3 latency baselines are worth preserving.
- [ ] No code copying needed — the three "noted" items are
      patterns, not load-bearing implementations.

Before deleting Hermes:
- [ ] Copy `supervisor.py` to
      `dev/docs/library_review/hermes_supervisor.py` for Track D.
- [ ] No other code copying needed.

After both deletions, JROS has every pattern these repos
contributed — no information loss.
