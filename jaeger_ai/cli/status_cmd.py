"""``jaeger status`` — runtime snapshot.

Reports what JaegerAI knows about itself without booting the brain:
  - Active instance
  - Model that would load (path + size)
  - Voice config (enabled, gate, defaults)
  - Whether a JaegerAI process is currently running (via pid file)
  - Aggregate counts: how many skills mastered, etc.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "status",
        help="runtime snapshot — active instance + model + voice + skills",
    )
    parser.set_defaults(_handler=run_status)


def run_status(args: Any) -> int:
    layout = c.get_active_instance_layout()
    print()
    print(f"  {c.bold('JaegerAI status')}")
    print()
    if layout is None:
        print(c.red("  no active instance"))
        return 1

    # Instance
    print(c.kv("Instance",       c.cyan(layout.root.name)))
    print(c.kv("Instance path",  c.dim(str(layout.root.resolve()))))

    # Identity — loaded independently so a broken config doesn't
    # hide the agent's name. ``ident.name`` is the AGENT's own name
    # (identity.yaml), never the character it's playing — labeled
    # "Agent name" so it's never mistaken for a persona preset.
    from jaeger_ai.core.instance.schemas import Config, Identity, load_yaml
    try:
        ident = load_yaml(layout.identity_path, Identity)
        print(c.kv("Agent name",  c.bold(ident.name)))
        if ident.role:
            print(c.kv("Role",    ident.role))
        if ident.voice_id:
            print(c.kv("Voice id", ident.voice_id))
    except Exception as exc:  # noqa: BLE001
        print(c.kv("Identity",   c.red(f"unreadable: {exc}")))
    # Config — separate try so a broken config still shows model
    # info from whichever fields parse.
    try:
        config = load_yaml(layout.config_path, Config)
        model_path = Path(config.model.model_path)
        size = _file_size_human(model_path)
        print(c.kv("Model",       f"{c.bold(model_path.name)}  {c.dim(size)}"))
        print(c.kv("Backend",     config.model.backend))
        print(c.kv("Context",     f"{config.model.ctx} tokens"))
        if config.voice.enabled:
            print(c.kv("Voice",   c.green("enabled") +
                                  c.dim(f"  wake={config.voice.wake_word}"
                                        f"  barge_in={config.voice.barge_in}")))
        else:
            print(c.kv("Voice",   c.dim("disabled")))
    except Exception as exc:  # noqa: BLE001
        print(c.kv("Config",     c.red(f"unreadable: {exc}")))

    # Running process detection
    print()
    print(c.bold("  Running process"))
    pid_path = _find_pid_file(layout)
    if pid_path and pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if _pid_alive(pid):
                print(c.kv("PID",  c.green(str(pid)) +
                                    c.dim(f"  ({pid_path})")))
            else:
                print(c.kv("PID",  c.dim("stale pid file (process dead)")))
        except Exception:  # noqa: BLE001
            print(c.kv("PID",  c.dim("unreadable pid file")))
    else:
        print(c.kv("PID",  c.dim("no process detected")))

    # Skill tree summary
    print()
    print(c.bold("  Skills"))
    try:
        from jaeger_ai.core.skills import service
        rows = service.list_skills(layout)["skills"]
        mine = sum(1 for r in rows if r.get("zone") == "instance")
        by_jaeger = sum(1 for r in rows if r.get("origin") == "agent")
        print(c.kv("Total", str(len(rows))))
        print(c.kv("Instance", f"{mine}  {c.dim(f'({by_jaeger} written by Jaeger)')}"))
        print(c.kv("Disabled", str(sum(1 for r in rows if r.get("disabled")))))
    except Exception as exc:  # noqa: BLE001
        print(c.kv("Skills", c.red(f"unreadable: {exc}")))

    # Personality presence
    print()
    print(c.bold("  Persona file"))
    pj = layout.root / "personality.json"
    if pj.exists():
        print(c.kv("personality.json",
                   c.green("present") + c.dim(f"  ({pj})")))
    else:
        print(c.kv("personality.json",
                   c.dim("absent — defaults active.  jaeger personality view")))
    print()
    return 0


# ── helpers ───────────────────────────────────────────────────────

def _file_size_human(path: Path) -> str:
    try:
        size = path.stat().st_size
    except Exception:  # noqa: BLE001
        return "(?)"
    if size > 1 << 30:
        return f"{size / (1 << 30):.1f} GB"
    if size > 1 << 20:
        return f"{size / (1 << 20):.1f} MB"
    return f"{size / 1024:.1f} KB"


def _find_pid_file(layout) -> Path | None:
    for candidate in (
        layout.root / "jaeger.pid",
        layout.root / "run" / "jaeger.pid",
    ):
        if candidate.exists():
            return candidate
    return None


from jaeger_os.core.process import pid_alive as _pid_alive  # single owner
