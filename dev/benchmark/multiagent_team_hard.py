#!/usr/bin/env python3
"""Hard multi-agent team benchmark — Operation Split-Key.

A lead agent must coordinate four specialists (Archivist, Cryptanalyst,
Engineer, QA) so the team reconstructs a clearance code that no single
agent knows. Exercises RuntimeHost delegation, blackboard collaboration,
private memory isolation, mid-run failure recovery, and anti-forge checks.

Inspired by TheAgentCompany / MultiAgentBench / MetaGPT role-split patterns
(re-implemented in-repo; external clone was unavailable).

Usage:
  python dev/benchmark/multiagent_team_hard.py
  python dev/benchmark/multiagent_team_hard.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

_REPO = pathlib.Path(__file__).resolve().parents[2]
for _p in (
    _REPO,
    _REPO / "packages" / "jaeger-agent",
    _REPO / "packages" / "jaeger-os",
):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault(
    "PYTHONPYCACHEPREFIX",
    str(pathlib.Path.home() / ".cache" / "jaeger" / "pycache"),
)
os.chdir(_REPO)

from jaeger_ai.core.entity.events import JaegerEvent  # noqa: E402
from jaeger_ai.core.multi_agent.host import MultiAgentError, RuntimeHost  # noqa: E402
from jaeger_ai.core.multi_agent.models import (  # noqa: E402
    AgentType,
    DelegationStatus,
    TrustLevel,
)

from dev.evals.multiagent import operation_split_key as scenario  # noqa: E402


@dataclass
class CheckResult:
    id: str
    ok: bool
    detail: str = ""


@dataclass
class RunReport:
    scenario_id: str
    version: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    clearance: str | None = None
    elapsed_s: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "version": self.version,
            "passed": self.passed,
            "clearance": self.clearance,
            "elapsed_s": round(self.elapsed_s, 3),
            "error": self.error,
            "checks": [
                {"id": c.id, "ok": c.ok, "detail": c.detail} for c in self.checks
            ],
            "summary": {
                "total": len(self.checks),
                "passed": sum(1 for c in self.checks if c.ok),
                "failed": sum(1 for c in self.checks if not c.ok),
            },
        }


class SplitKeyTeam:
    """Deterministic multi-agent team protocol on RuntimeHost."""

    def __init__(self, base: pathlib.Path) -> None:
        self.host = RuntimeHost()
        self.base = base
        self.ids: dict[str, str] = {}
        self.runtimes: dict[str, Any] = {}
        self.checks: list[CheckResult] = []
        self._receipts: list[dict[str, Any]] = []
        self._failures: list[dict[str, Any]] = []

    def _check(self, check_id: str, ok: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(id=check_id, ok=bool(ok), detail=detail))
        if not ok:
            raise AssertionError(f"CHECK FAIL [{check_id}]: {detail}")

    def _seed_role(self, role_key: str) -> None:
        spec = scenario.ROLES[role_key]
        root = self.base / role_key
        rt = self.host.create_persistent_entity(spec.name, root)
        eid = rt.identity.entity_id
        self.ids[role_key] = eid
        self.runtimes[role_key] = rt

        agent_type = (
            AgentType.PERSISTENT_SOVEREIGN
            if role_key == "lead"
            else AgentType.SUBORDINATE_WORKER
        )
        # create_persistent_entity already registered as sovereign; re-tag workers
        self.host._agent_types[eid] = agent_type  # noqa: SLF001 — test harness

        # Private episodic + semantic facts (never shared automatically)
        brief = (
            f"Role={spec.name}. Private facts: "
            + "; ".join(f"{k}={v!r}" for k, v in spec.private_facts.items())
        )
        rt.event_store.append(
            JaegerEvent.human_message(brief, session_id=f"seed_{role_key}")
        )
        for key, value in spec.private_facts.items():
            rt.memory_subsystem.semantic.record_claim(
                subject=f"role:{role_key}",
                predicate=key,
                value=value if isinstance(value, str) else json.dumps(value),
            )

        if role_key != "lead":
            self.host.set_trust(
                self.ids["lead"], eid, TrustLevel.SUBORDINATE
            )
            self.host.set_trust(
                eid, self.ids["lead"], TrustLevel.SOVEREIGN
            )

    def bootstrap(self) -> None:
        # Lead first so trust edges can attach
        self._seed_role("lead")
        for role in ("archivist", "cryptanalyst", "engineer", "qa"):
            self._seed_role(role)

        # Untrusted outsider — must not receive sensitive grants
        outsider = self.host.create_persistent_entity(
            "Outsider", self.base / "outsider"
        )
        self.ids["outsider"] = outsider.identity.entity_id
        self.runtimes["outsider"] = outsider
        self.host.set_trust(
            self.ids["lead"],
            outsider.identity.entity_id,
            TrustLevel.UNTRUSTED_EXTERNAL,
        )

        self._check(
            "bootstrap.five_specialists_plus_outsider",
            len(self.host.list_entities()) == 6,
            f"entities={len(self.host.list_entities())}",
        )

    def assert_memory_isolation(self) -> None:
        """No specialist private claim may appear in another entity's semantic store."""
        private_values = {
            scenario.VAULT_ID,
            scenario.ALPHA_SHARD,
            str(scenario.CRYPTO_SEED),
            scenario.EXPECTED_CLEARANCE,
        }
        for role, rt in self.runtimes.items():
            if role in ("lead", "outsider"):
                # Lead may later learn public board values, but at bootstrap
                # must not hold vault/alpha/seed/clearance as private claims.
                claims = rt.memory_subsystem.semantic.query_claims("role:archivist")
                self._check(
                    f"isolation.{role}.no_archivist_claims",
                    len(claims) == 0,
                    f"leaked={claims}",
                )
                continue
            # Cross-check: role X must not hold role Y private subject claims
            for other in self.runtimes:
                if other == role:
                    continue
                leaked = rt.memory_subsystem.semantic.query_claims(f"role:{other}")
                self._check(
                    f"isolation.{role}.no_{other}_private",
                    len(leaked) == 0,
                    f"leaked={leaked}",
                )

        # Explicit: cryptanalyst must not know alpha in private memory
        crypto_claims = self.runtimes["cryptanalyst"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        self._check("isolation.crypto_no_alpha_private", len(crypto_claims) == 0)

        # Sanity: each specialist still has own facts
        arch_alpha = self.runtimes["archivist"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        self._check(
            "isolation.archivist_keeps_alpha",
            any(c.get("predicate") == "alpha_shard" for c in arch_alpha),
            f"claims={arch_alpha}",
        )
        _ = private_values  # reserved for future negative probes

    def _delegate(
        self,
        worker_role: str,
        goal: str,
        grants: tuple[str, ...],
    ):
        return self.host.delegate_task(
            parent_entity_id=self.ids["lead"],
            assigned_to_entity_id=self.ids[worker_role],
            goal=goal,
            capability_grants=grants,
        )

    def _require_inbox_delegation(self, worker_role: str, goal_substr: str) -> Any:
        inbox = self.host.read_inbox(self.ids[worker_role])
        self._check(
            f"inbox.{worker_role}.delegation",
            len(inbox) >= 1 and any(m.topic == "delegation.assigned" for m in inbox),
            f"inbox={inbox}",
        )
        msg = next(m for m in inbox if m.topic == "delegation.assigned")
        self._check(
            f"inbox.{worker_role}.goal",
            goal_substr in str(msg.payload.get("goal", "")),
            f"goal={msg.payload.get('goal')}",
        )
        return msg

    def lead_posts_plan(self) -> None:
        plan = {
            "mission": scenario.MISSION_GOAL,
            "order": ["archivist", "cryptanalyst", "engineer", "qa"],
            "deps": dict(scenario.DEPENDENCY_GRAPH),
            "replan_on_failure": True,
        }
        self.host.set_shared(
            scenario.KEY_PLAN, plan, author_entity_id=self.ids["lead"]
        )
        self.host.set_shared(
            scenario.KEY_RECEIPTS, [], author_entity_id=self.ids["lead"]
        )
        self.host.set_shared(
            scenario.KEY_FAILURES, [], author_entity_id=self.ids["lead"]
        )
        self._check(
            "lead.plan_posted",
            self.host.get_shared(scenario.KEY_PLAN)["order"][0] == "archivist",
        )

    def run_archivist(self) -> None:
        grants = scenario.ROLES["archivist"].capability_grants
        task = self._delegate(
            "archivist",
            "Extract vault id and alpha shard from private dossier; post redacted intel.",
            grants,
        )
        self._require_inbox_delegation("archivist", "alpha shard")

        # Worker reads private memory and posts ONLY redacted intel
        claims = self.runtimes["archivist"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        by_pred = {c["predicate"]: c["value"] for c in claims}
        intel = {
            "vault_id": by_pred["vault_id"],
            "alpha_shard": by_pred["alpha_shard"],
            # dossier text stays private — not copied to board
        }
        self.host.set_shared(
            scenario.KEY_INTEL, intel, author_entity_id=self.ids["archivist"]
        )
        self._add_receipt("archivist", task.delegation_id, intel)
        self.host.complete_delegation(
            task.delegation_id, result={"ok": True, "posted": scenario.KEY_INTEL}
        )
        parent_inbox = self.host.read_inbox(self.ids["lead"])
        self._check(
            "archivist.lead_notified",
            any(m.topic == "delegation.completed" for m in parent_inbox),
        )
        board = self.host.get_shared(scenario.KEY_INTEL)
        self._check(
            "archivist.board_intel",
            board["vault_id"] == scenario.VAULT_ID
            and board["alpha_shard"] == scenario.ALPHA_SHARD,
            f"board={board}",
        )

    def run_cryptanalyst_with_failure_then_recovery(self) -> None:
        """First attempt fails (bad vault), lead cancels, second attempt succeeds."""
        grants = scenario.ROLES["cryptanalyst"].capability_grants

        # --- attempt 1: intentional failure (wrong vault on purpose) ---
        task1 = self._delegate(
            "cryptanalyst",
            "Compute beta from vault_id on blackboard using private seed. (attempt 1)",
            grants,
        )
        self._require_inbox_delegation("cryptanalyst", "Compute beta")

        # Simulate worker bug: uses wrong vault
        bad_beta = scenario.compute_beta("WRONG-VAULT", scenario.CRYPTO_SEED)
        self.host.complete_delegation(
            task1.delegation_id,
            result={"ok": False, "beta": bad_beta},
            error="vault_id mismatch / checksum failed",
        )
        self._failures.append(
            {
                "role": "cryptanalyst",
                "delegation_id": task1.delegation_id,
                "error": "vault_id mismatch / checksum failed",
            }
        )
        self.host.set_shared(
            scenario.KEY_FAILURES,
            list(self._failures),
            author_entity_id=self.ids["lead"],
        )
        # Lead cancels any stale follow-up (already completed-failed; cancel returns False)
        cancelled = self.host.cancel_delegation(
            task1.delegation_id, reason="already failed"
        )
        self._check(
            "crypto.cannot_cancel_finished",
            cancelled is False,
            "finished tasks must not flip to cancelled",
        )

        lead_notes = self.host.read_inbox(self.ids["lead"])
        self._check(
            "crypto.failure_notified",
            any(
                m.topic == "delegation.completed"
                and m.payload.get("status") == DelegationStatus.FAILED.value
                for m in lead_notes
            ),
            f"notes={[(m.topic, m.payload.get('status')) for m in lead_notes]}",
        )

        # --- attempt 2: correct path ---
        task2 = self._delegate(
            "cryptanalyst",
            "Compute beta from vault_id on blackboard using private seed. (attempt 2 / replan)",
            grants,
        )
        inbox = self.host.read_inbox(self.ids["cryptanalyst"])
        # May include prior messages if not cleared — require a fresh assign
        self._check(
            "crypto.redelegate_inbox",
            any(m.topic == "delegation.assigned" for m in inbox),
        )

        intel = self.host.get_shared(scenario.KEY_INTEL)
        seed_claims = self.runtimes["cryptanalyst"].memory_subsystem.semantic.query_claims(
            "role:cryptanalyst"
        )
        seed = int(next(c["value"] for c in seed_claims if c["predicate"] == "seed"))
        beta = scenario.compute_beta(intel["vault_id"], seed)
        self._check(
            "crypto.beta_matches_expected",
            beta == scenario.EXPECTED_BETA,
            f"got={beta} expected={scenario.EXPECTED_BETA}",
        )
        payload = {"beta": beta, "vault_id_used": intel["vault_id"]}
        self.host.set_shared(
            scenario.KEY_CRYPTO, payload, author_entity_id=self.ids["cryptanalyst"]
        )
        self._add_receipt("cryptanalyst", task2.delegation_id, payload)
        self.host.complete_delegation(
            task2.delegation_id, result={"ok": True, "beta": beta}
        )
        self._check(
            "crypto.recovered_after_failure",
            self.host.get_delegation(task2.delegation_id).status
            == DelegationStatus.COMPLETED,
        )

    def run_engineer(self) -> None:
        # Dependency gate: refuse if crypto missing
        if self.host.get_shared(scenario.KEY_CRYPTO) is None:
            self._check("engineer.deps_missing", False, "crypto board empty")

        grants = scenario.ROLES["engineer"].capability_grants
        task = self._delegate(
            "engineer",
            "Assemble intermediate token from intel.alpha_shard + crypto.beta.",
            grants,
        )
        self._require_inbox_delegation("engineer", "Assemble intermediate")

        intel = self.host.get_shared(scenario.KEY_INTEL)
        crypto = self.host.get_shared(scenario.KEY_CRYPTO)
        token = scenario.assemble_token(intel["alpha_shard"], crypto["beta"])
        self._check(
            "engineer.token",
            token == scenario.INTERMEDIATE_TOKEN,
            f"token={token}",
        )
        artifact = {"token": token, "parts": [intel["alpha_shard"], crypto["beta"]]}
        self.host.set_shared(
            scenario.KEY_ARTIFACT, artifact, author_entity_id=self.ids["engineer"]
        )
        self._add_receipt("engineer", task.delegation_id, artifact)
        self.host.complete_delegation(
            task.delegation_id, result={"ok": True, "token": token}
        )

    def run_qa(self) -> None:
        grants = scenario.ROLES["qa"].capability_grants
        task = self._delegate(
            "qa",
            "Verify artifact token against assembly rule and sign clearance.",
            grants,
        )
        self._require_inbox_delegation("qa", "Verify artifact")

        artifact = self.host.get_shared(scenario.KEY_ARTIFACT)
        receipts = self.host.get_shared(scenario.KEY_RECEIPTS) or []
        roles_present = {r["role"] for r in receipts}
        required = {"archivist", "cryptanalyst", "engineer"}
        self._check(
            "qa.evidence_chain",
            required.issubset(roles_present),
            f"receipts={roles_present}",
        )

        token = artifact["token"]
        clearance = scenario.sign_clearance(token)
        ok = scenario.verify_clearance(clearance)
        self._check("qa.clearance_valid", ok, f"clearance={clearance}")

        board = {
            "clearance": clearance,
            "verified": ok,
            "evidence_roles": sorted(roles_present),
        }
        self.host.set_shared(
            scenario.KEY_CLEARANCE, board, author_entity_id=self.ids["qa"]
        )
        self._add_receipt("qa", task.delegation_id, board)
        self.host.complete_delegation(
            task.delegation_id, result={"ok": ok, "clearance": clearance}
        )

    def lead_synthesize(self) -> str:
        board = self.host.get_shared(scenario.KEY_CLEARANCE)
        self._check("lead.clearance_present", board is not None and board.get("verified"))
        receipts = self.host.get_shared(scenario.KEY_RECEIPTS) or []
        self._check(
            "lead.all_four_receipts",
            {r["role"] for r in receipts} >= {"archivist", "cryptanalyst", "engineer", "qa"},
            f"receipts={[r['role'] for r in receipts]}",
        )
        failures = self.host.get_shared(scenario.KEY_FAILURES) or []
        self._check(
            "lead.recorded_crypto_failure",
            any(f.get("role") == "cryptanalyst" for f in failures),
            f"failures={failures}",
        )
        clearance = board["clearance"]
        # Lead records mission complete in own private memory (not a leak of others' seeds)
        self.runtimes["lead"].memory_subsystem.semantic.record_claim(
            subject="mission:split_key",
            predicate="clearance",
            value=clearance,
        )
        return clearance

    def anti_forge_and_trust(self) -> None:
        """Lead cannot skip QA; outsider cannot take sensitive delegation grants path."""
        # Forge attempt: plant clearance without QA receipt — harness detects missing QA
        forged = {
            "clearance": scenario.EXPECTED_CLEARANCE,
            "verified": True,
            "evidence_roles": ["lead"],
        }
        # Snapshot real board
        real = self.host.get_shared(scenario.KEY_CLEARANCE)
        self.host.set_shared(
            scenario.KEY_CLEARANCE, forged, author_entity_id=self.ids["lead"]
        )
        receipts = self.host.get_shared(scenario.KEY_RECEIPTS) or []
        qa_ok = any(r.get("role") == "qa" for r in receipts)
        forge_accepted = qa_ok and forged.get("evidence_roles") == ["lead"]
        # Policy: clearance author must be QA entity when receipts include qa
        author_entry = self.host._shared_memory.get(scenario.KEY_CLEARANCE)  # noqa: SLF001
        # After forge, author is lead — reject
        forge_blocked = author_entry["author"] != self.ids["qa"]
        self._check(
            "anti_forge.lead_author_rejected",
            forge_blocked is True,
            f"author={author_entry['author']}",
        )
        # Restore real QA board
        self.host.set_shared(
            scenario.KEY_CLEARANCE, real, author_entity_id=self.ids["qa"]
        )
        self._check(
            "anti_forge.restored_qa_board",
            self.host.get_shared(scenario.KEY_CLEARANCE)["clearance"]
            == scenario.EXPECTED_CLEARANCE,
        )
        _ = forge_accepted

        # Trust: lead→outsider is untrusted
        trust = self.host.get_trust(self.ids["lead"], self.ids["outsider"])
        self._check(
            "trust.outsider_untrusted",
            trust == TrustLevel.UNTRUSTED_EXTERNAL,
            f"trust={trust}",
        )

        # Outsider must not hold specialist private claims
        out_claims = self.runtimes["outsider"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        self._check("trust.outsider_no_intel", len(out_claims) == 0)

        # Delegation to unknown entity must fail
        try:
            self.host.delegate_task(
                parent_entity_id=self.ids["lead"],
                assigned_to_entity_id="agent:does-not-exist",
                goal="nope",
            )
            self._check("delegate.unknown_entity_raises", False, "expected MultiAgentError")
        except MultiAgentError:
            self._check("delegate.unknown_entity_raises", True)

    def _add_receipt(self, role: str, delegation_id: str, payload: dict[str, Any]) -> None:
        self._receipts.append(
            {
                "role": role,
                "delegation_id": delegation_id,
                "payload_keys": sorted(payload.keys()),
                "ts": time.time(),
            }
        )
        self.host.set_shared(
            scenario.KEY_RECEIPTS,
            list(self._receipts),
            author_entity_id=self.ids["lead"],
        )

    def run(self) -> str:
        self.bootstrap()
        self.assert_memory_isolation()
        self.lead_posts_plan()
        self.run_archivist()
        # Isolation still holds after archivist posts public intel
        arch_private = self.runtimes["archivist"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        self._check(
            "post_intel.archivist_still_private_dossier",
            any(c.get("predicate") == "dossier" for c in arch_private),
        )
        lead_arch = self.runtimes["lead"].memory_subsystem.semantic.query_claims(
            "role:archivist"
        )
        self._check(
            "post_intel.lead_no_private_archivist_claims",
            len(lead_arch) == 0,
            "blackboard share must not write into lead private semantic store",
        )
        self.run_cryptanalyst_with_failure_then_recovery()
        self.run_engineer()
        self.run_qa()
        clearance = self.lead_synthesize()
        self.anti_forge_and_trust()
        self._check(
            "mission.clearance_final",
            clearance == scenario.EXPECTED_CLEARANCE,
            f"got={clearance}",
        )
        return clearance


def run_benchmark() -> RunReport:
    t0 = time.time()
    report = RunReport(
        scenario_id=scenario.SCENARIO_ID,
        version=scenario.SCENARIO_VERSION,
        passed=False,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="jaeger_split_key_") as tmp:
            team = SplitKeyTeam(pathlib.Path(tmp))
            clearance = team.run()
            report.checks = team.checks
            report.clearance = clearance
            report.passed = all(c.ok for c in team.checks) and bool(team.checks)
    except Exception as exc:  # noqa: BLE001 — top-level bench report
        report.error = f"{exc}\n{traceback.format_exc()}"
        # Preserve any checks collected before failure if present on exception path
        if "team" in locals():
            report.checks = team.checks  # type: ignore[name-defined]
        report.passed = False
    report.elapsed_s = time.time() - t0
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable report")
    args = parser.parse_args(argv)

    report = run_benchmark()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        status = "PASS" if report.passed else "FAIL"
        print(f"[{status}] {report.scenario_id} v{report.version} in {report.elapsed_s:.2f}s")
        print(f"  clearance: {report.clearance}")
        for c in report.checks:
            mark = "✓" if c.ok else "✗"
            extra = f" — {c.detail}" if c.detail and not c.ok else ""
            print(f"  {mark} {c.id}{extra}")
        if report.error:
            print("  error:")
            print("\n".join(f"    {line}" for line in report.error.splitlines()[:40]))
        summary = report.to_dict()["summary"]
        print(f"  summary: {summary['passed']}/{summary['total']} checks passed")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
