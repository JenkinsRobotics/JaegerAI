"""``ToolDef`` — single source of truth for one tool's contract.

A tool is defined once. The same ``ToolDef`` renders itself three ways
(Anthropic ``input_schema``, OpenAI ``function`` block, Hermes XML
``<tools>`` JSON entry) so we never split the schema and have it drift.
Validation of the model's argument blob happens at dispatch via
``args_model.model_validate`` — that is the single Pydantic trust
boundary per call. Everything else inside the loop is plain dicts.

Flags worth knowing:
  • ``interactive=True``  — must NOT run in parallel with siblings
    (e.g. ``ask_user``, anything that takes the terminal). The agent
    loop forces sequential dispatch when any sibling is interactive.
  • ``dangerous=True``    — physically affects the world. Robots care.
    Reserved for tools like ``move_joint``, ``drive_velocity``,
    ``send_message`` — anything the operator might want confirmed,
    audited, or scoped behind a permission tier on hardware.
  • ``beta=True``         — still being stabilised (e.g. the avatar /
    animation tools while Mochi is the testbed). Beta tools are
    excluded from the agent's catalogue — invisible to the model AND
    undispatchable — unless dev mode is on (``JAEGER_DEV_MODE=1``),
    so a half-tested tool can't break a daily-driver session.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel


def dev_mode_enabled() -> bool:
    """Whether this process runs in dev mode (``JAEGER_DEV_MODE`` set
    to ``1`` / ``true`` / ``yes`` / ``on``).

    Dev mode is the gate for ``ToolDef.beta`` tools: outside it the
    agent never sees them. Read per call (not cached) so tests and a
    long-lived daemon can flip it without a restart."""
    return (os.environ.get("JAEGER_DEV_MODE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


@dataclass
class ToolDef:
    """One callable tool, plus everything needed to expose it to a
    model and dispatch it safely.

    ``args_model`` is a Pydantic class whose JSON schema describes the
    arguments the model is allowed to pass. ``fn`` is the actual
    handler — it receives keyword args matching the model's fields
    after Pydantic validation. Three renderers convert the same schema
    into the three on-wire formats the adapters use.

    Registry-grade metadata (all optional; defaults preserve old
    callers):

      * ``toolset``           — canonical category the tool belongs
        to (matches a key in :mod:`jaeger_os.agent.skill_registry.toolset_scoping`
        ``TOOLSETS``). Lets the registry derive visibility instead
        of the parallel name-set map. Empty string = unclassified.
      * ``permission_tier``   — the tier the ``@requires_tier``
        decorator on ``fn`` enforces. Carried here so the doctor
        and ``describe_tool`` can report it without re-introspecting.
      * ``side_effect``       — one of ``"read"`` / ``"write"`` /
        ``"external"`` / ``"hardware"``, or ``""`` (unclassified —
        the default). The loop treats ONLY an explicit ``"read"``
        as safe for parallel dispatch, batch dedup, and
        changing-result polling tolerance; unclassified tools get
        the conservative write-side treatment. The old default of
        ``"read"`` silently classified every unannotated tool as
        side-effect-free, which would have parallel-dispatched
        ``speak`` and friends.
      * ``max_result_chars``  — per-tool result size budget. When
        set, the context guard truncates this tool's result at
        this cap instead of the global one. ``0`` = use the
        global default.
      * ``check_fn``          — optional zero-arg callable returning
        ``True`` if the tool is currently available (deps installed,
        credentials present, etc.). Tools that return ``False``
        get hidden from the model's schema view.
      * ``requires_env``      — environment variables the tool needs
        at runtime (e.g. ``("OPENAI_API_KEY",)``). The default
        ``check_fn`` checks them when nothing else is provided.
      * ``examples``          — short example invocations for
        ``describe_tool``. List of ``"call name(args)"`` strings.
    """

    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., Any]
    interactive: bool = False
    dangerous: bool = False
    beta: bool = False
    # Registry metadata — see class docstring.
    toolset: str = ""
    permission_tier: str = ""
    side_effect: str = ""
    max_result_chars: int = 0
    check_fn: Callable[[], bool] | None = None
    requires_env: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()

    def is_available(self) -> bool:
        """True when the tool's runtime preconditions are met.

        Precedence:
          1. Explicit ``check_fn`` — its bool result wins.
          2. ``requires_env`` — every named env var must be present
             and non-empty.
          3. No constraints declared → always available.

        Errors from ``check_fn`` are treated as "unavailable" rather
        than propagated; a probe that crashes should never mask the
        rest of the tool surface."""
        if self.check_fn is not None:
            try:
                return bool(self.check_fn())
            except Exception:  # noqa: BLE001
                return False
        if self.requires_env:
            import os
            return all(os.environ.get(k) for k in self.requires_env)
        return True

    # ── on-wire renderers ────────────────────────────────────────────

    def to_anthropic_schema(self) -> dict[str, Any]:
        """The shape Anthropic's Messages API takes in its ``tools``
        list: ``{name, description, input_schema}``."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """The shape OpenAI Chat Completions takes in its ``tools`` list:
        ``{type: 'function', function: {name, description, parameters}}``.
        Covers every OpenAI-compatible endpoint (the real OpenAI,
        OpenRouter, llama.cpp server, LM Studio, Ollama OpenAI-mode,
        Gemini's compat surface, vLLM)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def to_hermes_xml_block(self) -> str:
        """One JSON entry to include inside the ``<tools>...</tools>``
        block in a Hermes-format system prompt. Returns a single line
        of JSON — the adapter is responsible for the surrounding XML."""
        return json.dumps(
            {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.args_model.model_json_schema(),
                },
            },
            ensure_ascii=True,
        )

    # ── dispatch ─────────────────────────────────────────────────────

    def dispatch(self, raw_args: dict[str, Any]) -> Any:
        """Validate ``raw_args`` against ``args_model``, then call
        ``fn``. Pydantic's ``ValidationError`` propagates so the agent
        loop can return it AS a tool result and let the model self-
        correct rather than crashing the turn.

        Phase-8 hardening: pre-coerce open-weight-model drift (string
        scalars where the schema expects numbers / booleans, bare
        scalars where it expects arrays, JSON-encoded strings) before
        validation fires. Pydantic v2 covers the simple string→number
        case but not the array-wrap or JSON-decode cases, both of
        which Gemma / Qwen / GLM hit routinely.
        """
        from jaeger_os.core.tools.arg_coercion import coerce_args
        coerced = coerce_args(raw_args, self.args_model.model_json_schema())
        validated = self.args_model.model_validate(coerced)
        return self.fn(**validated.model_dump())


__all__ = ["ToolDef", "dev_mode_enabled"]
