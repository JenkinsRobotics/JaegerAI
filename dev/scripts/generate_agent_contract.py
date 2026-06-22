#!/usr/bin/env python3
"""Generate ``jaeger_os/docs/agent_contract.md`` from ``core/prompts/rules.py``.

The agent's behavioural contract — the literal text the model sees on
every turn — lives in ``rules.py`` as a handful of plain string
constants. Reading them out of code requires people to grep, and they
drift away from the natural place to ask "what does Jaeger HAVE to
do?" (a doc).

This script is the single source of truth: re-run it after any change
to ``rules.py`` and ``jaeger_os/docs/agent_contract.md`` regenerates.
CI can re-run it and diff to catch drift (see
``dev/tests/jaeger_os/core/test_polish_group5.py``).

Usage:
    dev/scripts/generate_agent_contract.py            # write the doc
    dev/scripts/generate_agent_contract.py --check    # exit 1 if stale

POLISH-5 in dev/docs/ROADMAP_0.2.0.md.
"""

from __future__ import annotations

# Self-bootstrap: when ``test_polish_group5.py`` invokes this script
# as a subprocess (no PYTHONPATH inherited), the ``from jaeger_os...``
# import below raises ``ModuleNotFoundError: No module named
# 'jaeger_os'``.  Walk up to the repo root (dev/scripts/ → dev → root)
# and prepend to ``sys.path`` BEFORE the heavy stdlib imports so the
# bootstrap can never lose to its own side effects.
import os.path as _osp
import sys as _sys
_REPO = _osp.dirname(_osp.dirname(_osp.dirname(_osp.abspath(__file__))))
if _REPO not in _sys.path:
    _sys.path.insert(0, _REPO)

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent   # dev/scripts/ → root
RULES_PATH = REPO / "jaeger_os" / "core" / "prompts" / "rules.py"
DOC_PATH = REPO / "jaeger_os" / "docs" / "agent_contract.md"


# Order matches how ``assemble_prompt`` weaves these into the final
# system prompt (see core/prompts/assemble.py). The doc renders them
# in the same sequence so a reader sees them as the agent would.
_SECTIONS: list[tuple[str, str]] = [
    ("JAEGER_OS_CONTEXT",
     "Identity frame — who the model is told it is on every turn."),
    ("MANDATORY_TOOL_RULES",
     "Hard requirements: tools the agent MUST call rather than "
     "answering from inside its head."),
    ("OPERATING_DISCIPLINE",
     "How to actually get a task done — pacing, focus, the contract "
     "between current message and earlier context."),
    ("TOOL_USAGE_RULES",
     "Mechanics of calling tools (formatting, retries, when to stop)."),
    ("RUNTIME_TAIL_BASE",
     "Always-on tail block — runtime details and the agent's "
     "self-improvement contract."),
    ("RUNTIME_TOOLSET_SCOPED",
     "Tail block appended when ``JAEGER_TOOLSET_SCOPING`` is ON "
     "(``load_toolset`` widens the active surface)."),
    ("RUNTIME_TOOLSET_UNSCOPED",
     "Tail block appended when ``JAEGER_TOOLSET_SCOPING`` is OFF "
     "(every registered tool already visible)."),
]


_HEADER = """\
# Agent contract

Auto-generated from `jaeger_os/core/prompts/rules.py` by
`dev/scripts/generate_agent_contract.py`. Do not hand-edit — re-run the
script after changing `rules.py` and the diff will land here.

This document mirrors the **literal text** the agent sees in its
system prompt every turn. Treat it as the canonical contract between
the framework and the model: anything the agent is told to "always",
"never", "MUST", "before X" lives here.

The actual system prompt is the concatenation of these blocks plus
per-instance content (`identity.yaml`, `soul.md`) — see
`core/prompts/assemble.py` for the weave order.

"""


def render() -> str:
    out: list[str] = [_HEADER]
    # Lazy import so a syntax error in rules.py surfaces here, not at
    # script-collection time.
    sys.path.insert(0, str(REPO / "src"))
    from jaeger_os.agent.prompts import rules as _rules

    for name, intro in _SECTIONS:
        text = getattr(_rules, name, None)
        if text is None:
            out.append(f"## `{name}`\n\n_(missing in rules.py — generator skipped)_\n\n")
            continue
        out.append(f"## `{name}`\n\n")
        out.append(f"_{intro}_\n\n")
        # Render inside a fenced ``text`` block so backticks /
        # markdown special chars inside the rules don't get interpreted.
        out.append("```text\n")
        out.append(text.rstrip("\n") + "\n")
        out.append("```\n\n")
    return "".join(out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="generate_agent_contract")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the doc is stale (no write)")
    args = parser.parse_args(argv)

    fresh = render()
    if args.check:
        if not DOC_PATH.exists():
            sys.stderr.write(f"{DOC_PATH} missing — run the generator.\n")
            return 1
        on_disk = DOC_PATH.read_text(encoding="utf-8")
        if on_disk != fresh:
            sys.stderr.write(
                f"{DOC_PATH} is out of date — run "
                f"dev/scripts/generate_agent_contract.py to regenerate.\n"
            )
            return 1
        print(f"[agent_contract] {DOC_PATH.name}: up to date")
        return 0

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(fresh, encoding="utf-8")
    print(f"[agent_contract] wrote {DOC_PATH.relative_to(REPO)} "
          f"({len(fresh):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
