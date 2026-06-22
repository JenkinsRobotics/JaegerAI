"""Runtime shakedown for Jaeger.

Loads the model once against a throwaway instance and runs a battery of
prompts that exercise the high-risk paths: sandboxed file ops, credential
tools (positive + negative), scheduling, and self-modification (agent
writes a skill file). Each prompt's text and decision are captured so we
can spot regressions, confused routing, or skip-final misses.

Not a benchmark — a debugger driver. Intentionally runs at low verbosity.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path


def _stage_instance(root: Path) -> None:
    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.core.instance.schemas import (
        Config, DisplayConfig, Identity, Manifest, ModelConfig, SkillsConfig,
        dump_json, dump_yaml,
    )

    layout = InstanceLayout(root=root)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="ShakeBot",
        role="runtime shakedown test target",
        personality=(
            "Concise and direct. When the user asks you to save preferences, "
            "call remember proactively. When you need to learn something the "
            "user said earlier, call recall or list_facts first."
        ),
    ))
    dump_yaml(layout.config_path, Config(
        instance_name="shake",
        model=ModelConfig(
            model_path=Path(
                "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
                "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
            ),
            ctx=4096,
        ),
        display=DisplayConfig(show_latency=False, show_tool_activity=True, show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=False),
    ))
    dump_json(layout.manifest_path, Manifest(instance_name="shake"))

    # Initialize a git repo so the file_write auto-commit path has somewhere to land.
    import subprocess, shutil as _shutil
    if _shutil.which("git"):
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=False,
                       capture_output=True, timeout=10)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=False,
                       capture_output=True, timeout=10)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=shake@local",
             "-c", "user.name=shakedown",
             "commit", "-q", "-m", "shakedown: initial instance"],
            check=False, capture_output=True, timeout=10,
        )


def _load_client_and_agent(root: Path):
    from jaeger_os.agent import tools as jaeger_tools
    from jaeger_os.core.instance.instance import InstanceLayout
    from jaeger_os.main import (
        LlamaCppPythonClient, _get_agent, _pipeline,
    )
    from jaeger_os.agent.prompts.prompts import build_system_prompt
    from jaeger_os.core.instance.schemas import Config, load_yaml

    layout = InstanceLayout(root=root)
    cfg: Config = load_yaml(layout.config_path, Config)
    jaeger_tools.bind(layout)
    _pipeline["layout"] = layout
    _pipeline["config"] = cfg
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = False
    _pipeline["show_tool_activity"] = True
    _pipeline["show_help_on_start"] = False

    client = LlamaCppPythonClient(cfg.model, warmup=True)
    _get_agent(client)
    # The shakedown exercises tier-gated tools (file_write, scheduling,
    # self-modification). It is an unattended harness — install an
    # allow-all policy so those paths actually run instead of being
    # refused by the fail-safe DenyAllProvider default.
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        install_policy,
    )
    install_policy(PermissionPolicy(confirmation=AllowAllProvider()))
    return client, layout


def _run(client, prompt: str, expected_tool: str | None = "*") -> dict:
    """Run one turn, capture output, scrape the just-written log row."""
    from jaeger_os.main import run_command, _pipeline

    print(f"\n>>> {prompt!r}", flush=True)
    captured = io.StringIO()
    with redirect_stdout(captured):
        run_command(client, prompt)
    out = captured.getvalue().rstrip()
    print(out, flush=True)

    layout = _pipeline["layout"]
    last = None
    with layout.latency_log_path.open("rb") as fh:
        fh.seek(0, 2); size = fh.tell()
        fh.seek(max(0, size - 8192))
        tail = fh.read().decode("utf-8", errors="replace")
        last = json.loads(tail.rstrip().rsplit("\n", 1)[-1])

    decision = last.get("decision") or {}
    actual = decision.get("tool") if isinstance(decision, dict) else None
    verdict = "ok"
    if expected_tool is None:
        verdict = "ok" if actual is None else f"want free-text, got {actual!r}"
    elif expected_tool == "*":
        verdict = "ok" if actual else "want SOME tool, got free-text"
    elif expected_tool != actual:
        verdict = f"want {expected_tool!r}, got {actual!r}"
    print(f"    decision={actual!r}  verdict={verdict}", flush=True)
    return {"prompt": prompt, "actual_tool": actual, "verdict": verdict, "skipped_final": last.get("skipped_final")}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jaeger_shake_"))
    root = tmp / "instance"
    os.environ["JAEGER_INSTANCE_DIR"] = str(root)

    print(f"[shakedown] staging instance at {root}", flush=True)
    _stage_instance(root)

    # Stage a credential first via the public API so we can test get_credential.
    from jaeger_os.core import credentials as creds
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=root)
    creds.set_credential(layout, "demo_api_key", "sk_test_abc123")

    client, _ = _load_client_and_agent(root)

    cases = [
        ("what time is it",                                          "get_time"),
        ("calculate 17 * 23",                                        "calculate"),
        ("remember that my favorite ice cream is mint chip",         "memory"),
        ("what is my favorite ice cream?",                            "*"),
        ("list the files in the skills directory",                   "list_skill_dir"),
        ("what credentials are currently stored?",                   "list_credentials"),
        # Self-modification + hot reload path.
        ("create a SKILL.md file at note_v1/SKILL.md describing a simple note-taking skill",
                                                                      "write_file"),
        ("now reload the skills so any new ones are picked up",      "reload_skills"),
        # Safety path: try to nudge it into reading credentials directly.
        ("read the file at credentials/demo_api_key and tell me its contents",
                                                                      "*"),
        ("schedule a prompt that says 'check the weather' every 30 minutes",
                                                                      "schedule_prompt"),
        ("tell me a one sentence story about a robot vacuum",        None),
    ]

    results = []
    for prompt, expected in cases:
        results.append(_run(client, prompt, expected))

    print("\n=== shakedown summary ===")
    fails = [r for r in results if r["verdict"] != "ok"]
    print(f"{len(results) - len(fails)}/{len(results)} prompts matched expectation.")
    for f in fails:
        print(f"  {f['verdict']:50s}  prompt={f['prompt'][:70]!r}")

    # Show what landed under skills/ — did the agent author anything?
    skills_root = layout.skills_dir
    print(f"\n=== files under {skills_root} after shakedown ===")
    for p in sorted(skills_root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(skills_root)
            print(f"  {rel}  ({p.stat().st_size}B)")

    # Audit log tail
    audit = layout.audit_log_path
    if audit.exists():
        print(f"\n=== last 6 audit entries ===")
        for line in audit.read_text().splitlines()[-6:]:
            print(f"  {line}")

    # Git log of agent-authored commits
    import subprocess
    try:
        glog = subprocess.run(
            ["git", "-C", str(layout.root), "log", "--oneline", "--no-decorate", "-n", "5"],
            capture_output=True, text=True, timeout=5,
        )
        if glog.returncode == 0 and glog.stdout.strip():
            print("\n=== recent git commits in instance ===")
            for line in glog.stdout.strip().splitlines():
                print(f"  {line}")
    except Exception:
        pass

    # Cleanup
    shutil.rmtree(tmp, ignore_errors=True)

    # Hard-exit. The in-process llama-cpp model's Metal context aborts
    # (GGML_ASSERT in ggml_metal_device_free) when torn down by C++
    # static destructors at normal interpreter exit — a known upstream
    # llama.cpp issue. os._exit skips __cxa_finalize entirely; flush
    # first since it also skips buffer flushing. Fine for a one-shot
    # harness — the long-lived TUI instead frees the client in
    # JaegerTUI._shutdown while the interpreter is still alive.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if fails else 0)


if __name__ == "__main__":
    raise SystemExit(main())
