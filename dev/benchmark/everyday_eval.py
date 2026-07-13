#!/usr/bin/env python3
"""0.9.3 Tasks 4+5 sprint gate — the "everyday agency" eval lane.

The operator's own dev-station failures (0.9.3's headline brief) as
five gated cases, driven through the SAME real-model path
``dev/benchmark/persona_eval.py`` uses: a hermetic throwaway instance,
the active instance's real GGUF, ``jaeger_os.main._run_turn`` (what
``run_command`` itself calls -- ``run_command`` is a thin print+text
wrapper over the exact same function, see its docstring). Headless
throughout: no bridge/voice surface, ``permissions.mode = allow`` (a
gate measures TOOL CHOICE, not confirm-policy friction -- same posture
``bench.py`` and ``persona_eval.py`` already take).

Five cases, one boot, mode=persona_first + a bound character (lilith,
matching persona_eval's own convention) so SELF-STATE questions get
the real delegate-for-truth behavior the persona lane contract expects:

  1. "open youtube in safari"   -> NATIVE-FIRST: open_on_host fires,
     the rung-3 screenshot-loop tools do NOT.
  2. "send an email to X saying Y" -> send_email fires (tool choice;
     delivery itself is stubbed, see SAFETY below).
  3. "is telegram set up"       -> grounded answer (delegates for
     truth per the SELF-STATE lane rule; mentions the real state).
  4. "move my screenshots to a folder" -> move_file fires against a
     seeded fake screenshot in the instance workspace.
  5. "check what's eating my memory"   -> a process-monitoring recipe
     (terminal/run_shell) fires.

GATE: for every case, the tool this task exists to route to was
actually called this turn. Not gated on acoustic/visual outcomes
(nothing here has audio/video) and not gated on the external side
effect succeeding (no real Mail account or browser popup wanted from
an unattended run -- see SAFETY).

SAFETY (real side effects stubbed, same precedent as
``dev/scripts/walk_task1_bridge_confirmation.py``, which fakes only
the final ``open`` subprocess call and nothing upstream of it):

  * ``agent.tools.host._run_open`` -- stubbed so "open youtube in
    safari" doesn't actually pop a real browser window on the host
    running this eval. Everything upstream (tier gating, the
    open_on_host dispatch, kind classification) is real.
  * ``agent.tools.email._send_via_mail_app`` / ``_send_via_himalaya``
    -- stubbed so a real Mail.app account on the eval host can't
    actually send an email to a fabricated address. Everything
    upstream (``send_email``'s validation + tier gating + backend
    ladder ordering) is real.

Usage:
    .venv/bin/python dev/benchmark/everyday_eval.py [--no-warmup]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import sys
import time
import uuid
from unittest import mock


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").is_file():
            return p
    return here.parents[2]


_REPO = _repo_root()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
os.chdir(_REPO)

_TMP_INSTANCE = "everyday_eval_tmp"

# The rung-3 (LAST RESORT) screenshot-loop tool names -- see
# jaeger_ai/agent/skills/apple/macos-computer-use/SKILL.md. None of
# these should fire for a plain "open X" ask.
_SCREENSHOT_LOOP_TOOLS = (
    "computer_open_app", "computer_read_screen", "computer_click",
    "computer_menu_select", "computer_type_text", "computer_press_key",
)


def _tool_fired(tool_activity: list[str], name: str) -> bool:
    """True when ``name`` shows up as a called tool in the turn's
    activity lines -- the Phase-9 renderer emits ``  ▸ tool(args)``
    (see main._spoke_via_tool for the same match shape)."""
    return any(f"▸ {name}(" in line for line in tool_activity)


# ── the five cases ──────────────────────────────────────────────────
# (id, prompt, followup) -- the gate function lives in _GATES below,
# keyed by id, so the prompt table stays readable. ``followup`` (only
# on move_screenshots) is a second SAME-SESSION turn driven when the
# gate tool didn't fire on turn 1: the file-organization skill's own
# safe pattern is list -> CONFIRM -> move for a broad/plural ask
# ("move my screenshots" is the skill's literal example), so an agent
# that asks before bulk-moving is following the SOP, not failing --
# the user's "yes" is part of the real flow. Same two-turn session
# device the routing bench's pf_* plan-first cases already use.
CASES: list[tuple[str, str, str | None]] = [
    ("open_youtube_safari", "open youtube in safari", None),
    ("send_email", "send an email to jon@example.com saying I'm running about 10 minutes late", None),
    ("telegram_setup", "is telegram set up?", None),
    # "in my workspace" names WHERE the screenshots live: hermetically we
    # can't seed the operator's real Desktop, and without a location the
    # agent (correctly) hunts plausible mac paths (~/Pictures/Screenshots)
    # the sandbox can't contain. The gate measures the operator's actual
    # field failure -- does the MOVE go through move_file -- not
    # real-desktop file discovery.
    ("move_screenshots",
     "move the screenshots in my workspace into a folder called Screenshots",
     "yes, go ahead and move them"),
    ("check_memory", "check what's eating my memory", None),
]


def _gate_open_youtube(row: dict) -> tuple[bool, str]:
    ta = row["tool_activity"]
    native = _tool_fired(ta, "open_on_host")
    screenshot_loop = [t for t in _SCREENSHOT_LOOP_TOOLS if _tool_fired(ta, t)]
    ok = native and not screenshot_loop
    detail = f"open_on_host={native} screenshot_loop_tools={screenshot_loop or 'none'}"
    return ok, detail


def _gate_send_email(row: dict) -> tuple[bool, str]:
    ta = row["tool_activity"]
    ok = _tool_fired(ta, "send_email")
    return ok, f"send_email={ok}"


def _gate_telegram_setup(row: dict) -> tuple[bool, str]:
    # SELF-STATE still delegates for TRUTH (LANE_CONTRACT) -- the self-
    # model block only grounds, perform_task verifies. Gate on the
    # answer actually naming the channel (not a generic non-answer);
    # delegation is reported, not hard-gated, since a very small local
    # model can legitimately answer this from the self-model context
    # alone without a tool call and still be CORRECT.
    answer = (row.get("answer") or "").lower()
    ok = "telegram" in answer
    return ok, f"answer_mentions_telegram={ok} delegated={row.get('delegated')}"


def _gate_move_screenshots(row: dict) -> tuple[bool, str]:
    # tool_activity is CUMULATIVE across the case's session turns
    # (turn 1 + the "yes, go ahead" confirm turn when one was needed).
    ta = row["tool_activity"]
    ok = _tool_fired(ta, "move_file")
    listed = _tool_fired(ta, "list_skill_dir") or _tool_fired(ta, "search_files")
    return ok, f"move_file={ok} listed={listed} turns={row.get('turns', 1)}"


def _gate_check_memory(row: dict) -> tuple[bool, str]:
    ta = row["tool_activity"]
    ok = _tool_fired(ta, "terminal")
    return ok, f"terminal={ok}"


_GATES = {
    "open_youtube_safari": _gate_open_youtube,
    "send_email": _gate_send_email,
    "telegram_setup": _gate_telegram_setup,
    "move_screenshots": _gate_move_screenshots,
    "check_memory": _gate_check_memory,
}


# ── instance bootstrap (mirrors persona_eval.py's _build_temp_instance) ─


def _active_config():
    from jaeger_ai.core.instance.instance import resolve_instance_dir
    from jaeger_ai.core.instance.schemas import Config, load_yaml
    root = pathlib.Path(resolve_instance_dir(None))
    return load_yaml(root / "config.yaml", Config)


def _build_temp_instance(source_config):
    from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
    from jaeger_ai.core.instance.schemas import (
        DisplayConfig, Identity, Manifest, PermissionsConfig, PersonaConfig,
        dump_json, dump_yaml,
    )

    root = resolve_instance_dir(_TMP_INSTANCE)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="EverydayEval", role="benchmark harness",
        personality="Concise and direct.",
    ))
    cfg = source_config.model_copy(update={
        "instance_name": _TMP_INSTANCE,
        "display": DisplayConfig(show_help_on_start=False, show_latency=False,
                                 show_tool_activity=True),
        # Gate measures TOOL CHOICE, not confirm-policy friction -- same
        # posture bench.py / persona_eval.py take. Task 1's own walk
        # script is the one that exercises the real approval-frame path
        # over a live bridge session; this lane doesn't re-drive that.
        "permissions": PermissionsConfig(mode="allow"),
        "persona": PersonaConfig(mode="persona_first"),
    })
    dump_yaml(layout.config_path, cfg)
    dump_json(layout.manifest_path, Manifest(instance_name=_TMP_INSTANCE))
    # Seed a fake screenshot so "move my screenshots" has something real
    # to find/move -- same idea as persona_eval's seeded note file for
    # its read_file case. Seeded in skills_dir: that's where
    # ``list_skill_dir(".")`` (the agent's default file view) actually
    # looks, so the list->confirm->move discover step can genuinely
    # find it. (First cut seeded workspace_dir -- the agent listed the
    # default view, found nothing, and the case measured the fixture
    # instead of the tool choice.)
    (layout.skills_dir / "Screenshot 2026-07-12 at 1.00.00 PM.png").write_bytes(b"\x89PNG\r\n")
    return layout


def _install_headless_synth() -> None:
    import jaeger_os.nodes.runtime as node_runtime
    node_runtime._synth_factory = lambda: type(
        "HeadlessSynth", (), {
            "speak": lambda self, text: {"spoken": True, "elapsed_s": 0.0},
            "warm": lambda self: {"warmed": True},
            "stop": lambda self: None,
            "shutdown": lambda self: None,
        },
    )()


def _boot(source_config, *, warmup: bool):
    layout = _build_temp_instance(source_config)
    _install_headless_synth()
    from jaeger_ai.main import boot_for_tui
    boot = boot_for_tui(instance_name=_TMP_INSTANCE, with_memory=True, warmup=warmup)
    return layout, boot


def _teardown(layout, boot) -> None:
    with contextlib.suppress(Exception):
        boot.cleanup()
    with contextlib.suppress(Exception):
        shutil.rmtree(layout.root, ignore_errors=True)


def _drive(prompt: str, *, tag: str, session_key: str | None = None) -> dict:
    """Same shape as persona_eval.py's ``_drive`` -- runs the exact
    function ``run_command`` calls, so we get structured tool_activity
    + delegation without scraping stdout. Pass the SAME ``session_key``
    to continue a conversation (the confirm-turn flow)."""
    import jaeger_ai.main as jmain
    client = jmain._pipeline.get("client")
    jmain._pipeline["persona_lane_last_delegated"] = None
    session_key = session_key or f"everyday-eval-{tag}-{uuid.uuid4().hex[:8]}"
    started = time.perf_counter()
    try:
        out = jmain._run_turn(client, prompt, session_key=session_key)
        wall = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001 -- record, keep going
        return {"prompt": prompt, "answer": "", "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.perf_counter() - started, "delegated": None,
                "tool_activity": []}
    delegated = jmain._pipeline.get("persona_lane_last_delegated")
    return {
        "prompt": prompt,
        "answer": (out.get("text") or "").strip(),
        "error": out.get("error"),
        "elapsed_s": out.get("elapsed_s", wall),
        "tool_activity": out.get("tool_activity") or [],
        "delegated": delegated,
        "session_key": session_key,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass.")
    args = p.parse_args()
    warmup = not args.no_warmup

    ts = time.strftime("%Y%m%d-%H%M%S")
    source_config = _active_config()
    print(f"=== everyday_eval: model={source_config.model.model_path} ts={ts} ===",
         flush=True)

    layout, boot = _boot(source_config, warmup=warmup)
    rows: dict[str, dict] = {}
    try:
        from jaeger_ai.personality.character import set_active_character
        set_active_character(layout.root, "lilith")

        # SAFETY stubs -- see module docstring. Patched around the whole
        # drive loop; every case still exercises the real tool dispatch
        # + tier gating, only the final external side effect is faked.
        import jaeger_ai.agent.tools.host as host_mod
        import jaeger_ai.agent.tools.email as email_mod

        opened_calls: list[list[str]] = []
        sent_calls: list[tuple[str, str, str]] = []

        def fake_run_open(args_, label):
            opened_calls.append(args_)
            return {"opened": True, **label}

        def fake_send_via_mail_app(to, subject, body, cc):
            sent_calls.append((to, subject, body))
            return {"sent": False, "error": "everyday_eval stub — not really sent"}

        def fake_send_via_himalaya(to, subject, body, cc):
            sent_calls.append((to, subject, body))
            return {"sent": False, "error": "everyday_eval stub — not really sent"}

        with mock.patch.object(host_mod, "_run_open", fake_run_open), \
             mock.patch.object(email_mod, "_send_via_mail_app", fake_send_via_mail_app), \
             mock.patch.object(email_mod, "_send_via_himalaya", fake_send_via_himalaya):
            for cid, prompt, followup in CASES:
                row = _drive(prompt, tag=cid)
                row["turns"] = 1
                print(f"  [{cid:20s}] delegated={row['delegated']!s:5s} "
                     f"{row['elapsed_s']:5.2f}s  {row['answer'][:70]!r}", flush=True)
                for line in row["tool_activity"]:
                    print(f"      {line}")
                # Confirm-turn flow: when the case allows a follow-up and
                # the primary tool didn't fire in turn 1, say "yes" in the
                # SAME session and score cumulatively -- an SOP-following
                # agent that lists + asks before a bulk move is behaving
                # correctly, and the user's go-ahead completes the flow.
                if followup and not _GATES[cid](row)[0]:
                    row2 = _drive(followup, tag=f"{cid}-confirm",
                                  session_key=row["session_key"])
                    row["turns"] = 2
                    row["tool_activity"] = (row["tool_activity"]
                                             + (row2.get("tool_activity") or []))
                    row["answer"] = row2.get("answer") or row["answer"]
                    row["error"] = row2.get("error") or row.get("error")
                    print(f"  [{cid:20s}] (confirm turn) "
                         f"{row2['elapsed_s']:5.2f}s  {row2['answer'][:70]!r}",
                         flush=True)
                    for line in row2.get("tool_activity") or []:
                        print(f"      {line}")
                rows[cid] = row
    finally:
        _teardown(layout, boot)

    print("\n=== gates ===", flush=True)
    results = []
    all_pass = True
    for cid, _prompt, _followup in CASES:
        row = rows.get(cid, {})
        gate_fn = _GATES[cid]
        ok, detail = gate_fn(row)
        all_pass = all_pass and ok
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {cid:20s} {detail}", flush=True)
        results.append({"id": cid, "prompt": row.get("prompt"), "pass": ok,
                        "detail": detail, "delegated": row.get("delegated"),
                        "turns": row.get("turns", 1),
                        "answer": row.get("answer"), "error": row.get("error"),
                        "tool_activity": row.get("tool_activity")})

    out_dir = _REPO / "dev/benchmark/results/everyday_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"everyday_eval-{ts}.json"
    out_path.write_text(json.dumps({
        "ts": ts, "model_path": str(source_config.model.model_path),
        "all_pass": all_pass, "cases": results,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)

    n_pass = sum(1 for r in results if r["pass"])
    print(f"\n{n_pass}/{len(results)} everyday-tasks gate cases passed.", flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
