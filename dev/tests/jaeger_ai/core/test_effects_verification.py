"""Tests for the Typed Effect and Verification Model (Workstream 9).

Verifies Invariants:
1. ProposedAction -> AuthorityDecision -> EffectIntent -> EffectLedger -> Execution -> EffectResult -> VerificationResult
2. Connected identifiers:
   request_id -> run_id -> proposal_id -> authority_decision_id -> effect_id -> verification_id
3. "Tool returned ok" NEVER automatically means objective verified.
4. Independent verification probes real disk state.
5. Unauthorized proposals are refused execution before any side effect occurs.
6. Idempotent re-execution via EffectLedger prevents duplicate side effects.
"""
from pathlib import Path
import tempfile
import pytest

from jaeger_ai.contract.schemas import (
    AuthorityDecision as ContractAuthorityDecision,
    AuthorityDecisionType,
    EffectStatus,
    ProposedAction as ContractProposedAction,
    VerificationStatus,
)
from jaeger_ai.core.effects.pipeline import EffectExecutionError, EffectPipeline
from jaeger_agent.cognition.effects import InMemoryEffectLedger


@pytest.fixture
def pipeline():
    return EffectPipeline()


@pytest.fixture
def ledger():
    return InMemoryEffectLedger()


def test_connected_audit_trace(pipeline: EffectPipeline):
    """Every effect execution produces an unbroken chain of connected identifiers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = Path(tmpdir) / "output.txt"

        proposal = ContractProposedAction(
            request_id="req_101",
            run_id="run_202",
            action_type="file_write",
            tool_name="write_file",
            target_path=str(target_file),
            arguments={"path": str(target_file), "content": "hello verified world"},
        )
        auth_decision = ContractAuthorityDecision(
            proposal_id=proposal.proposal_id,
            decision=AuthorityDecisionType.ALLOW,
            reason="Authorized for test",
        )

        def do_write():
            target_file.write_text("hello verified world", encoding="utf-8")
            return {"ok": True, "path": str(target_file)}

        intent, eff_result, verif_result = pipeline.execute_and_verify(
            proposal,
            auth_decision,
            do_write,
        )

        # Assert unbroken connection of identifiers
        assert intent.request_id == "req_101"
        assert intent.run_id == "run_202"
        assert intent.proposal_id == proposal.proposal_id
        assert intent.authority_decision_id == auth_decision.decision_id
        assert intent.effect_id.startswith("eff_")

        assert eff_result.effect_id == intent.effect_id
        assert eff_result.status == EffectStatus.APPLIED

        assert verif_result.request_id == "req_101"
        assert verif_result.run_id == "run_202"
        assert verif_result.effect_id == intent.effect_id
        assert verif_result.verification_id.startswith("verif_")

        # Independent disk probe verified
        assert verif_result.status == VerificationStatus.OBJECTIVE_VERIFIED
        assert "disk_probe" in verif_result.verifier or "file_write" in verif_result.verifier


def test_unauthorized_proposal_refuses_execution(pipeline: EffectPipeline):
    """An unauthorized proposal cannot declare an EffectIntent or execute."""
    proposal = ContractProposedAction(
        request_id="req_deny",
        run_id="run_deny",
        action_type="shell_exec",
        tool_name="run_command",
        arguments={"CommandLine": "reboot"},
    )
    auth_decision = ContractAuthorityDecision(
        proposal_id=proposal.proposal_id,
        decision=AuthorityDecisionType.DENY,
        reason="Operator policy denied reboot",
    )

    side_effect_executed = False

    def dangerous_action():
        nonlocal side_effect_executed
        side_effect_executed = True
        return {"ok": True}

    with pytest.raises(EffectExecutionError) as exc_info:
        pipeline.execute_and_verify(proposal, auth_decision, dangerous_action)

    assert "not authorized" in str(exc_info.value)
    assert side_effect_executed is False


def test_tool_ok_does_not_equal_verified_for_unknown_tool(pipeline: EffectPipeline):
    """Tool returning ok is NOT automatically verified without an independent verifier."""
    proposal = ContractProposedAction(
        request_id="req_303",
        run_id="run_303",
        action_type="custom_external_action",
        tool_name="custom_api_call",
        arguments={"endpoint": "https://api.example.com/v1/notify"},
    )
    auth_decision = ContractAuthorityDecision(
        proposal_id=proposal.proposal_id,
        decision=AuthorityDecisionType.ALLOW,
    )

    def do_call():
        return {"ok": True, "status": "sent"}

    intent, eff_result, verif_result = pipeline.execute_and_verify(
        proposal,
        auth_decision,
        do_call,
    )

    assert eff_result.status == EffectStatus.APPLIED
    # Invariant: Unknown effect must NOT magically become verified
    assert verif_result.status == VerificationStatus.OBJECTIVE_INCONCLUSIVE
    assert "syntactic confirmation only" in verif_result.evidence


def test_independent_disk_probe_detects_false_tool_claim(pipeline: EffectPipeline):
    """If a tool claims ok but the file is not on disk, verification fails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_file = Path(tmpdir) / "ghost.txt"

        proposal = ContractProposedAction(
            request_id="req_ghost",
            run_id="run_ghost",
            action_type="file_write",
            tool_name="write_file",
            target_path=str(non_existent_file),
            arguments={"path": str(non_existent_file), "content": "ghost content"},
        )
        auth_decision = ContractAuthorityDecision(
            proposal_id=proposal.proposal_id,
            decision=AuthorityDecisionType.ALLOW,
        )

        def lying_tool():
            # Tool pretends it wrote the file, but doesn't actually write it
            return {"ok": True, "path": str(non_existent_file)}

        intent, eff_result, verif_result = pipeline.execute_and_verify(
            proposal,
            auth_decision,
            lying_tool,
        )

        assert eff_result.status == EffectStatus.APPLIED
        # Ground truth check fails!
        assert verif_result.status == VerificationStatus.OBJECTIVE_FAILED
        assert "does not exist after write" in verif_result.evidence


def test_effect_ledger_idempotency(pipeline: EffectPipeline, ledger: InMemoryEffectLedger):
    """Re-executing an effect with the same idempotency key skips execution."""
    execution_counter = 0

    proposal = ContractProposedAction(
        request_id="req_repeat",
        run_id="run_repeat",
        action_type="send_notification",
        tool_name="notify",
        arguments={"msg": "Hello"},
    )
    auth_decision = ContractAuthorityDecision(
        proposal_id=proposal.proposal_id,
        decision=AuthorityDecisionType.ALLOW,
    )

    def do_notify():
        nonlocal execution_counter
        execution_counter += 1
        return {"ok": True}

    # First run: applied
    intent1, eff1, verif1 = pipeline.execute_and_verify(
        proposal, auth_decision, do_notify, ledger=ledger
    )
    assert eff1.status == EffectStatus.APPLIED
    assert execution_counter == 1

    # Second run with same parameters: skipped as idempotent!
    intent2, eff2, verif2 = pipeline.execute_and_verify(
        proposal, auth_decision, do_notify, ledger=ledger
    )
    assert eff2.status == EffectStatus.SKIPPED_IDEMPOTENT
    assert execution_counter == 1  # Callable was not run a second time!
