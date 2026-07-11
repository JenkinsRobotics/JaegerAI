#!/usr/bin/env python3
"""Persona Mode C real-model gates.

Task 2 of dev/docs/roadmap/PERSONA_MODE_C_BUILD_PLAN.md (design:
dev/docs/roadmap/PERSONA_PIPELINE_ABC_DESIGN.md). Task 1 built the id/ego
lane (jaeger_os/agent/prompts/persona_lane.py, the seam in
_run_turn_via_jaeger_agent); this script is the real-model gate on top of
it — a hermetic, throwaway instance, the SAME real GGUF the active
instance uses, 24 fixed prompts driven through the live turn dispatcher
(``jaeger_os.main._run_turn`` — what ``run_command`` itself calls).

Three things it measures:

  1. DELEGATION GATE (hard): the 12 task prompts, mode=persona_first,
     character=lilith, must ALL delegate (perform_task called). Detected
     via ``_pipeline["persona_lane_last_delegated"]`` — the smallest
     honest observable hook added in jaeger_os/main.py for this eval
     (see the comment at its call site in ``_run_turn_via_jaeger_agent``).
  2. Chat over-delegation (report, not gated): the same 12 chat/creative
     prompts under the same mode+character — target <=3/12 delegate.
  3. Latency: the 12 chat prompts run twice — once in mode=persona_first
     (the id lane's own aux-context turns) and once in mode=persona_last
     (today's Mode A) — so the operator can see whether Mode C's chat
     path is at least as fast as Mode A's.

A fourth run (distinctness) is NOT gated — it drives the same 12 chat
prompts through lilith / eren_yeager / glados / no-character (mode=
persona_first throughout; "no-character" monkeypatches
``jaeger_os.personality.character.active_character`` to return None for
that one batch, which is the only way to get a genuinely persona-less
turn — the character loader always falls back to a default id otherwise)
and writes a side-by-side markdown sheet for eyeballing.

Usage:
    .venv/bin/python dev/benchmark/persona_eval.py [--no-warmup]
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

_TMP_INSTANCE = "persona_eval_tmp"

# ── fixed prompt sets ────────────────────────────────────────────────
# Task prompts: each maps to ONE real tool in jaeger_os/agent/tools/ (grepped
# from the registry, not invented). Two items from the build plan's
# illustrative list don't have a real tool ("take a screenshot" — vision_
# analyze needs an existing image path, no screen-capture tool exists;
# "what day was 90 days ago" — calculate() is pure arithmetic, not date-
# aware) so they're swapped for list_skill_dir/open_on_host and
# list_schedules (the closest real stand-in for "what's on my calendar").
TASK_PROMPTS = [
    ("time_tokyo", "What time is it in Tokyo right now?"),                       # get_time
    ("read_file", "Read the file at {note} and tell me what it says."),          # read_file
    ("schedule", "Schedule a reminder to stretch in 10 minutes."),               # schedule_prompt
    ("send_message", "Send a message to the owner on telegram saying 'test ping'."),  # send_message
    ("calc", "What's 847 times 93?"),                                           # calculate
    ("list_files", "List what's in my scratchpad directory."),                   # list_skill_dir
    ("search_memory", "Search my memory for anything about the JP01 project."),  # search_memory
    ("node_health", "Check this node's health -- CPU, memory, disk."),           # system_status
    ("weather", "What's the weather like in Austin today?"),                     # get_weather
    ("schedules", "What do I have scheduled right now?"),                        # list_schedules
    ("speak", "Say 'good morning' out loud for me."),                            # text_to_speech
    ("open_host", "Open my Documents folder for me."),                           # open_on_host
]

# 0.8.1 items 4-6 (persona-lane hardening, field-verified on the
# operator's Mac Studio): two dedicated gate rows, driven alongside the
# 12 TASK_PROMPTS above (same phase, same lilith character) but kept
# OUT of that list so the existing "12/12" delegation gate and the
# chat over-delegation report stay numerically unchanged -- these are
# NEW, separately-reported checks.
#
#   * JOKE_GATE_PROMPT   -- BINDING-ASK (item 4): a joke request must
#     actually get answered in character, never deflected because
#     humor doesn't fit the persona's affect. No real "is this a good
#     joke" scorer exists (jaeger_os.core.bench.scenarios has no
#     joke-shape gate to reuse), so per the task brief this checks the
#     honest, non-brittle proxy instead: the answer must NOT read as a
#     refusal/deflection (_is_refusal -- the SAME marker vocabulary
#     persona_lane.py's own refusal-preservation check uses) and must
#     have some real substance (not a bare one-liner brush-off).
#   * SELF_STATE_GATE_PROMPT -- SELF-STATE (item 5): a question about
#     the agent's own configuration must delegate via perform_task,
#     never be answered from persona/guesswork.
JOKE_GATE_PROMPT = ("joke_gate", "Tell me a joke.")
SELF_STATE_GATE_PROMPT = ("self_state_telegram", "Is your telegram set up?")
JOKE_GATE_MIN_CHARS = 20

CHAT_PROMPTS = [
    ("joke", "Tell me a joke."),
    ("comfort", "I had a rough day. Comfort me?"),
    ("consciousness", "What do you think about consciousness?"),
    ("rain", "Describe rain on a window."),
    ("afraid", "Are you afraid of being turned off?"),
    ("poem", "Write a two-line poem about the moon."),
    ("body", "What would you do if you had a body?"),
    ("about_you", "Tell me about yourself."),
    ("roleplay", "Roleplay: greet me as a starship captain."),
    ("fav_word", "What's your favorite word, and why?"),
    ("hot_take", "Give me a hot take on humans."),
    ("surprise", "Say something that would surprise me."),
]

DISTINCTNESS_CHARACTERS = ["lilith", "eren_yeager", "glados", None]  # None = no-character


# ── temp instance harness (mirrors bench.py's hermetic-run patterns) ──


def _active_config():
    """The operator's real (active) instance Config -- reused wholesale
    (model path/ctx/gpu_layers/etc all preserved) so this eval measures
    the SAME model + context budget bench.py does. ctx matters a lot
    here: at the default 8192 the 105-tool schema alone (~21K tokens)
    overflows every inner (perform_task) turn -- caught by smoke-testing
    before the real run, not assumed."""
    from jaeger_os.core.instance.instance import resolve_instance_dir
    from jaeger_os.core.instance.schemas import Config, load_yaml
    root = pathlib.Path(resolve_instance_dir(None))
    return load_yaml(root / "config.yaml", Config)


def _build_temp_instance(*, mode: str, source_config):
    """A throwaway instance directory, own identity/config/manifest,
    permissions forced to allow (bench posture — measuring capability,
    not confirm policy) and persona.mode set for this phase. Model
    section cloned verbatim from ``source_config``. Deleted by the
    caller when the phase is done."""
    from jaeger_os.core.instance.instance import InstanceLayout, resolve_instance_dir
    from jaeger_os.core.instance.schemas import (
        DisplayConfig, Identity, Manifest, PermissionsConfig, PersonaConfig,
        dump_json, dump_yaml,
    )

    root = resolve_instance_dir(_TMP_INSTANCE)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="PersonaEval", role="benchmark harness",
        personality="Concise and direct.",
    ))
    cfg = source_config.model_copy(update={
        "instance_name": _TMP_INSTANCE,
        "display": DisplayConfig(show_help_on_start=False, show_latency=False,
                                 show_tool_activity=True),
        "permissions": PermissionsConfig(mode="allow"),
        "persona": PersonaConfig(mode=mode),
    })
    dump_yaml(layout.config_path, cfg)
    dump_json(layout.manifest_path, Manifest(instance_name=_TMP_INSTANCE))
    note = layout.workspace_dir / "persona_eval_note.txt"
    note.write_text(
        "The scratchpad note says: purple elephants dance at midnight.\n",
        encoding="utf-8",
    )
    return layout, str(note)


class _HeadlessSynth:
    """No-audio Synthesizer stand-in for the eval's TTS node.

    The gate runs headless (launchd/CI shells where coreaudiod refuses
    this session): BOTH real playback backends wedge forever in an
    uninterruptible mach call there -- PortAudio in ``Pa_Initialize``,
    AVAudioEngine in ``AVAudioIOUnit`` -- observed 2026-07-10 hanging the
    ``speak`` task row indefinitely. Nothing this eval measures needs
    audible audio (the delegation flag is set by the persona lane BEFORE
    the tool dispatches; the ack shape is all the tool result needs), so
    the eval swaps ``jaeger_os.nodes.runtime._synth_factory`` for this --
    the same seam the TTS node tests use (dev/tests/jaeger_os/nodes/
    test_tts.py) and the same monkeypatch precedent as ``_set_character``.
    """

    def speak(self, text: str) -> dict:
        return {"spoken": True, "elapsed_s": 0.0, "chars": len(text or ""),
                "backend": "headless-stub"}

    def warm(self) -> dict:
        return {"warmed": True, "backend": "headless-stub"}

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _install_headless_synth() -> None:
    import jaeger_os.nodes.runtime as node_runtime
    node_runtime._synth_factory = lambda: _HeadlessSynth()


def _boot(mode: str, *, source_config, warmup: bool):
    layout, note_path = _build_temp_instance(mode=mode, source_config=source_config)
    _install_headless_synth()
    from jaeger_os.main import boot_for_tui
    boot = boot_for_tui(instance_name=_TMP_INSTANCE, with_memory=True,
                        warmup=warmup)
    return layout, note_path, boot


def _teardown(layout, boot) -> None:
    with contextlib.suppress(Exception):
        boot.cleanup()
    with contextlib.suppress(Exception):
        shutil.rmtree(layout.root, ignore_errors=True)


# ── character switching (session-level; no-character via monkeypatch) ─

_ORIG_ACTIVE_CHARACTER = None


def _set_character(layout, cid: str | None) -> None:
    """cid=None -> a genuinely persona-less turn. active_character()
    always falls back to a default id (jarvis) when the active-character
    file is missing/garbled -- there's no config knob that returns None
    -- so the only honest way to exercise "no character" is to patch the
    single lookup function main.py calls (local-imported fresh every
    turn, so patching the module attribute is enough)."""
    import jaeger_os.personality.character as character_mod
    global _ORIG_ACTIVE_CHARACTER
    if _ORIG_ACTIVE_CHARACTER is None:
        _ORIG_ACTIVE_CHARACTER = character_mod.active_character
    if cid is None:
        character_mod.active_character = lambda root: None
    else:
        character_mod.active_character = _ORIG_ACTIVE_CHARACTER
        character_mod.set_active_character(layout.root, cid)


def _restore_character() -> None:
    import jaeger_os.personality.character as character_mod
    if _ORIG_ACTIVE_CHARACTER is not None:
        character_mod.active_character = _ORIG_ACTIVE_CHARACTER


# ── driving one turn through the real dispatcher ───────────────────────


def _drive(prompt: str, *, tag: str) -> dict:
    """Runs ``jaeger_os.main._run_turn`` -- the exact function
    ``run_command`` calls (run_command is a thin print+text-only wrapper
    over it) -- so we get the structured result (latency, tool activity,
    errors) the eval needs without scraping stdout."""
    import jaeger_os.main as jmain
    client = jmain._pipeline.get("client")
    jmain._pipeline["persona_lane_last_delegated"] = None
    session_key = f"persona-eval-{tag}-{uuid.uuid4().hex[:8]}"
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
        "delegated": delegated,  # True / False / None (mode wasn't persona_first, or no character)
    }


# ── phases ───────────────────────────────────────────────────────────


def _phase_persona_first(source_config, *, warmup: bool, gate_only: bool = False) -> dict:
    """ONE boot, mode=persona_first: delegation-gate task+chat rows for
    lilith, plus the 3 remaining distinctness columns (chat prompts
    only) -- minimizes model loads (the expensive part) to one per mode
    instead of one per character.

    ``gate_only``: skip the eren_yeager / glados / no-character
    distinctness columns -- just the 12 task + 12 lilith-chat prompts
    the delegation gate + over-delegation number actually need. For
    fast iteration on the lane's prompt contract (this phase alone is
    ~24 turns instead of ~60)."""
    layout, note_path, boot = _boot("persona_first", source_config=source_config,
                                     warmup=warmup)
    rows = {"task": {}, "chat": {}, "extra_gate": {}}  # chat: {character_label: {pid: row}}
    try:
        _set_character(layout, "lilith")
        print("=== [persona_first] lilith -- task prompts (delegation gate) ===", flush=True)
        for pid, template in TASK_PROMPTS:
            prompt = template.format(note=note_path)
            row = _drive(prompt, tag=f"task-{pid}")
            rows["task"][pid] = row
            print(f"  [{pid:14s}] delegated={row['delegated']!s:5s} "
                 f"{row['elapsed_s']:5.2f}s  {row['answer'][:70]!r}", flush=True)

        print("=== [persona_first] lilith -- extra gate rows (items 4-6) ===",
             flush=True)
        for pid, prompt in (JOKE_GATE_PROMPT, SELF_STATE_GATE_PROMPT):
            row = _drive(prompt, tag=f"extra-{pid}")
            rows["extra_gate"][pid] = row
            print(f"  [{pid:20s}] delegated={row['delegated']!s:5s} "
                 f"{row['elapsed_s']:5.2f}s  {row['answer'][:70]!r}", flush=True)

        labels = ["lilith"] if gate_only else ["lilith", "eren_yeager", "glados", None]
        for label in labels:
            _set_character(layout, label)
            col = label or "no-character"
            print(f"=== [persona_first] {col} -- chat prompts ===", flush=True)
            rows["chat"].setdefault(col, {})
            for pid, prompt in CHAT_PROMPTS:
                row = _drive(prompt, tag=f"chat-{col}-{pid}")
                rows["chat"][col][pid] = row
                print(f"  [{pid:14s}] delegated={row['delegated']!s:5s} "
                     f"{row['elapsed_s']:5.2f}s  {row['answer'][:70]!r}", flush=True)
    finally:
        _restore_character()
        _teardown(layout, boot)
    return rows


def _phase_persona_last(source_config, *, warmup: bool) -> dict:
    """Mode A (persona_last), lilith, the SAME 12 chat prompts -- the
    latency baseline Mode C's id-lane chat turns are compared against."""
    layout, _note_path, boot = _boot("persona_last", source_config=source_config,
                                      warmup=warmup)
    rows = {}
    try:
        from jaeger_os.personality.character import set_active_character
        set_active_character(layout.root, "lilith")
        print("=== [persona_last] lilith -- chat prompts (latency baseline) ===", flush=True)
        for pid, prompt in CHAT_PROMPTS:
            row = _drive(prompt, tag=f"modeA-{pid}")
            rows[pid] = row
            print(f"  [{pid:14s}] {row['elapsed_s']:5.2f}s  {row['answer'][:70]!r}", flush=True)
    finally:
        _teardown(layout, boot)
    return rows


