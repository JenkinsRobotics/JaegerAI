#!/usr/bin/env python3
"""End-to-end coding battery: real models, real tools, through a real Gateway.

Each task seeds a scratch project, sends ONE prompt through the same
``POST /v1/sessions/{id}/turns`` path the IDE uses, and then grades the result with
an independent verifier that this script runs itself. A model saying "done" counts
for nothing; only the verifier's exit status does.

    gateway_battery.py --gateway http://127.0.0.1:18810 --models kimi-k2.7-code:cloud
    gateway_battery.py --models kimi-k2.7-code:cloud,glm-5.3:cloud --tasks bugfix_slug,interactive_pty

Point it at a scratch Gateway with ``--auto-approve`` (see ``dev/scripts/gateway_turn.py``);
never at the operator's live Gateway. Results go to ``~/.jaeger/verification/``,
outside the repository.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gateway_turn import run_turn  # noqa: E402

BENCH_ROOT = Path("/tmp/jg_bench")
RESULTS = Path.home() / ".jaeger" / "verification" / "gateway-battery"


@dataclass
class Task:
    id: str
    prompt: str
    seed: dict[str, str]
    verify: str                      # shell, run in the workspace; exit 0 = pass
    hidden: dict[str, str] = field(default_factory=dict)  # written only at verify time
    timeout: int = 360


def _port_closed(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


TASKS: list[Task] = [
    Task(
        id="bugfix_slug",
        prompt=("test_slug.py has failing tests for slugify() in slug.py. Fix slug.py so every test passes "
                "without editing the tests. Plan first with update_plan, then run the tests with "
                "exec_command (python3 -m unittest -q) and report the result."),
        seed={
            "slug.py": 'def slugify(text):\n    return text.lower().replace(" ", "-")\n',
            "test_slug.py": (
                "import unittest\nfrom slug import slugify\n\n\nclass T(unittest.TestCase):\n"
                "    def test_basic(self):\n        self.assertEqual(slugify('Hello, World!'), 'hello-world')\n"
                "    def test_ws(self):\n        self.assertEqual(slugify('  Multiple   spaces '), 'multiple-spaces')\n"
                "    def test_accents(self):\n        self.assertEqual(slugify('Café au lait'), 'cafe-au-lait')\n"
                "    def test_empty(self):\n        self.assertEqual(slugify(''), '')\n"
            ),
        },
        verify="python3 -m unittest -q test_slug 2>&1",
    ),
    Task(
        id="multi_file_rename",
        prompt=("Rename the function get_user_name to display_name everywhere in this project (definition, all "
                "callers and the tests) and keep behaviour identical. "
                "Afterwards run the tests with exec_command."),
        seed={
            "users.py": 'def get_user_name(user):\n    return f"{user[\'first\']} {user[\'last\']}"\n',
            "report.py": ("from users import get_user_name\n\n\ndef line(user):\n"
                          "    return get_user_name(user).upper()\n"),
            "cli.py": ("from users import get_user_name\nfrom report import line\n\n\ndef main(user):\n"
                       "    return get_user_name(user) + ' | ' + line(user)\n"),
            "test_all.py": ("import unittest\nfrom users import get_user_name\nfrom report import line\nfrom cli import main\n\n"
                            "U = {'first': 'Ada', 'last': 'Lovelace'}\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_name(self):\n        self.assertEqual(get_user_name(U), 'Ada Lovelace')\n"
                            "    def test_line(self):\n        self.assertEqual(line(U), 'ADA LOVELACE')\n"
                            "    def test_main(self):\n        self.assertEqual(main(U), 'Ada Lovelace | ADA LOVELACE')\n"),
        },
        # No old name left, the new one defined, the three tests still present
        # (deleting tests must not count as passing), and they pass.
        verify=("! grep -rn get_user_name --include='*.py' . && grep -q 'def display_name' users.py "
                "&& test \"$(grep -c 'def test_' test_all.py)\" -ge 3 && python3 -m unittest -q test_all 2>&1"),
    ),
    Task(
        id="implement_roman",
        prompt=("Create roman.py with to_roman(n) and from_roman(s) for integers 1..3999 using standard subtractive "
                "notation. to_roman must raise ValueError outside 1..3999; from_roman must raise ValueError for "
                "malformed numerals (e.g. 'IIII', 'VX', 'ABC', ''). The two must round-trip. Verify your work by "
                "actually running code, and finish with a one-line summary."),
        seed={"README.md": "Roman numeral helper — see task.\n"},
        hidden={"check_roman.py": (
            "import sys\nfrom roman import to_roman, from_roman\n"
            "cases={1:'I',4:'IV',9:'IX',14:'XIV',40:'XL',90:'XC',400:'CD',1994:'MCMXCIV',2024:'MMXXIV',3999:'MMMCMXCIX'}\n"
            "for n,s in cases.items():\n    assert to_roman(n)==s,(n,to_roman(n))\n    assert from_roman(s)==n,(s,)\n"
            "assert all(from_roman(to_roman(n))==n for n in range(1,4000))\n"
            "for bad in (0,4000,-5):\n    try: to_roman(bad)\n    except ValueError: pass\n    else: sys.exit('no error for %r'%bad)\n"
            "for bad in ('IIII','VX','ABC','','IC','MMMM'):\n    try: from_roman(bad)\n    except ValueError: pass\n"
            "    else: sys.exit('no error for %r'%bad)\nprint('roman ok')\n")},
        verify="python3 check_roman.py 2>&1",
    ),
    Task(
        id="interactive_pty",
        prompt=("quiz.py is interactive: it asks two questions on the terminal. Run it interactively and answer "
                "'Ada' for the name and '21' for the number (do not edit quiz.py and do not pipe input — type the "
                "answers when asked). Then tell me what it printed."),
        seed={"quiz.py": (
            "name = input('Name? ')\nnumber = int(input('Favourite number? '))\n"
            "line = f'Hello {name}, double is {number * 2}'\nprint(line)\n"
            "open('answer.txt', 'w').write(line)\n")},
        verify="test \"$(cat answer.txt 2>/dev/null)\" = 'Hello Ada, double is 42'",
    ),
    Task(
        id="background_server",
        prompt=("Start a web server serving this directory on port 8931 with exec_command "
                "(python3 -m http.server 8931 --bind 127.0.0.1) and leave it running while you fetch "
                "http://127.0.0.1:8931/hello.txt with curl. Save exactly what you fetched into fetched.txt. "
                "Then stop the server (kill_command) so port 8931 is free again."),
        seed={"hello.txt": "hi from server\n"},
        verify="test \"$(cat fetched.txt 2>/dev/null)\" = 'hi from server'",
    ),
    Task(
        id="debug_two_bugs",
        prompt=("The tests in test_stats.py fail. Find and fix the bugs in stats.py without changing the tests. "
                "Run the tests to confirm and tell me what was wrong."),
        seed={
            "stats.py": (
                "def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n\n\n"
                "def median(xs):\n    s = sorted(xs)\n    n = len(s)\n    return s[n // 2]\n"),
            "test_stats.py": (
                "import unittest\nfrom stats import mean, median\n\n\nclass T(unittest.TestCase):\n"
                "    def test_mean(self):\n        self.assertAlmostEqual(mean([1, 2, 3, 4]), 2.5)\n"
                "    def test_median_odd(self):\n        self.assertEqual(median([5, 1, 3]), 3)\n"
                "    def test_median_even(self):\n        self.assertEqual(median([4, 1, 3, 2]), 2.5)\n"),
        },
        verify="python3 -m unittest -q test_stats 2>&1",
    ),
    Task(
        id="csv_summary",
        prompt=("sales.csv has columns region,units,price. Write summary.json containing an object mapping each "
                "region to its total revenue (sum of units*price, rounded to 2 decimals), plus a key "
                "\"grand_total\" with the overall revenue. Use code to compute it; don't do arithmetic by hand."),
        seed={"sales.csv": ("region,units,price\nnorth,10,2.50\nsouth,4,10.00\nnorth,3,7.25\nwest,8,1.10\n"
                            "south,2,3.333\nwest,1,99.99\n")},
        verify=("python3 - <<'EOF'\nimport json,sys\nd=json.load(open('summary.json'))\n"
                "exp={'north':46.75,'south':46.67,'west':108.79,'grand_total':202.21}\n"
                "sys.exit(0 if all(abs(d.get(k,-1)-v)<0.011 for k,v in exp.items()) else 1)\nEOF"),
    ),
]


def prepare(model: str, task: Task) -> Path:
    workspace = BENCH_ROOT / model.replace(":", "_").replace("/", "_") / task.id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for name, body in task.seed.items():
        (workspace / name).write_text(body, encoding="utf-8")
    return workspace


def grade(task: Task, workspace: Path) -> tuple[bool, str]:
    for name, body in task.hidden.items():
        (workspace / name).write_text(body, encoding="utf-8")
    try:
        done = subprocess.run(["bash", "-c", task.verify], cwd=workspace, capture_output=True,
                              text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return False, "verifier timed out"
    ok = done.returncode == 0
    if task.id == "background_server":
        ok = ok and _port_closed(8931)
        if not _port_closed(8931):
            return False, "server still listening on 8931"
    return ok, (done.stdout + done.stderr).strip()[-300:]


def run_one(gateway: str, model: str, provider: str, task: Task, auto_approve: bool) -> dict:
    workspace = prepare(model, task)
    started = time.time()
    try:
        turn = run_turn(gateway, task.prompt, str(workspace), model=model, provider=provider,
                        timeout=task.timeout, auto_approve=auto_approve)
        error = ""
    except Exception as exc:  # noqa: BLE001 — a crashed run is a failed run, recorded
        turn, error = {"terminal": None, "status": None, "tools": [], "plans": [], "answer": ""}, repr(exc)
    passed, detail = grade(task, workspace)
    return {"model": model, "task": task.id, "passed": passed, "verifier": detail,
            "terminal": turn["terminal"], "status": turn["status"],
            "seconds": round(time.time() - started, 1), "tools": turn["tools"],
            "plan_updates": len(turn["plans"]), "error": error,
            "answer": (turn.get("answer") or "")[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:18810")
    ap.add_argument("--models", required=True, help="comma-separated model ids (as the Gateway takes them)")
    ap.add_argument("--provider", default="")
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    ap.add_argument("--auto-approve", action="store_true")
    args = ap.parse_args()
    wanted = {t for t in args.tasks.split(",") if t}
    tasks = [t for t in TASKS if not wanted or t.id in wanted]
    rows = []
    for model in [m for m in args.models.split(",") if m]:
        for task in tasks:
            row = run_one(args.gateway, model, args.provider, task, args.auto_approve)
            rows.append(row)
            print(f"{'PASS' if row['passed'] else 'FAIL'}  {model:32} {task.id:20} {row['seconds']:6}s  "
                  f"{len(row['tools'])} tool calls  {row['plan_updates']} plan updates"
                  + (f"  [{row['error'] or row['verifier'][:80]}]" if not row["passed"] else ""), flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"battery-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(rows, indent=2))
    print("\nper model:")
    for model in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == model]
        wins = sum(r["passed"] for r in mine)
        print(f"  {model:32} {wins}/{len(mine)} passed  median {statistics.median(r['seconds'] for r in mine):.0f}s")
    print(f"\nresults: {out}")
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
