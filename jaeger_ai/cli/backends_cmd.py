"""``jaeger backends`` — list installed agent CLI backends.

These CLIs are models, not delegates. ``jaeger runtime`` stays the
GGUF/MLX engine panel; this verb is the PATH onboarding surface
(OpenClaw practice: probe known binaries, show installed vs missing).
"""

from __future__ import annotations

from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "backends",
        help="list installed agent CLI backends (claude, codex, grok, …)",
    )
    parser.set_defaults(_handler=run_backends)
    nested = parser.add_subparsers(dest="backends_verb")
    listed = nested.add_parser("list", help="list installed agent CLI backends")
    listed.set_defaults(_handler=run_backends)


def run_backends(args: Any) -> int:
    del args
    from jaeger_ai.features.cli_backends.service import list_all

    rows = list_all()
    print(c.bold("\nCLI backends — installed agent CLIs as Jaeger models\n"))
    print(c.grey(
        "  Select one as the brain with /model use cli <id> "
        "(e.g. cli:claude). Delegates remain workers.\n"
    ))
    installed = 0
    for item in rows:
        if item.installed:
            installed += 1
            mark = c.green("●")
            state = c.green("installed on PATH")
            where = c.grey(item.executable or "")
        else:
            mark = c.grey("○")
            names = ", ".join(item.spec.executables)
            state = c.yellow(f"missing  (looked for {names})")
            where = ""
        catalog = "" if item.spec.catalog else c.grey("  · listed only (ollama HTTP is the brain)")
        label = item.spec.display_name or item.spec.id
        print(f"  {mark} {c.bold(label):<28} {c.grey('cli:' + item.spec.id):<16} {state}{catalog}")
        if where:
            print(f"      {where}")
    print()
    print(c.grey(
        f"  {installed}/{len(rows)} installed. "
        "These are models in Jaeger's loop; delegate_task still sends a whole job."
    ))
    return 0
