"""Persona Mode C — the id and the ego.

Design: dev/docs/roadmap/PERSONA_PIPELINE_ABC_DESIGN.md (Mode C section);
build plan: dev/docs/roadmap/PERSONA_MODE_C_BUILD_PLAN.md. Operator-
canonized framing, 2026-07-10:

The persona lane IS the id — desire, voice, character. It wants to answer
everything itself, in character, right now. The clean agent (driven here
through exactly ONE tool, ``perform_task``) is the ego: the reality
principle. A tool call is literally reality-testing. The permission tiers,
e-stop, and fail-closed gates elsewhere in the loop are the superego,
saying no regardless of what either the id or the ego wants. One property
makes this mode safe to ship: **the id never touches reality directly.**
Lilith cannot assert the time — she must go through the ego, which checks.
Every hallucination is an id answering a reality question it should have
delegated instead.

``run_persona_turn`` is the whole mechanism: native function-calling
decides — call ``perform_task`` (the full clean agentic loop: persona-off,
every tool, the hardened prompt) or answer as the character. Delegation is
a TOOL CALL, not a prose classifier — the same decision shape the routing
bench measures, and the mechanism local models handle best. When it
delegates, the id composes the final reply from the tool's raw result,
guarded by the SAME content-survival check Station 3 (``persona_filter.
py``) uses for its restyle pass — imported, not duplicated, so "restyled"
never means "replaced."

Recursion is structurally impossible here, not merely policed: the
``perform_task`` closure (built by the caller, main.py's
``_run_persona_lane_turn``) calls ``drive_one_turn`` directly — never back
through this module, never through the turn dispatcher — so there is no
code path for the ego to re-enter the id.

**Contract callers rely on:** ``run_persona_turn`` returns ``None`` only
for a failure that happens BEFORE ``perform_task`` is invoked (aux call
error, no decision, empty answer) — that is the caller's fail-open signal
to fall through to Mode A untouched, and it also means the turn has not
run yet. Once ``perform_task`` HAS been called, this function is
guaranteed to return a string, never ``None``: a failed or content-
gutting compose pass returns the tool's raw, unstyled answer instead of
silently discarding it — the turn must never run twice.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from jaeger_os.agent.dialects import extract_tool_calls
from jaeger_os.agent.prompts.persona_filter import _preserves_content
from jaeger_os.agent.schemas.tool_schema import ToolDef


class _PerformTaskArgs(BaseModel):
    request: str = Field(
        ..., description="The user's request, verbatim, plus any needed context."
    )


def _unused_dispatch(request: str) -> str:
    """Placeholder ``fn`` for :data:`PERFORM_TASK_SPEC`. Never actually
    called — the lane intercepts ``perform_task`` calls itself (see
    :func:`_decide` / :func:`run_persona_turn`) and drives the real
    session's ``drive_one_turn`` through the ``perform_task`` closure the
    caller supplies. A ``ToolDef`` needs a ``fn`` to exist; this one only
    has to exist, never run."""
    return request


PERFORM_TASK_SPEC = ToolDef(
    name="perform_task",
    description=(
        "Do real work: anything needing current information, files, "
        "devices, scheduling, messages, computation, or multiple steps. "
        "Pass the user's request (plus any needed context) verbatim."
    ),
    args_model=_PerformTaskArgs,
    fn=_unused_dispatch,
)

# The lane's own system-prompt addendum, appended after the identity +
# character block. Deliberately blunt ("any doubt -> use it"): the whole
# safety property of Mode C rests on the id under-trusting itself, and a
# soft instruction here is exactly the failure mode the design doc calls
# out ("what time is it" answered from vibes).
LANE_CONTRACT = (
    "You have ONE tool: perform_task. Any fact, any action, any device, "
    "any file, any schedule, any message, any computation, or any doubt "
    "at all -> call perform_task with the user's request. You are not the "
    "one who touches reality; that tool is. Otherwise — a genuine chat, "
    "opinion, joke, or creative turn with nothing to check — answer as "
    "yourself, briefly, in character."
)

# Compose-pass instruction: turn the tool's raw (persona-off) answer into
# the id's own voice without touching its substance. Mirrors persona_
# filter.py's _STYLE_RULES; kept separate because the compose pass also
# needs to phrase around "I delegated this" without ever saying so.
COMPOSE_RULES = (
    "Reply to the user using the result below, in YOUR voice. Preserve "
    "every fact, number, unit, name, file path, URL, and code snippet "
    "VERBATIM — change only tone and phrasing. Keep every piece of "
    "information from the result; dropping content is failure. Never "
    "mention a tool, a delegation, or 'perform_task' — just answer as "
    "yourself. Plain terminal text: no markdown emphasis.\n\n"
    "RESULT:\n"
)

# History budget (design: "last ~6 user/assistant pairs, char-budget them
# — aux_ctx 4096; the persona system prompt + character block already eat
# some"). aux_ctx defaults to 4096 tokens (~16K chars at a rough 4
# chars/token estimate); the system prompt (identity framing + full
# character block + LANE_CONTRACT) plus the perform_task tool schema plus
# the response budget can easily be several thousand chars on a richly
# written character, so history gets a deliberately small, fixed slice —
# a long conversation degrades gracefully (older turns drop) instead of
# ever overflowing the aux context and erroring the turn.
MAX_HISTORY_PAIRS = 6
MAX_HISTORY_CHARS = 3200


def _budget_history(
    history: list[dict[str, Any]],
    *,
    max_pairs: int = MAX_HISTORY_PAIRS,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[dict[str, Any]]:
    """User/assistant turns with real text content only (tool calls and
    tool results are the clean agent's business, never the id's), the
    last ``max_pairs`` pairs, then the oldest of those dropped until the
    total fits ``max_chars``. Order preserved (oldest first)."""
    turns = [
        {"role": m.get("role"), "content": (m.get("content") or "").strip()}
        for m in history
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    turns = turns[-(max_pairs * 2):]
    total = sum(len(t["content"]) for t in turns)
    while turns and total > max_chars:
        dropped = turns.pop(0)
        total -= len(dropped["content"])
    return turns


def _decide(result: Any) -> dict[str, Any] | None:
    """Extract ``perform_task``'s arguments from an aux ``chat()`` result.

    Native ``tool_calls`` first — the structured path llama-cpp's handler
    fills for tools-aware families (Gemma among them, per the recon: the
    aux lane already sends ``tools=``/``tool_choice='auto'``). The text-
    dialect drift parser (:func:`extract_tool_calls`) second, for models
    that emit the call as text instead. Returns ``None`` when neither
    surfaces a ``perform_task`` call — the id answered directly."""
    for tc in (getattr(result, "tool_calls", None) or []):
        fn = (tc or {}).get("function") or {}
        if fn.get("name") != PERFORM_TASK_SPEC.name:
            continue
        raw_args = fn.get("arguments")
        if isinstance(raw_args, str):
            try:
                return json.loads(raw_args) if raw_args.strip() else {}
            except (TypeError, ValueError):
                return {}
        if isinstance(raw_args, dict):
            return raw_args
        return {}
    for call in extract_tool_calls(getattr(result, "text", "") or ""):
        if call.get("name") == PERFORM_TASK_SPEC.name:
            return call.get("arguments") or {}
    return None


def run_persona_turn(
    client: Any,
    user_text: str,
    *,
    character_block: str,
    agent_name: str,
    history: list[dict[str, Any]],
    perform_task: Callable[[str], str],
) -> str | None:
    """Drive one Mode-C turn on the aux lane. See the module docstring for
    the id/ego framing and the None-only-before-delegation contract.

    ``character_block`` is the FULL identity+persona system text (the
    caller builds it — main.py's ``_persona_identity_block``, shared with
    Station 3 so both voices introduce themselves identically).
    ``agent_name`` is accepted for parity with that shared builder's
    signature and logging; the identity framing is already baked into
    ``character_block`` by the time it reaches here.
    """
    text = (user_text or "").strip()
    block = (character_block or "").strip()
    if not text or not block:
        return None

    system = block + "\n\n" + LANE_CONTRACT
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(
        {"role": t["role"], "content": t["content"]}
        for t in _budget_history(history)
    )
    messages.append({"role": "user", "content": text})

    try:
        first = client.chat(
            messages,
            tools=[PERFORM_TASK_SPEC.to_openai_schema()],
            max_tokens=400,
            temperature=0.4,
            top_p=0.9,
        )
    except Exception:  # noqa: BLE001 — the id is optional, the turn is not
        return None

    args = _decide(first)
    if args is None:
        # Tool-free: the id answered itself. No content-survival guard —
        # there is nothing upstream to preserve; this text IS the answer.
        answer = (getattr(first, "text", None) or "").strip()
        return answer or None

    request = str(args.get("request") or "").strip() or text
    # From here on the turn HAS run — every path below returns a string,
    # never None (see the module docstring's contract).
    raw = str(perform_task(request) or "").strip()

    compose_text = ""
    try:
        composed = client.chat(
            [
                {"role": "system", "content": block},
                {"role": "user", "content": COMPOSE_RULES + raw},
            ],
            max_tokens=min(600, max(120, len(raw) // 2)),
            temperature=0.3,
            top_p=0.9,
        )
        compose_text = (getattr(composed, "text", None) or "").strip()
    except Exception:  # noqa: BLE001 — compose is optional, the answer is not
        compose_text = ""

    if compose_text and _preserves_content(raw, compose_text):
        return compose_text
    return raw  # compose failed, empty, or gutted content — raw survives unstyled


__all__ = [
    "PERFORM_TASK_SPEC",
    "LANE_CONTRACT",
    "COMPOSE_RULES",
    "MAX_HISTORY_PAIRS",
    "MAX_HISTORY_CHARS",
    "run_persona_turn",
]
