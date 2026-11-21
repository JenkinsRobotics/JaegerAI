"""Hard multi-agent team gate: Operation Split-Key.

Lead + four specialists must collaborate under RuntimeHost to reconstruct
a clearance no single agent knows. Covers isolation, dependency order,
failure recovery, anti-forge, and trust.
"""
from __future__ import annotations

from dev.benchmark.multiagent_team_hard import run_benchmark
from dev.evals.multiagent import operation_split_key as scenario


def test_operation_split_key_team_hard():
    report = run_benchmark()
    assert report.error is None, report.error
    assert report.passed, [
        (c.id, c.detail) for c in report.checks if not c.ok
    ]
    assert report.clearance == scenario.EXPECTED_CLEARANCE
    # Must have exercised failure recovery + anti-forge + isolation
    ids = {c.id for c in report.checks}
    required = {
        "bootstrap.five_specialists_plus_outsider",
        "crypto.recovered_after_failure",
        "qa.evidence_chain",
        "lead.all_four_receipts",
        "anti_forge.lead_author_rejected",
        "trust.outsider_untrusted",
        "mission.clearance_final",
    }
    missing = required - ids
    assert not missing, f"missing checks: {missing}"


def test_split_key_ground_truth_is_internally_consistent():
    beta = scenario.compute_beta(scenario.VAULT_ID, scenario.CRYPTO_SEED)
    assert beta == scenario.EXPECTED_BETA
    token = scenario.assemble_token(scenario.ALPHA_SHARD, beta)
    assert token == scenario.INTERMEDIATE_TOKEN
    assert scenario.verify_clearance(scenario.sign_clearance(token))
    assert not scenario.verify_clearance("FORGED-CLEARANCE")
