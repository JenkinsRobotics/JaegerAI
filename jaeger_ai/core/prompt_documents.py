"""SOUL.md and AGENTS.md — this instance's two context documents.

Two documents, two jobs, and keeping them apart is the point:

  SOUL.md    WHO the agent is — character, values, voice, self-narrative.
             Hand-written by the operator, or maintained by the agent
             through ``update_soul``.
  AGENTS.md  HOW it operates — tool directives, mission objectives,
             hardware bindings, house rules for this deployment.

Before the split there was one document (``soul.md``) that **nothing
read**: the setup wizard wrote it, ``update_soul`` maintained it, and no
prompt fragment ever loaded it. Operational directives had no home at
all, so mission text went into the identity file and travelled with the
persona to instances whose tools and hardware were different.

WHY THIS LIVES IN JAEGERAI
--------------------------
The prompt assembler ships in **jaeger-agent** (the brain moved out of
this repo at 0.10.0). It exposes its assembly as a declared registry —
``PROMPT_FRAGMENTS``, a plain ordered list — so a host can contribute
fragments without the module knowing anything about them. That is what
this module does: the loaders and the fragments are JaegerAI's, because
an *instance* is JaegerAI's concept, and the dependency stays untouched
and unpinned-to-a-fork.

The seam is the one soft spot: jaeger-agent has no ``register_fragment``
API, so :func:`register_context_documents` inserts into the list by
position, anchored on fragment NAMES rather than indices. If the
dependency ever renames ``identity_name`` or ``framework`` the anchors
stop matching and the fragments append at the end instead of vanishing —
degraded ordering, never a lost document. Ask upstream for a real
registration hook if this seam ever bites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Cap each document so a long one can't crowd out the routing
# imperatives — the model attends most to the start of the prompt, and a
# 10K-char soul.md pushed MANDATORY_TOOL_RULES into low-attention
# territory in benchmarks.
SOUL_MAX_CHARS = 4_000
DIRECTIVES_MAX_CHARS = 8_000

# Uppercase is canonical — the convention every agent runtime that reads
# these files uses. The lowercase spellings stay resolvable because
# existing instances on disk were written as ``soul.md`` by the wizard,
# and jaeger-agent's ``update_soul`` tool still writes that name.
SOUL_NAMES = ("SOUL.md", "soul.md")
DIRECTIVES_NAMES = ("AGENTS.md", "agents.md")


def _load_context_doc(layout: Any, names: tuple[str, ...], cap: int) -> str:
    """Read the first of ``names`` that exists under the instance root.

    One helper for both documents (an ordered candidate list, first match
    wins, capped before it reaches the prompt). Returns ``""`` for
    absent, empty, or unreadable — a context document must never break
    boot.
    """
    root = getattr(layout, "root", layout)
    for name in names:
        try:
            path = Path(root) / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001 — unreadable reads as absent
            continue
        if not text:
            continue
        if len(text) > cap:
            text = text[:cap].rstrip() + f"\n…({name} truncated)"
        return text
    return ""


def load_soul(layout: Any) -> str:
    """The instance's identity document — ``SOUL.md`` (or the legacy
    lowercase ``soul.md``). Empty string when absent."""
    return _load_context_doc(layout, SOUL_NAMES, SOUL_MAX_CHARS)


def load_agent_directives(layout: Any) -> str:
    """The instance's operating document — ``AGENTS.md``: tool
    directives, mission objectives, hardware bindings. Empty string when
    absent.

    Kept OUT of :func:`load_soul` on purpose. A directive that lives in
    the identity document gets copied along with the persona to an
    instance whose tools and hardware are different, and then quietly
    instructs the agent to drive something that isn't there.
    """
    return _load_context_doc(layout, DIRECTIVES_NAMES, DIRECTIVES_MAX_CHARS)


# ── fragment builders ───────────────────────────────────────────────


def _soul_identity(ctx: Any) -> str:
    """The instance's own identity document, verbatim.

    This is the ONE dynamic source for who the agent is. Nothing in code
    substitutes for it: when the file is absent the fragment is empty and
    the prompt simply carries no identity prose — a built-in default
    persona injected here would be an identity the operator never wrote
    and cannot edit from disk.

    Identity prose ONLY. Operational directives belong to the
    ``agent_directives`` fragment, and the character VOICE still belongs
    to the output filter, not here — a full character sheet in the worker
    prompt measured ~7 bench points on a 4B.
    ``persona.soul_in_prompt: false`` turns this off for an instance that
    wants the pre-split prompt back.
    """
    try:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(ctx.layout.config_path, Config)
        if not getattr(cfg.persona, "soul_in_prompt", True):
            return ""
    except Exception:  # noqa: BLE001 — no readable config → default ON
        pass
    return load_soul(ctx.layout)


def _agent_directives(ctx: Any) -> str:
    """How this deployment operates.

    Placed AFTER the framework instructions so a deployment can sharpen
    the framework's general rules with its own specifics, and before the
    dynamic blocks (skills, board, catalog) that describe what is
    currently available to act on.
    """
    return load_agent_directives(ctx.layout)


# ── registration ────────────────────────────────────────────────────

SOUL_FRAGMENT = "soul_identity"
DIRECTIVES_FRAGMENT = "agent_directives"


def _user_facing(mode: str) -> bool:
    """Soul / conversational identity — live chat and Deep Think.

    Defined here rather than on jaeger-agent's assemble module so a
    host on an older engine still drops SOUL.md from idle_board / cron.
    """
    return mode in ("agent", "deep_think")


def _insert_after(fragments: list, anchor: str, fragment: Any) -> None:
    """Place ``fragment`` directly after the named anchor, or append when
    the anchor is gone (a dependency rename degrades ordering, never
    drops the document)."""
    for index, existing in enumerate(fragments):
        if existing.name == anchor:
            fragments.insert(index + 1, fragment)
            return
    fragments.append(fragment)


def register_context_documents() -> bool:
    """Contribute the two document fragments to jaeger-agent's prompt
    registry. Idempotent; returns True when the registry now carries
    them.

    Called at boot, before the first prompt assembly. Safe to call again
    — a re-boot in the same process must not duplicate fragments.
    """
    try:
        from jaeger_agent.prompts import assemble
    except Exception:  # noqa: BLE001 — no assembler, nothing to extend
        return False

    fragments = assemble.PROMPT_FRAGMENTS
    present = {f.name for f in fragments}

    # Soul is who the agent is when talking to the user. Standing-work
    # modes (idle_board / cron) are the hands — they keep AGENTS.md
    # (how to operate) and drop SOUL.md (voice / identity prose).
    soul = assemble.PromptFragment(
        SOUL_FRAGMENT, "instance", "instance/SOUL.md",
        _soul_identity, _user_facing,
        "who this instance IS — user-facing modes only; "
        "gated by persona.soul_in_prompt",
    )
    directives = assemble.PromptFragment(
        DIRECTIVES_FRAGMENT, "instance", "instance/AGENTS.md",
        _agent_directives, assemble._non_subagent,  # noqa: SLF001
        "how this instance OPERATES — tools, mission, hardware bindings",
    )
    if SOUL_FRAGMENT in present:
        for index, existing in enumerate(fragments):
            if existing.name == SOUL_FRAGMENT:
                fragments[index] = soul
                break
    else:
        _insert_after(fragments, "identity_name", soul)
    if DIRECTIVES_FRAGMENT not in present:
        _insert_after(fragments, "framework", directives)
    return True


__all__ = [
    "DIRECTIVES_FRAGMENT", "DIRECTIVES_MAX_CHARS", "DIRECTIVES_NAMES",
    "SOUL_FRAGMENT", "SOUL_MAX_CHARS", "SOUL_NAMES",
    "load_agent_directives", "load_soul", "register_context_documents",
]
