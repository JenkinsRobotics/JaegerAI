# Library review — `VoiceLLM`

**Source:** `/Users/jonathanjenkins/GITHUB/VoiceLLM`
**Maintainer:** operator (Jenkins Robotics)
**Status:** "milestone complete" — explicitly being handed off; ideas
migrate to JROS
**Reviewed:** 2026-06-06 for 0.4 roadmap inputs

---

## What it is

VoiceLLM is the **predecessor** to JROS's agentic-AI work — a
continuously-listening local voice assistant on Apple Silicon.  Same
stack JROS uses today (Gemma 4 26B-A4B, Whisper two-pass, Kokoro,
sounddevice) and the operator built it as the "voice loop" testbed
before pivoting to JROS for the broader agentic + embodied story.

Their own README confirms the migration path:

> *"This project is complete for the current local voice assistant
> milestone… Carry-forward ideas: True full-duplex AEC/barge-in;
> Persistent memory beyond in-session conversation history; LLM-
> callable tools or skills."*

JROS already has all three.  VoiceLLM is the rear-view mirror.

## Architecture in one diagram

```
       ┌──────────────────────────────────────────────────────┐
       │                    Single process                     │
       │                                                       │
       │   ┌────────────┐    Bus (queue.Queue)   ┌──────────┐ │
       │   │ STT node   │ ─publish─▶ topic ─sub▶ │ Orches-  │ │
       │   │ (Whisper)  │                        │ trator   │ │
       │   └────────────┘                        │ FSM      │ │
       │   ┌────────────┐                        │ IDLE →   │ │
       │   │ LLM node   │ ◀──────── topic ─────  │ THINKING │ │
       │   │ (Gemma)    │                        │ → REPLY  │ │
       │   └────────────┘                        │ → IDLE   │ │
       │   ┌────────────┐                        └──────────┘ │
       │   │ TTS node   │ ◀──────── topic ─────────┘          │
       │   │ (Kokoro)   │                                      │
       │   └────────────┘                                      │
       └──────────────────────────────────────────────────────┘
```

**Critically:** all nodes run in the same Python process; the "Bus"
is a `queue.Queue(maxsize=2048)`.  This is the **node concept without
the IPC cost** — the simplest possible pub/sub.

## Patterns to absorb into JROS 0.4 (the gold)

### 1. The simplest possible Bus is also the right Bus for monolithic mode

Look at `core/bus.py` in its entirety:

```python
import queue
from dataclasses import dataclass
from typing import Any

@dataclass
class Message:
    topic: str
    payload: Any

class Bus:
    def __init__(self):
        self.q = queue.Queue(maxsize=2048)
    def publish(self, topic, payload):
        self.q.put(Message(topic, payload))
    def get(self, timeout=0.1):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None
```

That's **the entire bus**.  No external library, no shared memory, no
serialization, no IPC.  Just a typed queue with topic labels.

**0.4 Track A should adopt this verbatim as the in-process default.**
The ZMQ transport only kicks in when `--multiprocess` is set.  Both
expose the same `publish` / subscribe API at the Node base class
level so a node doesn't know which transport it's using.

This validates the 0.4 plan: `inproc` is a degenerate transport, NOT
a fundamentally different architecture.  VoiceLLM proves it scales
to a full voice loop with TTS, STT, LLM.

### 2. The LLM-gated speech pattern (`<ignore>` / `<reply>`)

From the README:

> *"Every reply begins with `<ignore>` or `<reply>`; the orchestrator
> suppresses TTS when the LLM judges the input as not addressed to it
> (background TV, keystroke noise, transcription artifacts, ambient
> conversation).  The audio pipeline does not gatekeep — the LLM does."*

This is **genuinely clever** and JROS doesn't have it.  For an
always-on robot listening to an open room, the LLM-as-gate beats:

  - Wake-word matching (false negatives + brittle phonetic mismatch)
  - Mic VAD (false positives on TV / music)
  - Per-utterance human approval (defeats the always-on point)

Each reply token starts with a one-token classification (`<ignore>`
vs `<reply>`).  Tiny inference cost — the LLM has to produce ONE
token before the orchestrator decides whether to fire TTS.  Wrong
classifications are recoverable next turn.

**0.4 should add this as a config flag:** `voice.llm_gate: true`.
The system prompt grows a "reply with `<ignore>` if the input isn't
addressed to you" rule.  Sits cleanly alongside JROS's existing
`is_non_speech_marker()` STT filter (step 6); the LLM-gate is the
second line of defence after the STT-level filter.

