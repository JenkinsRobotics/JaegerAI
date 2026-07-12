"""``jaeger prompt`` — see the system prompt the LLM actually receives.

Renders the assembled system prompt for an instance, fragment by fragment,
each tagged with its kind and source file — so you can see EXACTLY what rules
are in effect and where they come from. The assembly is the registry
``PROMPT_FRAGMENTS`` in ``agent/prompts/assemble.py``; this command renders
it. Nothing reaches the model that isn't a fragment there, so this is the
complete picture.

  jaeger prompt                  full dump, active instance, agent mode
  jaeger prompt --fragments      one-line-per-fragment table (fired + skipped)
  jaeger prompt --raw            verbatim assembled prompt (what the LLM gets)
  jaeger prompt -i work --mode subagent
"""

from __future__ import annotations

from typing import Any

from . import _common as c

_MODES = ["agent", "subagent", "deep_think", "idle_board", "cron"]


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "prompt",
        help="inspect the assembled system prompt the LLM receives",
    )
    parser.add_argument(
        "--instance", "-i", default=None,
        help="instance name (default: the active instance)",
    )
    parser.add_argument(
        "--mode", default="agent", choices=_MODES,
        help="which prompt mode to render (default: agent)",
    )
    parser.add_argument(
        "--fragments", action="store_true",
        help="list the fragment table only (name/kind/source), no full text",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="print the assembled prompt verbatim — exactly what the LLM gets",
    )
    parser.set_defaults(_handler=run_prompt)


def _resolve_layout(args: Any) -> Any:
    if args.instance:
        from jaeger_ai.core.instance.instance import (
            InstanceLayout,
            resolve_instance_dir,
        )
        return InstanceLayout(resolve_instance_dir(args.instance))
    return c.get_active_instance_layout()


def run_prompt(args: Any) -> int:
    layout = _resolve_layout(args)
    if layout is None:
        print(c.red("  no active instance — run `jaeger instances create` first"))
        return 1

    from jaeger_ai.agent.prompts.assemble import PROMPT_FRAGMENTS, iter_fragments

    rendered = iter_fragments(layout, mode=args.mode)
    fired = {frag.name for frag, _ in rendered}

    # --raw: just the bytes the model receives, nothing else.
    if args.raw:
        print("\n\n".join(text for _, text in rendered))
        return 0

    total = sum(len(t) for _, t in rendered)
    print()
    print(
        f"  {c.bold('System prompt')}  ·  instance {c.cyan(layout.root.name)}"
        f"  ·  mode {c.cyan(args.mode)}  ·  {c.bold(str(total))} chars"
    )
    print(c.dim(
        f"  assembled from agent/prompts/assemble.py — "
        f"{len(rendered)} of {len(PROMPT_FRAGMENTS)} fragments applied this mode"
    ))
    print()

    # --fragments: the map. Shows EVERY fragment (fired ✓ or skipped ·) so a
    # conditional one can never hide.
    if args.fragments:
        for frag in PROMPT_FRAGMENTS:
            on = frag.name in fired
            chars = next((len(t) for f, t in rendered if f.name == frag.name), 0)
            mark = c.green("✓") if on else c.dim("·")
            size = f"{chars:>6} chars" if on else "      —     "
            line = f"  {mark} {frag.name:<18} {frag.kind:<9} {size}  {frag.source}"
            print(line if on else c.dim(line))
            print(c.dim(f"       └ {frag.note}"))
        print()
        return 0

    # default: full dump, banner per fragment.
    for frag, text in rendered:
        print(c.cyan(
            f"══════ {frag.name}  [{frag.kind} · {frag.source}]  "
            f"· {len(text)} chars ══════"
        ))
        print(text)
        print()
    return 0
