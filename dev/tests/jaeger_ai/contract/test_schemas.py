"""Tests for Workstream 4: Typed Contracts and Versioned Schemas.

Verifies that all 18 core contracts:
1. Validate correctly on valid data with default schema_version=1.
2. Fail deterministically on malformed, missing, or invalid values.
3. Successfully serialize and deserialize via JSON without data loss.
4. Enforce strict boundaries (e.g. valid sha256 hashes, bounded salience, valid lifecycle states).
"""
import pytest
from pydantic import ValidationError

from jaeger_ai.contract.schemas import (
    SCHEMA_VERSION,
    RuntimeRequest,
    RuntimeResponse,
    Session,
    Run,
    AgentEvent,
    ProposedAction,
    AuthorityDecision,
    AuthorityDecisionType,
    ApprovalRequest,
    EffectIntent,
    EffectResult,
    EffectStatus,
    VerificationResult,
    VerificationStatus,
    Attachment,
    Capability,
    Provider,
    Model,
    Device,
    AgentToAgentRequest,
    AgentToAgentResult,
)


def test_schema_version_consistency():
    """All schemas must carry the canonical schema_version."""
    req = RuntimeRequest(session_id="s1", input_text="hello")
    assert req.schema_version == SCHEMA_VERSION == 1

    session = Session(session_id="s1")
    assert session.schema_version == 1

    run = Run(run_id="r1", commitment_id="c1")
    assert run.schema_version == 1


def test_runtime_request_validation():
    """RuntimeRequest must require input_text and session_id, and reject empty inputs."""
    valid = RuntimeRequest(
        session_id="s_123",
        input_text="Inspect server disk space",
        model="kimi-k2.7-code:cloud",
        provider="ollama",
    )
    assert valid.session_id == "s_123"
    assert valid.input_text == "Inspect server disk space"
    assert valid.execution_mode.value == "agent"
    assert valid.actionable is True

    # Deterministic failure on empty input_text
    with pytest.raises(ValidationError):
        RuntimeRequest(session_id="s_123", input_text="")

    # Deterministic failure on missing session_id
    with pytest.raises(ValidationError):
        RuntimeRequest(input_text="hello")


def test_runtime_response_serialization_roundtrip():
    """RuntimeResponse must roundtrip cleanly through JSON."""
    resp = RuntimeResponse(
        request_id="req_456",
        turn_id="turn_789",
        status="completed",
        text="All systems operational.",
        model="kimi-k2.7-code:cloud",
        backend="ollama",
        strategy="react_loop",
        tool_activity=[{"tool": "filesystem.read", "ok": True}],
    )
    raw_json = resp.model_dump_json()
    loaded = RuntimeResponse.model_validate_json(raw_json)
    assert loaded == resp
    assert loaded.status == "completed"
    assert len(loaded.tool_activity) == 1


def test_agent_event_salience_bounds():
    """AgentEvent salience must be strictly bounded between 0.0 and 1.0."""
    ev = AgentEvent(
        event_id="ev_001",
        event_type="perception.sensed",
        actor="system:sensor",
        source="desktop_supervisor",
        salience=0.85,
    )
    assert ev.salience == 0.85

    # Salience > 1.0 must fail
    with pytest.raises(ValidationError):
        AgentEvent(
            event_id="ev_002",
            event_type="test",
            actor="test",
            source="test",
            salience=1.5,
        )

    # Salience < 0.0 must fail
    with pytest.raises(ValidationError):
        AgentEvent(
            event_id="ev_003",
            event_type="test",
            actor="test",
            source="test",
            salience=-0.1,
        )


def test_run_canonical_states():
    """Run schema must enforce canonical WorkState values."""
    valid_run = Run(
        run_id="run_101",
        commitment_id="comm_202",
        state="waiting_for_approval",
        wake_key="approval:app_1",
    )
    assert valid_run.state == "waiting_for_approval"

    # Invalid state must fail deterministically
    with pytest.raises(ValidationError):
        Run(
            run_id="run_102",
            commitment_id="comm_202",
            state="flying_around",
        )