> **⚠️ ADDED in 0.4, REMOVED in 0.5.0 (2026-06-16).** This
> recommendation was wrong *for JROS specifically*.  It "sits cleanly"
> in VoiceLLM because VoiceLLM has **no tools** — its LLM only ever
> produces a spoken reply, so a `<reply>`/`<ignore>` prefix is the
> whole job.  JROS's brain is an agentic tool-caller; putting the gate
> in its system prompt made one model do two conflicting jobs, and the
> "default to ignore / just reply" framing suppressed tool routing
> (gemma-4-26B-A4B: 0/3 tool prompts gated on, 3/3 off).  Ambient
> filtering belongs in the voice INPUT layer (VAD + wake word), never
> the brain.  The gate pattern is right for a tool-less voice assistant
> and wrong for an agent.

### 3. The orchestrator FSM (`IDLE → THINKING → RESPONDING → IDLE`)

`core/runners/orchestrator.py` runs a deterministic state machine
driven by bus events.  Each state has clear entry/exit invariants:

  - `IDLE`: mic listening, no LLM call in flight, no TTS active
  - `THINKING`: LLM call in flight, mic still capturing for barge-in
  - `RESPONDING`: TTS streaming, mic paused or AEC-filtered
  - back to IDLE

**JROS's current voice loop is implicit** — the state lives in
scattered booleans (`self._tts_active`, `mic.paused`, etc.).  An
explicit FSM in `jaeger_os/nodes/orchestrator.py` would make the
voice-loop behaviour testable + introspectable.  This is a 0.4
Track A nice-to-have — promote to must-have if barge-in keeps
introducing race bugs.

### 4. Two interchangeable LLM backends as a config flag

VoiceLLM ships **both** `llama.cpp` and `mlx-lm` Gemma backends with
ONE config flag (`LLM_BACKEND = "llamacpp"` vs `"mlx"`).  The mlx
path is faster on M-series.

JROS today is llama-cpp-only.  Adding the mlx backend as an opt-in is
2-3 days of work + would close the perf gap with closed-source
assistants on Apple Silicon.  Reserve as a 0.4.x deliverable; not
critical for 0.4.0.

### 5. Plugin-per-subsystem layout

`plugins/` in VoiceLLM is:

```
kokoro_tts/
llama_cpp_llm/
llm_core/
mlx_llm/
whisper_stt/
```

Exactly the shape JROS already has (`jaeger_os/plugins/`).  No
absorption needed — JROS converged on the same layout independently.
Worth noting for the operator: this is the right structure, both
projects independently picked it.

## Patterns we should NOT inherit

  - **The single-process-only Bus.**  Adopt the in-process Bus pattern
    for the monolithic default, but layer a ZMQ pub/sub on top of the
    same API so multi-process / multi-machine works.  VoiceLLM
    explicitly punts on multi-machine — JROS can't.
  - **Mic pause + similarity filtering for self-speech rejection.**
    JROS's path is full-duplex AEC (`_MicStream`'s optional aec +
    far_end_buffer plumbing from step 6).  Mic-pause works for a
    desktop assistant but breaks the moment the robot has to listen
    while it speaks (interruption awareness, conversational hand-off).
  - **No persistent memory.**  VoiceLLM keeps only in-session history;
    JROS has full `remember`/`recall`/`forget`/`list_facts` over a
    SQLite store.  Confirmed working in this branch's agent test.

## How VoiceLLM informs Track A (0.4.0 node foundation)

Concrete imports for 0.4 Track A:

  1. **Copy `core/bus.py` verbatim** to `jaeger_os/transport/inproc_bus.py`
     (~30 lines).  This becomes the default transport.
  2. **Use VoiceLLM's plugin/node init pattern** (the `make_stt(bus)`,
     `make_backend()` factories in `main.py`) as the model for
     `jaeger_os/nodes/launch.py`'s node construction.
  3. **Adopt the orchestrator FSM** structure for the voice-loop
     coordinator node, even if its scope is narrower than VoiceLLM's
     (no TTS gate; JROS has the full agent loop instead).

These three are pure copy-and-adapt — no architectural rework — and
land VoiceLLM's hard-won concrete patterns in JROS without dragging
its single-process limitations.
