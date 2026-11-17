"""``jaeger quickstart`` — first run for a new Mac, no paid keys.

The one command after ``install.sh`` (the curl one-liner runs it for you):

  1. Brain   — picks a free or subscription-safe model that already works on
               this Mac: a signed-in subscription CLI (Grok, Gemini via
               Antigravity, ChatGPT via Codex) or a local Ollama model. It
               never asks for an API key; if nothing is usable it says what
               to install or sign in to and stops.
  2. Agent   — creates the ``jaeger`` agent when none exists (an existing one
               is left as it is).
  3. Services — writes the launchd jobs for the Gateway, the agent and the
               MCP server from THIS machine's paths (``~/.jaeger/launchd``),
               starts them, and adds one login item that brings them up at
               every login (``~/Library/LaunchAgents/com.jenkinsrobotics.jaeger.plist``).
  4. Menu app — builds the menu bar app and installs it as
               ``~/Applications/JaegerAI.app`` (skipped when a JaegerAI.app
               is already installed), then opens it.

  jaeger quickstart [--yes] [--provider ID] [--dry-run] [--json]
                    [--no-services] [--no-app]

``--dry-run`` changes nothing: it prints the pick, the agent step, the launchd
jobs it would write and the app step. ``--provider`` takes a row id from the
pick list (``grok``, ``gemini``, ``chatgpt`` or ``ollama:<model>``).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_NAME = "jaeger"
SERVICE_IDS = ("gateway", "agent", "mcp")
APP_NAME = "JaegerAI.app"


def _say(msg: str = "", *, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


# ── 1. brain ────────────────────────────────────────────────────────


def free_brains() -> list[dict]:
    """Usable no-key brains on this Mac, best first."""
    rows: list[dict] = []
    try:
        from jaeger_ai.core.models.discovery import discover_subscription_clis
        clis = discover_subscription_clis()
    except Exception as exc:  # noqa: BLE001
        clis = []
        rows.append({"id": "_cli_probe", "usable": False, "why": f"CLI probe failed: {exc}"})
    for row in clis:
        models = [m.get("id") for m in row.get("models") or [] if m.get("id")]
        rows.append({
            "id": row["id"],
            "label": f"{row.get('display_name') or row['id']} (your subscription, via its CLI)",
            "provider": "cli",
            "model": models[0] if models else row.get("backend_id"),
            "usable": bool(row.get("reachable")),
            "why": row.get("reason") or ("ready" if row.get("reachable") else row.get("status")),
        })
    try:
        from jaeger_ai.core.models.discovery import discover_ollama
        oll = discover_ollama()
    except Exception:  # noqa: BLE001
        oll = {"online": False}
    local = []
    for m in oll.get("models") or []:
        name = str(m.get("name") or m.get("model") or "")
        caps = m.get("capabilities") or []
        if not name or "cloud" in name or "embed" in name or "embedding" in caps:
            continue
        local.append(name)
    if oll.get("online") and local:
        for name in local[:6]:
            rows.append({"id": f"ollama:{name}", "label": f"{name} (Ollama, on this Mac, free)",
                         "provider": "ollama", "model": name, "usable": True, "why": "ready"})
    else:
        rows.append({"id": "ollama", "label": "Ollama (on this Mac, free)", "provider": "ollama",
                     "model": None, "usable": False,
                     "why": "Ollama is not running" if not oll.get("online") else "no local model pulled"})
    rows = [r for r in rows if not r["id"].startswith("_")]
    rows.sort(key=lambda r: (not r["usable"],))
    return rows


def _choose(rows: list[dict], wanted: str | None, assume_yes: bool) -> dict | None:
    usable = [r for r in rows if r["usable"]]
    if wanted:
        return next((r for r in usable if r["id"] == wanted), None)
    if not usable:
        return None
    if assume_yes or not sys.stdin.isatty():
        return usable[0]
    print("Pick the brain Jaeger should use (no API keys needed):")
    for i, r in enumerate(usable, 1):
        print(f"  {i}. {r['label']}")
    raw = input(f"Choice [1]: ").strip() or "1"
    try:
        return usable[max(1, min(len(usable), int(raw))) - 1]
    except ValueError:
        return usable[0]


NO_BRAIN_HELP = """No free brain is ready on this Mac yet. Set up one of these, then rerun
`jaeger quickstart`:
  • Ollama (free, on this Mac):  brew install ollama && ollama serve &
                                 ollama pull qwen3:8b
  • Grok subscription:           install the grok CLI and sign in
  • Gemini (Google account):     install Antigravity (agy) and sign in
  • ChatGPT subscription:        npm i -g @openai/codex && codex login
