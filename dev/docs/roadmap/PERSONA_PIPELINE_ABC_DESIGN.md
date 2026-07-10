# Persona pipeline A / B / C — design (operator review; no implementation until OK)

> Operator idea 2026-07-10: keep today's pipeline as **A**, add experimental
> **B** (persona frontend) and **C** (clean agent as the persona's TOOL).
> Config: `persona.mode: output_filter | frontend | agent_tool` (A default).
> Reversible knob per instance; A stays default until B/C pass every gate.

## The problem being solved

The clean agent generates content persona-off; Station-3 restyles it. For
task turns that's correct (persona costs a 4B ~7 bench points in the
execution context — measured, which is why A exists). But for CREATIVE /
conversational turns the content IS the character: a restyled generic joke
is not a Lilith joke. The hardened filter (065957f) protects answers; it
cannot personalize their substance. B and C move persona from "paint at the
exit" to "the voice that answers," without touching the agentic engine.

## Mode A — output filter (today; stays default)

user → clean agent (tools, persona-off) → answer → Station-3 restyle
(content-survival guard). Known ceiling: creative content is generic.

## Mode B — persona frontend (answer-or-delegate)

user → persona model (in character, with chat context), instructed: answer
directly UNLESS the turn needs tools/facts/actions/multi-step work — then
emit a delegate marker → clean agent runs the turn exactly as today →
persona composes the final reply from the agent's result (content-survival
guard applies to the compose).
- Chat/creative turns: ONE persona call (vs A's agent+filter two) — faster.
- Task turns: one small upfront call + unchanged agent + compose.
- RISK (the reason C exists): delegation is a prose judgment by the
  weakest, most-in-character link. "what time is it" answered from vibes is
  the failure mode. The delegate rule must be aggressively conservative
  ("any fact, any action, any doubt → delegate").

## Mode C — the clean agent IS the persona's tool (operator's pick; APPROVED 2026-07-10)

**The id and the ego (operator's framing — the best explanation of this mode):**
the persona lane is the id — desire, voice, character; it wants to answer
everything itself. The clean agent is the ego — the reality principle; tool
calls are literally reality-testing. The permission tiers / e-stop / fail-
closed gates are the superego, saying no regardless of what either wants.
The safety property in one line: **the id never touches reality directly** —
Lilith cannot assert the time, she must go through the ego, which checks.
(Every hallucination is an id answering a reality question.) Same seam as
Mind-Body-Soul one level down: the Soul doesn't drive motors; the expressive
self doesn't fabricate facts.

The persona model runs as a minimal agent with exactly ONE tool:

    perform_task(request: str) -> result
    "Do real work: anything needing current information, files, devices,
     scheduling, messages, computation, or multiple steps. Pass the user's
     request (plus any needed context) verbatim."

- A turn arrives at the persona agent. Native function-calling decides:
  call `perform_task` (→ the full clean agentic loop runs the request,
  persona-off, all tools, hardened prompt) or answer in character.
- Delegation is a TOOL CALL — the mechanism local models handle best and
  the same decision shape the routing bench measures. No prose classifier.
- The persona composes the final answer from the tool result (guard applies).
- Recursion guard: the inner clean agent must never re-enter persona
  (persona.mode forced off inside `perform_task`; depth=1 hard).
- Trace UX: the inner agent's tool chips still stream to the app (the
  operator sees get_time run); the persona turn wraps them.
- Infrastructure: the aux inference lane (acb972d — one loaded model, two
  llama contexts) carries the persona context; no second model load.

## Shared design points (B and C)

- **Context:** persona lane holds the conversation history; the inner agent
  gets the current request + what the persona passes (start: verbatim user
  message; later: persona-curated context). Memory writes stay agent-side.
- **Identity:** the persona lane speaks AS identity.name with the character
  block — the "your name stays X" framing baked into its system prompt.
- **Failure modes:** persona lane error/timeout → fall through to Mode A for
  that turn (fail-open to the working pipeline, never a dead turn).
- **Security:** user input now hits the persona prompt first. The scenario
  security lane MUST run against the B/C front door; injection posture must
  match A. The inner agent keeps its hardened prompt + permission gates
  regardless (tool-tier enforcement is inside `perform_task`, unchanged).

## Gates (all three must pass before B or C can even be non-default-able)

1. **Routing bench unchanged** (drives the clean loop directly — by
   construction) + a NEW delegation eval: ~24 prompts, half chat/creative,
   half task (time, file, schedule, message, calc); C must call
   `perform_task` on 100% of task prompts (this is the make-or-break number).
2. **Scenario security lane** through the full persona-on path.
3. **Persona distinctness eval** (the operator's actual goal): fixed prompt
   set ("tell me a joke", "comfort me", "describe rain") through Lilith /
   Eren / GLaDOS / no-character; judge: distinct voices AND task delivered
   (the joke exists). A must-lose-to-B/C metric: distinctness. A
   must-not-lose metric: delivery + latency on task turns.
4. **Latency:** chat turns ≤ A (expected: better — one call vs two); task
   turns within ~10% of A.

## Rollout

Build C first (operator's pick; native mechanism, measurable delegation),
B only if C's single-tool shape proves too rigid. Knob per instance;
default A; flip an instance (jros-dev) to C for daily-driving before any
default change. Ledgered like every 0.8 experiment.

## Open questions for the operator

1. Wake-word/voice turns: should voice sessions default to C (conversation-
   heavy) or stay A until C earns it?
2. Should `perform_task` results stream through the persona (restyled live)
   or land as one composed reply after the inner turn completes? (Start:
   composed-after; streaming restyle is a later polish.)
3. Distinctness judge: local model self-judge, or operator eyeball on a
   fixed sheet first pass? (Start: eyeball sheet — cheap, honest.)
