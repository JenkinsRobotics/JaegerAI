#!/usr/bin/env python3
"""Render a full benchmark transcript: the exact system prompt + every case's
question / tools / skills / response / pass, from a results run.

Usage:
    python dev/benchmark/make_transcript.py                 # latest E4B run
    python dev/benchmark/make_transcript.py <rows.jsonl>    # a specific run
    python dev/benchmark/make_transcript.py --out FILE      # write elsewhere

Default output: dev/benchmark/last_run_transcript.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
DEFAULT_OUT = HERE / "last_run_transcript.md"


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


def render(rows_path: Path) -> str:
    rows = [json.loads(l) for l in rows_path.read_text().splitlines() if l.strip()]
    run_id = rows_path.parent.name
    model = rows_path.parent.parent.name
    passed = sum(1 for r in rows if r.get("case_pass"))

    lines: list[str] = []
    lines.append("# SYSTEM PROMPT (sent verbatim before EVERY question below)\n")
    lines.append(_system_prompt())
    lines.append("\n\n# PER-CASE TRANSCRIPT (question / tools / skills / response)")
    lines.append(f"# {model} — {len(rows)} cases (run {run_id}) — {passed}/{len(rows)} passed\n")
    lines.append("For each case: QUESTION sent, TOOLS chosen in order, any SKILLS "
                 "loaded, the RESPONSE, and PASS/FAIL + tokens/latency.\n")

    for i, r in enumerate(rows):
        verdict = "PASS" if r.get("case_pass") else "FAIL"
        tags = ",".join(r.get("tags", []))
        lines.append(f"## [{i:02d}] {r['id']}  ({verdict})   tags={tags}")
        lines.append(f"QUESTION:  {r.get('prompt','')}")
        lines.append(f"TOOLS →    {_fmt_tools(r.get('tools_called', []))}")
        if r.get("skills_viewed"):
            lines.append(f"SKILLS →   {r['skills_viewed']}")
        lines.append(f"RESPONSE:  {r.get('answer','')}")
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