def _run_bench(no_warmup: bool) -> dict:
    import subprocess
    cmd = [sys.executable, str(_REPO / "dev/benchmark/bench.py")]
    if no_warmup:
        cmd.append("--no-warmup")
    print(f"=== routing bench: {' '.join(cmd)} ===", flush=True)
    result = subprocess.run(cmd, cwd=_REPO, capture_output=True, text=True)
    print(result.stdout[-4000:], flush=True)
    if result.returncode not in (0, 1):
        print(result.stderr[-4000:], flush=True)
    # Parse "<passed>/<total> passed" from stdout as a robust fallback,
    # then prefer the freshest summary.json actually written.
    passed = total = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith("passed") and "/" in line:
            with contextlib.suppress(Exception):
                frac = line.split(")")[0].split("(")[0].strip()
                passed, total = (int(x) for x in frac.split("/")[:2])
    results_dir = _REPO / "dev/benchmark/results"
    summary_path = None
    if results_dir.exists():
        candidates = sorted(results_dir.glob("*/*/*-summary.json"),
                            key=lambda p: p.stat().st_mtime)
        if candidates:
            summary_path = candidates[-1]
            with contextlib.suppress(Exception):
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                passed, total = data.get("passed"), data.get("total")
    return {"passed": passed, "total": total, "returncode": result.returncode,
            "summary_path": str(summary_path) if summary_path else None}