Jaeger never needs a paid API key for these."""


# ── 2. agent ────────────────────────────────────────────────────────


def _agent_exists() -> Path | None:
    from jaeger_ai.core.instance.instance import user_instances_root
    root = user_instances_root() / AGENT_NAME
    return root if (root / "config.yaml").exists() else None


def _create_agent(brain: dict) -> str:
    from jaeger_ai.core.instance.setup_wizard import create_instance, setup_defaults
    character = setup_defaults().get("default_character") or "assistant"
    user = os.environ.get("USER") or None
    create_instance(character_id=character, name=AGENT_NAME, display_name="Jaeger",
                    user_name=user, awake_model=brain["model"], awake_provider=brain["provider"],
                    asleep_model=brain["model"], autonomy="scoped", make_default=True)
    return character


# ── 3. services ─────────────────────────────────────────────────────


def _services(brain: dict | None):
    from jaeger_ai.core.runtime import stack
    ids = list(SERVICE_IDS)
    if brain and brain.get("provider") == "ollama" and shutil.which("ollama"):
        ids.insert(0, "ollama")
    return [stack.SERVICE_BY_ID[i] for i in ids if i in stack.SERVICE_BY_ID]


def _gateway_ok() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:33418/health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


# ── 4. menu app ─────────────────────────────────────────────────────


def _installed_app() -> Path | None:
    for base in (Path("/Applications"), Path.home() / "Applications"):
        if (base / APP_NAME).exists():
            return base / APP_NAME
    return None


def _install_app(dry: bool) -> dict:
    if sys.platform != "darwin":
        return {"step": "app", "skipped": "not macOS"}
    have = _installed_app()
    if have:
        return {"step": "app", "skipped": f"already installed at {have}"}
    if not shutil.which("swift"):
        return {"step": "app", "skipped": "Swift (Xcode Command Line Tools) not found"}
    dest = Path.home() / "Applications" / APP_NAME
    if dry:
        return {"step": "app", "would_build": "jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh",
                "would_install": str(dest)}
    script = REPO_ROOT / "jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh"
    env = dict(os.environ, JAEGER_MAC_CONFIGURATION="release")
    subprocess.run(["bash", str(script)], check=True, env=env)
    root = subprocess.run(["bash", str(script.parent / "build-root.sh")], capture_output=True,
                          text=True, check=True, env=env).stdout.strip()
    built = Path(root) / "JaegerShell.app"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(built, dest, symlinks=True)
    subprocess.run(["open", str(dest)], check=False)
    return {"step": "app", "installed": str(dest)}


# ── main ────────────────────────────────────────────────────────────


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jaeger quickstart", description=__doc__.splitlines()[0])
    p.add_argument("--yes", "-y", action="store_true", help="take the best ready brain without asking")
    p.add_argument("--provider", help="pick a brain by id (see --dry-run)")
    p.add_argument("--dry-run", action="store_true", help="show every step, change nothing")
    p.add_argument("--no-services", action="store_true", help="skip launchd setup")
    p.add_argument("--no-app", action="store_true", help="skip the menu bar app")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    quiet = a.json
    report: dict = {"dry_run": a.dry_run, "steps": []}

    # 1. brain
    rows = free_brains()
    report["brains"] = [{k: r[k] for k in ("id", "usable", "why", "model")} for r in rows]
    existing = _agent_exists()
    brain = _choose(rows, a.provider, a.yes or a.dry_run)
    _say("1. Brain", quiet=quiet)
    for r in rows:
        mark = "✓" if r["usable"] else "·"
        _say(f"   {mark} {r['id']:<28} {r['why']}", quiet=quiet)
    if brain is None and not existing:
        _say(NO_BRAIN_HELP if not a.provider else f"'{a.provider}' is not ready on this Mac.", quiet=quiet)
        report["ok"] = False
        if a.json:
            print(json.dumps(report, indent=2))
        return 3
    report["brain"] = brain and {k: brain[k] for k in ("id", "provider", "model")}
    if brain:
        _say(f"   → {brain['label']}", quiet=quiet)

    # 2. agent
    _say("2. Agent", quiet=quiet)
    if existing:
        step = {"step": "agent", "kept": str(existing)}
        _say(f"   ✓ keeping your agent at {existing}", quiet=quiet)
    elif a.dry_run:
        step = {"step": "agent", "would_create": AGENT_NAME, "brain": brain["id"]}
        _say(f"   would create agent '{AGENT_NAME}' on {brain['id']}", quiet=quiet)
    else:
        character = _create_agent(brain)
        step = {"step": "agent", "created": AGENT_NAME, "character": character}
        _say(f"   ✓ created agent '{AGENT_NAME}'", quiet=quiet)
    report["steps"].append(step)

    # 3. services
    _say("3. Services (launchd)", quiet=quiet)
    if a.no_services or sys.platform != "darwin":
        report["steps"].append({"step": "services", "skipped": "--no-services" if a.no_services else "not macOS"})
        _say("   skipped", quiet=quiet)
    else:
        from jaeger_ai.core.runtime import stack
        svcs = _services(brain)
        if a.dry_run:
            jobs = {}
            for s in svcs:
                jobs[str(stack.plist_path_for(s))] = s.command_builder()
            step = {"step": "services", "would_write": jobs,
                    "login_item": str(Path.home() / "Library/LaunchAgents/com.jenkinsrobotics.jaeger.plist"),
                    "login_runs": ["jaeger", "stack", "up", *[s.id for s in svcs], "--json"]}
            for path in jobs:
                _say(f"   would write {path}", quiet=quiet)
        else:
            res = stack.stack_up(svcs, wait_timeout=120.0)
            from jaeger_ai.cli.verbs.autostart_verb import _macos_enable
            login = _macos_enable(["stack", "up", *[s.id for s in svcs], "--json"])
            step = {"step": "services", "ok": bool(res.get("ok")), "login_item": login == 0,
                    "services": [(s["name"], s["state"]) for s in res.get("services", [])]}
            for name, state in step["services"]:
                _say(f"   {name:<14} {state}", quiet=quiet)
        report["steps"].append(step)

    # 4. menu app
    _say("4. Menu bar app", quiet=quiet)
    if a.no_app:
        step = {"step": "app", "skipped": "--no-app"}
    else:
        try:
            step = _install_app(a.dry_run)
        except Exception as exc:  # noqa: BLE001
            step = {"step": "app", "error": str(exc)}
    report["steps"].append(step)
    _say("   " + ", ".join(f"{k}: {v}" for k, v in step.items() if k != "step"), quiet=quiet)

    report["gateway_healthy"] = _gateway_ok()
    report["ok"] = True
    if a.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _say("", quiet=quiet)
        if a.dry_run:
            _say("Dry run: nothing changed.")
        else:
            _say("Done. Open the Jaeger menu bar icon, or chat at http://127.0.0.1:8790.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
