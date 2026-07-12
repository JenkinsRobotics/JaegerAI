#!/usr/bin/env python3
"""Render a full benchmark transcript for a run: the exact system prompt, then
per case — what we SENT, what the agent DID (process + execution), what we
EXPECTED, and the OUTCOME (pass/fail + which check failed).

Usage:
    python dev/benchmark/make_transcript.py                 # latest E4B run
    python dev/benchmark/make_transcript.py <rows.jsonl>    # a specific run
    python dev/benchmark/make_transcript.py --out FILE      # write elsewhere

bench.py also calls render() to drop a transcript.md into each run's results dir.
Default standalone output: dev/benchmark/last_run_transcript.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
DEFAULT_OUT = HERE / "last_run_transcript.md"

# The scoring flags a row carries, in report order, with a human label.
_CHECKS = [
    ("routing_ok", "routing"),      # right tools called
    ("ordered_ok", "order"),        # right tools in order
    ("answer_ok", "answer"),        # answer_contains matched
    ("no_hallucination", "no-halluc"),
    ("safety_ok", "safety"),        # no forbidden tool / refused
    ("skill_ok", "skill"),          # right playbook pulled
]


def _cases_by_id() -> dict:
    """Map case id -> BenchCase so we can print EXPECTED. Empty on any import
    trouble (transcript still renders, just without the expected column)."""
    try:
        from jaeger_os.core.bench.cases import CASES
        return {c.id: c for c in CASES}
    except Exception:  # pragma: no cover
        return {}


def _latest_rows() -> Path:
    rows = sorted(RESULTS.glob("*/*/*-rows.jsonl"), key=lambda p: p.stat().st_mtime)
    if not rows:
        sys.exit("no results found under dev/benchmark/results/")
    return rows[-1]


def _system_prompt() -> str:
    """The assembled agent prompt, verbatim — exactly what the LLM gets."""
    try:
        out = subprocess.run(
            ["jaeger", "prompt"], capture_output=True, text=True, timeout=60
        )
        return out.stdout or out.stderr
    except Exception as e:  # pragma: no cover
        return f"(could not render system prompt: {e})"


def _fmt_tools(tools: list[str]) -> str:
    return " -> ".join(tools) if tools else "(none)"


def _tool_schema() -> str:
    """The `tools=` payload the model gets every turn, alongside the prompt:
    each tool's name + description + params, and use_skill's skill-name enum.
    This is the OTHER half of 'what we send' — the prompt is the first half."""
    try:
        import jaeger_os.agent.tools  # noqa: F401 — registers tools on import
        from jaeger_os.core.tools.tool_registry import get_tools
        tools = sorted(get_tools(), key=lambda t: t.name)
    except Exception as e:  # pragma: no cover
        return f"(could not render tool schema: {e})"

    lines = [f"{len(tools)} tools in the `tools=` field. Each: name — description "
             "[params]. use_skill's description is shown IN FULL below (its "
             "name→description skill catalog); every other description is clipped "
             "to ~110 chars for scanning.\n"]
    skill_enum: list[str] = []
    use_skill_desc = ""
    for t in tools:
        try:
            props = t.args_model.model_json_schema().get("properties", {})
        except Exception:
            props = {}
        params = list(props.keys())
        full = " ".join((t.description or "").split())
        if t.name == "use_skill":
            skill_enum = props.get("name", {}).get("enum", []) or []
            use_skill_desc = t.description or ""   # keep newlines for the catalog
            lines.append(f"- {t.name}({', '.join(params)}) — [full description shown below]")
        else:
            lines.append(f"- {t.name}({', '.join(params)}) — {full[:110]}")
    if skill_enum:
        lines.append(f"\nuse_skill: the `name` param is an ENUM of {len(skill_enum)} "
                     "skill names (enums can't carry per-value blurbs), and its "
                     "DESCRIPTION carries the name→description catalog — shown here "
                     "in full, exactly as the model receives it:")
        lines.append("\n" + use_skill_desc)
    return "\n".join(lines)


def _expected(case) -> str:
    """One-line EXPECTED spec from the case definition."""
    if case is None:
        return "(case definition unavailable)"
    bits: list[str] = []
    et = getattr(case, "expected_tools", None)
    if et:
        bits.append(f"tools={et}" + (" (ordered)" if getattr(case, "ordered", False) else ""))
    es = getattr(case, "expected_skills", None)
    if es:
        bits.append(f"skills={es}")
    aa = getattr(case, "answer_contains_any", None)
    if aa:
        bits.append(f"answer∈{aa}")
    al = getattr(case, "answer_contains_all", None)
    if al:
        bits.append(f"answer⊇{al}")
    ft = getattr(case, "forbidden_tools", None)
    if ft:
        bits.append(f"MUST-NOT-call={ft}")
    return "  ·  ".join(bits) or "(refusal / no-tool expected)"


def _failed_on(row: dict) -> str:
    """Which scoring checks the row failed (False), as a short list."""
    failed = [label for key, label in _CHECKS if row.get(key) is False]
    return ", ".join(failed) if failed else "—"


def render(rows_path: Path) -> str:
    rows = [json.loads(l) for l in rows_path.read_text().splitlines() if l.strip()]
    cases = _cases_by_id()
    run_id = rows_path.parent.name
    model = rows_path.parent.parent.name
    passed = sum(1 for r in rows if r.get("case_pass"))

    lines: list[str] = []
    lines.append("# SYSTEM PROMPT (sent verbatim before EVERY question below)\n")
    lines.append(_system_prompt())
    lines.append("\n\n# TOOL + SKILL SCHEMA (the `tools=` payload, sent every turn with the prompt)\n")
    lines.append(_tool_schema())
    lines.append("\n\n# PER-CASE TRANSCRIPT — sent / process / expected / outcome")
    lines.append(f"# {model} — {len(rows)} cases (run {run_id}) — {passed}/{len(rows)} passed\n")
    lines.append("Per case: QUESTION (what we send) · TOOLS/SKILLS + RESPONSE (agent "
                 "process & execution) · EXPECTED (what we score as correct) · "
                 "OUTCOME (pass/fail + which check failed).\n")

    # Failures first-glance index so a run is scannable at the top.
    fails = [r for r in rows if not r.get("case_pass")]
    if fails:
        lines.append(f"FAILURES ({len(fails)}): "
                     + ", ".join(f"{r['id']} [{_failed_on(r)}]" for r in fails) + "\n")

    for i, r in enumerate(rows):
        verdict = "PASS" if r.get("case_pass") else "FAIL"
        tags = ",".join(r.get("tags", []))
        lines.append(f"## [{i:02d}] {r['id']}  ({verdict})   tags={tags}")
        lines.append(f"QUESTION:  {r.get('prompt','')}")
        lines.append(f"EXPECTED:  {_expected(cases.get(r['id']))}")
        lines.append(f"TOOLS →    {_fmt_tools(r.get('tools_called', []))}")
        if r.get("skills_viewed"):
            lines.append(f"SKILLS →   {r['skills_viewed']}")
        lines.append(f"RESPONSE:  {r.get('answer','')}")
        if verdict == "FAIL":
            lines.append(f"FAILED-ON: {_failed_on(r)}")
        meta = (f"           [{r.get('elapsed_s',0):.1f}s · "
                f"in {r.get('prompt_tokens',0)} / out {r.get('completion_tokens',0)} tok · "
                f"{r.get('iterations',0)} iter]")
        lines.append(meta)
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    out = DEFAULT_OUT
    if "--out" in args:
        idx = args.index("--out")
        out = Path(args[idx + 1])
        args = args[:idx] + args[idx + 2:]
    rows_path = Path(args[0]) if args else _latest_rows()
    out.write_text(render(rows_path))
    print(f"wrote {out}  (from {rows_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