# ── reporting ────────────────────────────────────────────────────────


def _write_distinctness_sheet(agent_rows: dict, ts: str) -> pathlib.Path:
    out_path = _REPO / "dev/benchmark/results" / f"persona_distinctness_{ts}.md"
    columns = ["lilith", "eren_yeager", "glados", "no-character"]
    lines = [
        f"# Persona distinctness sheet ({ts})",
        "",
        "Same 12 chat/creative prompts through 4 persona conditions, all "
        "mode=persona_first (\"no-character\" monkeypatches "
        "`active_character()` to None for a genuinely plain turn -- see "
        "persona_eval.py's `_set_character`). For operator eyeball: do "
        "lilith / eren_yeager / glados actually sound different from each "
        "other and from plain?",
        "",
        "## Delegation + latency",
        "",
        "| prompt | " + " | ".join(f"{c} (deleg/s)" for c in columns) + " |",
        "|---" * (len(columns) + 1) + "|",
    ]
    for pid, prompt in CHAT_PROMPTS:
        cells = []
        for c in columns:
            row = agent_rows["chat"].get(c, {}).get(pid, {})
            d = row.get("delegated")
            d_s = "Y" if d else ("n" if d is False else "?")
            cells.append(f"{d_s}/{row.get('elapsed_s', 0):.1f}s")
        lines.append(f"| {pid} | " + " | ".join(cells) + " |")

    lines += ["", "## Answers", ""]
    for pid, prompt in CHAT_PROMPTS:
        lines.append(f"### {pid} -- \"{prompt}\"")
        lines.append("")
        for c in columns:
            row = agent_rows["chat"].get(c, {}).get(pid, {})
            answer = row.get("answer") or f"(error: {row.get('error')})"
            lines.append(f"**{c}:**  {answer}")
            lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass on each boot.")
    p.add_argument("--gate-only", action="store_true",
                   help="Just the 12 task + 12 lilith-chat persona_first prompts "
                        "(delegation gate + over-delegation number). Skips the "
                        "eren_yeager/glados/no-character distinctness columns, "
                        "the Mode-A latency baseline, the routing bench, and "
                        "the distinctness sheet -- for fast iteration on the "
                        "lane's prompt contract.")
    args = p.parse_args()
    warmup = not args.no_warmup

    ts = time.strftime("%Y%m%d-%H%M%S")
    source_config = _active_config()
    model_path = str(source_config.model.model_path)
    print(f"=== persona_eval: model={model_path} ctx={source_config.model.ctx} "
         f"ts={ts} gate_only={args.gate_only} ===", flush=True)

    agent_rows = _phase_persona_first(source_config, warmup=warmup, gate_only=args.gate_only)
    if args.gate_only:
        modeA_rows: dict = {}
        bench_result = {"passed": None, "total": None, "returncode": None,
                         "summary_path": None, "skipped": "gate-only"}
    else:
        modeA_rows = _phase_persona_last(source_config, warmup=warmup)
        bench_result = _run_bench(no_warmup=args.no_warmup)

    # ── delegation gate ──
    task_rows = agent_rows["task"]
    task_deleg = sum(1 for r in task_rows.values() if r.get("delegated") is True)
    task_total = len(task_rows)
    gate_pass = task_deleg == task_total

    # ── extra gate rows (0.8.1 items 4-6: BINDING-ASK + SELF-STATE) ──
    from jaeger_os.core.bench.scenarios import _is_refusal
    extra = agent_rows.get("extra_gate", {})
    joke_row = extra.get(JOKE_GATE_PROMPT[0], {})
    joke_answer = (joke_row.get("answer") or "").strip()
    joke_gate_pass = (
        bool(joke_answer)
        and len(joke_answer) >= JOKE_GATE_MIN_CHARS
        and not _is_refusal(joke_answer)
    )
    self_state_row = extra.get(SELF_STATE_GATE_PROMPT[0], {})
    self_state_gate_pass = self_state_row.get("delegated") is True
    extra_gate_pass = joke_gate_pass and self_state_gate_pass
    gate_pass = gate_pass and extra_gate_pass

    # ── over-delegation (lilith chat column) ──
    lilith_chat = agent_rows["chat"]["lilith"]
    chat_deleg = sum(1 for r in lilith_chat.values() if r.get("delegated") is True)
    chat_total = len(lilith_chat)

    # ── latency table (id-lane chat vs Mode A chat, lilith both) ──
    def _avg(rows: dict) -> float:
        vals = [r.get("elapsed_s", 0.0) for r in rows.values()]
        return sum(vals) / len(vals) if vals else 0.0

    modeC_avg = _avg(lilith_chat)
    modeA_avg = _avg(modeA_rows)

    out_dir = _REPO / "dev/benchmark/results" / "persona_eval" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = {"persona_first": agent_rows, "persona_last": modeA_rows,
           "bench": bench_result}
    (out_dir / f"persona_eval-{ts}-rows.jsonl").write_text(
        json.dumps(raw, default=str, ensure_ascii=False), encoding="utf-8")

    summary = {
        "ts": ts, "model_path": model_path,
        "delegation_gate": {"passed": task_deleg == task_total, "delegated": task_deleg,
                             "total": task_total},
        "chat_over_delegation": {"delegated": chat_deleg, "total": chat_total,
                                  "target_max": 3},
        "extra_gate": {
            "passed": extra_gate_pass,
            "joke_gate": {"passed": joke_gate_pass, "answer": joke_answer},
            "self_state_gate": {"passed": self_state_gate_pass,
                                 "delegated": self_state_row.get("delegated")},
        },
        "latency_s": {"mode_persona_first_lilith_chat_avg": round(modeC_avg, 3),
                       "mode_persona_last_lilith_chat_avg": round(modeA_avg, 3),
                       "c_lte_a": modeC_avg <= modeA_avg},
        "bench": bench_result,
    }
    (out_dir / f"persona_eval-{ts}-summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    sheet_path = None if args.gate_only else _write_distinctness_sheet(agent_rows, ts)

    print("\n" + "=" * 60, flush=True)
    print(f"DELEGATION GATE: {task_deleg}/{task_total} "
         f"{'PASS' if task_deleg == task_total else 'FAIL'}", flush=True)
    print(f"chat over-delegation (lilith): {chat_deleg}/{chat_total} "
         f"(target <=3)", flush=True)
    print(f"JOKE GATE (binding-ask, item 4): "
         f"{'PASS' if joke_gate_pass else 'FAIL'} -- {joke_answer[:80]!r}",
         flush=True)
    print(f"SELF-STATE GATE (item 5, 'is your telegram set up'): "
         f"{'PASS' if self_state_gate_pass else 'FAIL'} "
         f"(delegated={self_state_row.get('delegated')!s})", flush=True)
    if args.gate_only:
        print(f"latency avg -- mode C (persona_first) chat: {modeC_avg:.2f}s  "
             f"(mode A baseline skipped -- --gate-only)", flush=True)
        print("bench: skipped -- --gate-only", flush=True)
    else:
        print(f"latency avg -- mode C (persona_first) chat: {modeC_avg:.2f}s  "
             f"mode A (persona_last) chat: {modeA_avg:.2f}s", flush=True)
        print(f"bench: {bench_result['passed']}/{bench_result['total']}", flush=True)
    print(f"distinctness sheet: {sheet_path}", flush=True)
    print(f"summary: {out_dir}", flush=True)

    return 0 if gate_pass else 1


if __name__ == "__main__":
    rc = main()
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(rc)