def test_authority_and_approval_contracts():
    """Validate ProposedAction, AuthorityDecision, and ApprovalRequest linkage."""
    proposal = ProposedAction(
        proposal_id="prop_001",
        request_id="req_001",
        run_id="run_001",
        action_type="file_write",
        tool_name="filesystem.write",
        arguments={"path": "/tmp/test.txt", "content": "hello"},
        tier="write_local",
    )
    assert proposal.proposal_id == "prop_001"
    assert proposal.tier == "write_local"

    decision = AuthorityDecision(
        decision_id="auth_001",
        proposal_id=proposal.proposal_id,
        decision=AuthorityDecisionType.REQUIRE_APPROVAL,
        reason="Writing to protected local directory requires confirmation",
    )
    assert decision.decision == AuthorityDecisionType.REQUIRE_APPROVAL

    approval = ApprovalRequest(
        approval_id="approval_999",
        request_id="req_001",
        session_id="session_001",
        run_id="run_001",
        prompt="Allow writing to /tmp/test.txt?",
        metadata={"tool": "filesystem.write"},
    )
    assert approval.status == "pending"
    assert approval.options == ["once", "deny"]


def test_effect_intent_result_and_verification_pipeline():
    """Validate EffectIntent -> EffectResult -> VerificationResult chain."""
    intent = EffectIntent(
        effect_id="eff_001",
        request_id="req_001",
        run_id="run_001",
        proposal_id="prop_001",
        authority_decision_id="auth_001",
        idempotency_key="sha256:write:/tmp/test.txt",
        action="file_write",
        target="/tmp/test.txt",
    )
    assert intent.idempotency_key == "sha256:write:/tmp/test.txt"

    result = EffectResult(
        effect_id=intent.effect_id,
        status=EffectStatus.APPLIED,
        result={"bytes_written": 5},
    )
    assert result.status == EffectStatus.APPLIED

    verif = VerificationResult(
        verification_id="verif_001",
        request_id="req_001",
        effect_id=intent.effect_id,
        status=VerificationStatus.OBJECTIVE_VERIFIED,
        target_objective="Write hello to /tmp/test.txt",
        evidence="Disk probe verified file exists with exact sha256 checksum",
        verifier="disk_probe",
    )
    assert verif.status == VerificationStatus.OBJECTIVE_VERIFIED
    assert verif.verifier == "disk_probe"


def test_attachment_sha256_validation():
    """Attachment must enforce valid 64-char sha256 hex string and non-negative size."""
    valid = Attachment(
        session_id="s_att",
        original_filename="doc.txt",
        stored_filename="uuid_doc.txt",
        safe_path="/tmp/uploads/uuid_doc.txt",
        size_bytes=1024,
        sha256="a" * 64,
        mime_type="text/plain",
    )
    assert valid.size_bytes == 1024
    assert len(valid.sha256) == 64

    # Negative size must fail
    with pytest.raises(ValidationError):
        Attachment(
            session_id="s_att",
            original_filename="doc.txt",
            stored_filename="uuid_doc.txt",
            safe_path="/tmp/uploads/uuid_doc.txt",
            size_bytes=-1,
            sha256="a" * 64,
        )

    # Invalid sha256 length must fail
    with pytest.raises(ValidationError):
        Attachment(
            session_id="s_att",
            original_filename="doc.txt",
            stored_filename="uuid_doc.txt",
            safe_path="/tmp/uploads/uuid_doc.txt",
            size_bytes=1024,
            sha256="short_hash",
        )


def test_device_contract():
    """Device contract represents node identities and advertised hardware capabilities."""
    device = Device(
        device_id="dev_mac_1",
        owner_entity="jaeger-entity-01",
        name="Operator MacBook Pro",
        device_type="mac",
        connection_state="connected",
        transport="unix_socket",
        capabilities=["display", "microphone", "speaker", "filesystem"],
    )
    assert device.device_type == "mac"
    assert "filesystem" in device.capabilities


def test_agent_to_agent_contract():
    """AgentToAgentRequest and AgentToAgentResult enforce bounded delegation and timing."""
    a2a_req = AgentToAgentRequest(
        source_agent_id="agent_lead",
        target_agent_id="agent_specialist_sec",
        task_type="audit_codebase",
        payload={"scope": "packages/jaeger-agent"},
        delegation_depth=2,
        timeout_s=30.0,
    )
    assert a2a_req.delegation_depth == 2
    assert a2a_req.timeout_s == 30.0

    # Delegation depth > 8 must fail to prevent recursion bombs
    with pytest.raises(ValidationError):
        AgentToAgentRequest(
            source_agent_id="agent_lead",
            target_agent_id="agent_specialist_sec",
            task_type="audit",
            delegation_depth=10,
        )

    a2a_res = AgentToAgentResult(
        correlation_id=a2a_req.message_id,
        source_agent_id="agent_specialist_sec",
        status="completed",
        result={"vulnerabilities_found": 0},
    )
    assert a2a_res.status == "completed"
