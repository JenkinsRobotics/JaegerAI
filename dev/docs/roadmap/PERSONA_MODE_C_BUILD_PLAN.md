# Persona Mode C (agent_tool — "the id and the ego") — build plan

> Operator-approved (design: PERSONA_PIPELINE_ABC_DESIGN.md). Framing is
> canonical: id = persona lane · ego = clean agent (the id's ONE tool) ·
> superego = permission/e-stop gates. The id never touches reality directly.

**Verified seams (Mode-C recon):** ONE chokepoint — `_apply_persona_filter`'s
sole call site is main.py:2273 inside `_run_turn_via_jaeger_agent`
(main.py:2207); ALL surfaces (TUI, bridge/Swift via run_for_voice, voice_loop,
messaging_gateway) funnel through it; bench + `delegate_task` call
`drive_one_turn` directly (main.py:1104-1130) and bypass it — bench untouched
by construction. Aux lane: `client.chat()` (main.py:2673) runs on the aux
context (`_aux_lane` :2652, spawn 0.08s, `model.aux_ctx` default 4096),
ALREADY accepts `tools=` with `tool_choice="auto"` (:2710-2712); only gap =
`_ChatResult` doesn't expose `choices[0].message.tool_calls` (:2721).
Schema render: `ToolSpec.to_openai_schema()` (tool_schema.py:141). Text-dialect
fallback parser: `extract_tool_calls` (agent/dialects/__init__.py:66). Session
history: `_jaeger_agents_by_session[key].messages` — filter to user/assistant
pairs. Config: `PersonaConfig` schemas.py:683 (`extra="forbid"`), catalog via
`_setting("persona")`. Aux-vs-worker contexts run concurrently (separate
locks); aux-vs-aux serialized on `_aux_lock`.

---

### Task 1 — the id/ego lane

1. **Config:** `PersonaConfig.mode: Literal["output_filter","agent_tool"] =
   "output_filter"` (+ `_setting("persona")`; do NOT add "frontend" until
   built — no spec ahead of code). Env kill switch stays (`JAEGER_PERSONA_FILTER=0`
   forces output_filter... decide: a mode env `JAEGER_PERSONA_MODE` overriding
   config is cleaner for A/B — add it, document both).
2. **`chat()` exposes tool calls:** `_ChatResult` gains `tool_calls`
   (the raw `choices[0].message.tool_calls` list or []); main.py:2721 region.
3. **New module `jaeger_os/agent/prompts/persona_lane.py`** (beside
   persona_filter.py; docstring = the id/ego/superego framing, verbatim spirit
   from the design doc):
   - `PERFORM_TASK_SPEC`: one tool, `perform_task(request: str)` — description
     per the design ("Do real work: anything needing current information,
     files, devices, scheduling, messages, computation, or multiple steps.").
   - `run_persona_turn(client, user_text, *, character_block, agent_name,
     history, perform_task) -> str | None`:
     a. system = identity framing ("Your name is {agent_name}…" — reuse the
        exact framing text from main.py:1926-1931) + character block + a short
        lane contract ("You have ONE tool… any fact, action, or doubt → use it;
        otherwise answer as yourself, briefly, in character").
     b. history = last ~6 user/assistant pairs (truncate to fit aux_ctx).
     c. First aux call with `tools=[PERFORM_TASK…openai schema]`. Tool call
        detected natively OR via `extract_tool_calls` on the text (fallback).
     d. Tool-free → return the text (the id answered; no guard — nothing to
        preserve). Tool call → `raw = perform_task(request)`; second aux call
        (no tools) composing the reply from `raw`; apply the CONTENT-SURVIVAL
        GUARD (persona_filter's overlap check — import/share it) comparing
        compose vs `raw`; guard-fail → return `raw` unstyled.
     e. Return None on any error/empty (caller falls back).
4. **The branch** in `_run_turn_via_jaeger_agent`, before `drive_one_turn`
   (main.py:2238): mode==agent_tool AND a character is active → build
   `perform_task = lambda request: <the existing drive_one_turn body for this
   session's jaeger_agent, returning the raw answer>` (inner tool chips still
   stream via the existing event path — verify). `run_persona_turn(...)`;
   None → fall through to today's `drive_one_turn` + Mode-A filter path
   (fail-open, never a dead turn). CRITICAL: if `perform_task` already ran and
   only the compose failed, do NOT run the turn twice — the guard's raw-return
   handles it inside run_persona_turn.
   Recursion structurally impossible (perform_task calls drive_one_turn, not
   _run_turn_via_jaeger_agent) — assert with a test anyway.
5. **Tests (fake client, canned responses):** tool-free turn → in-character
   text, zero inner turns; tool-call turn → perform_task called once with the
   request, composed reply returned; compose-mangles → raw returned;
   lane-error → None → Mode-A fallback executed; mode=output_filter →
   byte-identical behavior to today (regression pin); config default is
   output_filter; JAEGER_PERSONA_MODE override works.

### Task 2 — the gates (real model)

1. **Delegation eval** `dev/benchmark/persona_eval.py`: 24 fixed prompts —
   12 task (time, weather-file, schedule, send-message, calc, file-read,
   search, device…), 12 chat/creative (joke, comfort, opinion, describe rain,
   self-reflection, roleplay…). Runs headless via `run_command` on a temp
   instance with mode=agent_tool + a character. **GATE: 12/12 task prompts
   delegate (perform_task called).** Report (not hard-gate) chat-side
   over-delegation rate (target ≤3/12) + per-turn latency A vs C on both
   halves.
2. **Distinctness sheet:** the 12 chat prompts through lilith / eren_yeager /
   glados + no-character → `dev/benchmark/results/persona_distinctness_<date>.md`
   for operator eyeball.
3. **Routing bench** (expect unchanged — mode is config-default off and the
   bench bypasses the seam; run once to confirm 79-81).
4. **Security lane note:** scenarios run the temp instance at default mode (A).
   Add a `--persona-mode` override to scenarios.py ONLY if cheap; else ledger
   "security lane vs Mode C" as a required pre-default-flip gate, since C is
   experimental/per-instance for now.

### Gates summary
Suites green · delegation 12/12 · bench 79-81 unchanged · distinctness sheet
delivered · latency reported · ledger. Mode stays default-off (output_filter);
jros-dev flips to agent_tool for daily driving after the operator eyeballs
the sheet. NO push.
