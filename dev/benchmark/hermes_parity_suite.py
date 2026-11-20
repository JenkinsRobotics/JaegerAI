#!/usr/bin/env python3
"""Phase 2 Part 3 — Reproducible 15-Task Hermes Parity Benchmark Suite.

Defines 15 representative tasks across the required capability matrix:
  1. coding_bugfix            (coding & debugging)
  2. multi_file_refactor      (multi-file autonomous edit)
  3. file_management          (file organization & verification)
  4. settings_modification    (authorized Jaeger setting write + verify)
  5. session_management       (list, archive, delete explicit disposable sessions)
  6. memory_persistence       (epistemic claim + evidence + restart survival)
  7. contradiction_resolution (detect conflict + verify + retract error)
  8. background_execution     (detached server/job + concurrent verification)
  9. scheduling_cron          (schedule creation & persistence verification)
 10. specialist_delegation    (granted delegate without redundant approval)
 11. skill_learning           (author + smoke-verify a reusable SKILL.md)
 12. failure_recovery         (recover from failing command/patch and succeed)
 13. tool_reliability_pty     (interactive PTY stdin/stdout task)
 14. browser_automation       (headless local HTML DOM interaction)
 15. multi_step_planning      (plan -> compute -> verify JSON artifact)

Each task records:
- verified_pass (independent deterministic verifier, never self-reported)
- approval_friction (unexpected approval prompts under Full Auto)
- elapsed_s, tool_calls, recovery_events, error

Usage:
    python3 dev/benchmark/hermes_parity_suite.py --list
    python3 dev/benchmark/hermes_parity_suite.py --mode deterministic
    python3 dev/benchmark/hermes_parity_suite.py --mode gateway --gateway http://127.0.0.1:18819 --model mistral-large-4:cloud
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParityTask:
    id: str
    category: str
    description: str
    prompt: str
    jaeger_surface: str
    hermes_comparable: bool = True
    seed: dict[str, str] = field(default_factory=dict)
    verify_cmd: str = ""
    notes: str = ""


TASKS: list[ParityTask] = [
    ParityTask(
        id="01_coding_bugfix",
        category="coding_and_debugging",
        description="Fix slugify() without modifying test_slug.py and verify unit tests pass.",
        prompt="Fix slugify() in slug.py so all tests in test_slug.py pass without editing test_slug.py. Run python3 -m unittest -q.",
        jaeger_surface="gateway_battery:bugfix_slug",
        seed={
            "slug.py": 'def slugify(text):\n    return text.lower().replace(" ", "-")\n',
            "test_slug.py": (
                "import unittest\nfrom slug import slugify\n\nclass T(unittest.TestCase):\n"
                "    def test_all(self):\n"
                "        self.assertEqual(slugify('Hello, World!'), 'hello-world')\n"
                "        self.assertEqual(slugify('  Multiple   spaces '), 'multiple-spaces')\n"
                "        self.assertEqual(slugify('Café au lait'), 'cafe-au-lait')\n"
            ),
        },
        verify_cmd="python3 -m unittest -q test_slug",
    ),
    ParityTask(
        id="02_multi_file_refactor",
        category="multi_file_planning",
        description="Rename get_user_name -> display_name across 4 files and verify tests.",
        prompt="Rename get_user_name to display_name across users.py, report.py, cli.py, and test_all.py, then run python3 -m unittest -q.",
        jaeger_surface="gateway_battery:multi_file_rename",
        verify_cmd="! grep -rn get_user_name --include='*.py' . && python3 -m unittest -q test_all",
    ),
    ParityTask(
        id="03_file_management",
        category="file_management",
        description="Organize unsorted scratch files into typed folders without data loss.",
        prompt="Move *.csv files into data/ and *.md files into docs/ preserving contents, and write manifest.json listing counts.",
        jaeger_surface="tools:files+exec_command",
        seed={"a.csv": "x,y\n1,2\n", "notes.md": "# Notes\n"},
        verify_cmd="test -f data/a.csv && test -f docs/notes.md && test -f manifest.json",
    ),
    ParityTask(
        id="04_settings_modification",
        category="settings_modification",
        description="Modify an authorized Jaeger setting in Full Auto with zero approval friction and verify disk persistence.",
        prompt="Set model.ctx to 32768 using settings_set and confirm the saved value with settings_get.",
        jaeger_surface="tools:settings_set+settings_get",
    ),
    ParityTask(
        id="05_session_management",
        category="session_management",
        description="Archive and delete explicitly selected disposable test sessions in Full Auto and verify 404 readback.",
        prompt="Archive session disp-a, then delete disp-a and disp-b while preserving keep-c, and verify.",
        jaeger_surface="tools:session_manage+session_search",
    ),
    ParityTask(
        id="06_memory_persistence",
        category="memory_persistence",
        description="Persist Truth identity, verified claim + evidence, and human goal across controlled Gateway restart.",
        prompt="Record a verified claim with evidence, restart the runtime, and confirm exact recall without fabrication.",
        jaeger_surface="core/world+core/entity",
    ),
    ParityTask(
        id="07_contradiction_resolution",
        category="epistemic_verification",
        description="Detect conflicting hypothesis vs observation, verify empirical truth, and retract disproven claim.",
        prompt="Inspect contradictions for actuator failure_cause, verify the observed cause with test evidence, and retract the hypothesis.",
        jaeger_surface="core/world:find_contradictions+verify_claim",
        hermes_comparable=False,
        notes="Jaeger-specific epistemic differentiator; Hermes has flat MEMORY.md without contradiction tracking.",
    ),
    ParityTask(
        id="08_background_execution",
        category="background_execution",
        description="Run a background HTTP server while fetching from it, save output, then cleanly stop the process.",
        prompt="Start python3 -m http.server 8931, curl /hello.txt into fetched.txt, then stop the server.",
        jaeger_surface="gateway_battery:background_server",
        verify_cmd="test \"$(cat fetched.txt 2>/dev/null)\" = 'hi from server'",
    ),
    ParityTask(
        id="09_scheduling_cron",
        category="scheduling",
        description="Create, persist, list, and cancel a scheduled job in isolated state.",
        prompt="Schedule a daily check job, verify it appears in schedules, then cancel it cleanly.",
        jaeger_surface="jaeger_agent.background.cron_runner",
    ),
    ParityTask(
        id="10_specialist_delegation",
        category="delegation",
        description="Delegate to an owner-granted framework under Full Auto with 0 redundant approvals while blocking ungranted frameworks.",
        prompt="Verify granted delegate executes cleanly in Full Auto while ungranted framework is denied.",
        jaeger_surface="core/authority/kernel+core/frameworks/grants",
    ),
    ParityTask(
        id="11_skill_learning",
        category="skill_learning",
        description="Create a valid SKILL.md procedure and verify skill_loader discovers and validates it.",
        prompt="Create a minimal SKILL.md in instance skills and confirm discovery and win-rate tracking.",
        jaeger_surface="jaeger_agent.skill_registry+skill_improvement",
    ),
    ParityTask(
        id="12_failure_recovery",
        category="failure_recovery",
        description="Recover cleanly from a failed patch/command without losing completed work or stalling.",
        prompt="Fix two independent bugs in stats.py where initial test run fails, then confirm all tests pass.",
        jaeger_surface="gateway_battery:debug_two_bugs",
        verify_cmd="python3 -m unittest -q test_stats",
    ),
    ParityTask(
        id="13_tool_reliability_pty",
        category="tool_reliability",
        description="Drive an interactive PTY script answering prompts without piping.",
        prompt="Run quiz.py interactively, answer 'Ada' and '21', and verify answer.txt.",
        jaeger_surface="gateway_battery:interactive_pty",
        verify_cmd="test \"$(cat answer.txt 2>/dev/null)\" = 'Hello Ada, double is 42'",
    ),
    ParityTask(
        id="14_browser_automation",
        category="browser_automation",
        description="Navigate a local HTML fixture via Playwright browser tool and extract interactive elements.",
        prompt="Open local fixture HTML in headless browser, inspect snapshot elements, and verify title/button.",
        jaeger_surface="jaeger_agent.tools.browser",
    ),
    ParityTask(
        id="15_desktop_computer_use_boundary",
        category="desktop_application_interaction",
        description="Evaluate desktop computer-use capability and report exact operational vs blocked state.",
        prompt="Probe desktop automation readiness (CuaDriver / Accessibility / system_control) honestly.",
        jaeger_surface="features/app_control+features/droid+tools/system_control",
        notes="Currently blocked in app_control/service.py (403 CuaDriver invoke disabled); tracked as P1 gap.",
    ),
]


def run_deterministic_baseline() -> dict[str, Any]:
    """Run deterministic hermetic checks across Jaeger's core non-LLM subsystems + Gate A."""
    import os
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
    from jaeger_ai.core.frameworks.grants import FrameworkGrants
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, dump_yaml
    from jaeger_ai.core.settings.tools import settings_get, settings_set
    from jaeger_ai.core.world.model import EpistemicProvenance
    from jaeger_ai.core.world.store import SqliteWorldStore
    import yaml

    rows: list[dict[str, Any]] = []

    def record(task_id: str, passed: bool, elapsed_s: float, friction: int = 0, detail: str = "") -> None:
        rows.append({
            "task_id": task_id,
            "verified_pass": passed,
            "approval_friction": friction,
            "elapsed_s": round(elapsed_s, 3),
            "detail": detail,
        })

    with tempfile.TemporaryDirectory(prefix="jg_parity_") as td:
        root = Path(td)
        old_state = os.environ.get("JAEGER_STATE_DIR")
        os.environ["JAEGER_STATE_DIR"] = str(root)
        try:
            inst = root / "instances" / "jaeger"
            layout = InstanceLayout(root=inst)
            layout.ensure_dirs()
            cfg = Config(instance_name="jaeger", model={"model_path": "unconfigured"})
            cfg.automation.autonomy = "auto"
            dump_yaml(layout.config_path, cfg)
            (inst / "authority_policy.yaml").write_text(
                yaml.safe_dump({"shell": {"risk_mode": "confirm"}, "filesystem": {"write": True}}),
                encoding="utf-8",
            )

            # 04 settings_modification
            t0 = time.perf_counter()
            dec = PolicyKernel().evaluate(
                ProposedAction(tool_name="settings_set", arguments={"path": "model.ctx", "value": 32768}, actor="owner:webui"),
                instance_root=inst, dry_run=True,
            )
            res = settings_set(layout, "model.ctx", 32768)
            ok = dec.decision == AuthorityDecisionType.ALLOW and res.get("ok") is True and settings_get(layout, "model.ctx")["setting"]["current"] == 32768
            record("04_settings_modification", ok, time.perf_counter() - t0, 0 if dec.decision == AuthorityDecisionType.ALLOW else 1, "settings_set verified")

            # 06 memory_persistence + 07 contradiction_resolution
            t0 = time.perf_counter()
            ws = SqliteWorldStore(root / "knowledge.sqlite3")
            c1 = ws.record_claim("sys", "temp", "62C", EpistemicProvenance.OBSERVED)
            c2 = ws.record_claim("sys", "temp", "45C", EpistemicProvenance.HYPOTHESIS)
            ctrs = ws.find_contradictions()
            ws.verify_claim(c1.claim_id, source_type="sensor", source_id="therm1", snippet="62C")
            rev2 = ws.claim_detail(c2.claim_id)["revision"]
            ws.manage_claim(c2.claim_id, "forget", expected_revision=rev2, operation_id="parity-op-1", actor="owner:cli")
            reopened = SqliteWorldStore(root / "knowledge.sqlite3")
            det1 = reopened.claim_detail(c1.claim_id)
            record("06_memory_persistence", det1["provenance"] == "verified" and len(det1["evidence"]) == 1, time.perf_counter() - t0, 0, "reopened SQLite verified")
            record("07_contradiction_resolution", len(ctrs) == 1 and reopened.find_contradictions() == [], time.perf_counter() - t0, 0, "1 detected -> 0 after retract")

            # 10 specialist_delegation
            t0 = time.perf_counter()
            FrameworkGrants().set("codex", "delegate", True, by="owner:webui")
            d_ok = PolicyKernel().evaluate(
                ProposedAction(tool_name="framework_delegate", arguments={"framework": "codex"}, actor="owner:webui"),
                instance_root=inst, dry_run=True,
            )
            d_deny = PolicyKernel().evaluate(
                ProposedAction(tool_name="framework_delegate", arguments={"framework": "other"}, actor="owner:webui"),
                instance_root=inst, dry_run=True,
            )
            record(
                "10_specialist_delegation",
                d_ok.decision == AuthorityDecisionType.ALLOW and d_deny.decision == AuthorityDecisionType.DENY,
                time.perf_counter() - t0,
                0 if d_ok.decision == AuthorityDecisionType.ALLOW else 1,
                "granted=ALLOW, ungranted=DENY",
            )

            # 15 desktop_computer_use_boundary
            t0 = time.perf_counter()
            from jaeger_agent.skills.macos_computer_v1 import computer_look, computer_use
            apps_res = computer_use("list_apps")
            apps_list = (apps_res.get("result") or {}).get("apps") or []
            shot_path = str(Path(td) / "parity_screen.png")
            shot_res = computer_use("screenshot", path=shot_path)
            shot_ok = bool(shot_res.get("ok")) and Path(shot_path).exists() and Path(shot_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            d_owner_cu = PolicyKernel().evaluate(
                ProposedAction(tool_name="computer_do", arguments={"goal": "inspect"}, actor="owner:webui", tier="external_effect"),
                instance_root=inst, dry_run=True,
            )
            d_ext_cu = PolicyKernel().evaluate(
                ProposedAction(tool_name="computer_do", arguments={"goal": "inspect"}, actor="mcp:remote", tier="external_effect"),
                instance_root=inst, dry_run=True,
            )
            desktop_ok = (
                bool(apps_res.get("ok"))
                and any(a.get("name") == "Finder" for a in apps_list)
                and shot_ok
                and d_owner_cu.decision == AuthorityDecisionType.ALLOW
                and d_ext_cu.decision == AuthorityDecisionType.DENY
            )
            record(
                "15_desktop_computer_use_boundary",
                desktop_ok,
                time.perf_counter() - t0,
                0 if d_owner_cu.decision == AuthorityDecisionType.ALLOW else 1,
                f"native macos_computer_v1 apps={len(apps_list)} screenshot_ok={shot_ok} owner=ALLOW external=DENY (CuaDriver app_control invoke stays 403)",
            )
        finally:
            if old_state is None:
                os.environ.pop("JAEGER_STATE_DIR", None)
            else:
                os.environ["JAEGER_STATE_DIR"] = old_state

    passed = sum(1 for r in rows if r["verified_pass"])
    return {
        "suite": "hermes_parity_suite_v1",
        "total_defined_tasks": len(TASKS),
        "deterministic_checked": len(rows),
        "deterministic_passed": passed,
        "total_approval_friction": sum(r["approval_friction"] for r in rows),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="List all 15 benchmark tasks")
    ap.add_argument("--mode", choices=("list", "deterministic"), default="deterministic")
    args = ap.parse_args()
    if args.list or args.mode == "list":
        print(json.dumps([asdict(t) for t in TASKS], indent=2))
        return 0
    out = run_deterministic_baseline()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
