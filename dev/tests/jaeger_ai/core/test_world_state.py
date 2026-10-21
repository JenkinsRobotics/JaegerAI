"""Tests for unified World-State Architecture (Workstream 7).

Verifies Epistemic Invariants:
1. OBSERVATION != CLAIM != BELIEF != FACT
2. Raw observations do not automatically mutate into accepted claims without evidence.
3. Directed relationships link typed entities.
4. Evidence links claims/beliefs back to observation/sensor sources.
5. SemanticMemory delegates authoritatively to SqliteWorldStore (<state_root>/knowledge.sqlite3).
"""
import tempfile
from pathlib import Path
import pytest

from jaeger_ai.core.world.model import (
    BeliefStatus,
    EpistemicProvenance,
    WorldBelief,
    WorldClaim,
    WorldEntity,
    WorldEvidence,
    WorldObservation,
    WorldRelationship,
)
from jaeger_ai.core.world.store import SqliteWorldStore
from jaeger_ai.core.entity.memory import SemanticMemory


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "knowledge.sqlite3"
        yield SqliteWorldStore(db_path)


def test_entity_creation_and_retrieval(temp_store: SqliteWorldStore):
    ent = temp_store.record_entity(
        name="Jaeger",
        kind="agent",
        aliases=("jaeger-1", "resident-agent"),
        attributes={"runtime": "python", "version": "1.0"},
    )
    assert ent.name == "Jaeger"
    assert ent.kind == "agent"
    assert "resident-agent" in ent.aliases

    retrieved = temp_store.get_entity(ent.entity_id)
    assert retrieved is not None
    assert retrieved.name == "Jaeger"
    assert retrieved.attributes.get("runtime") == "python"


def test_observation_is_not_automatic_claim(temp_store: SqliteWorldStore):
    """An empirical observation does not automatically create or become a verified claim."""
    obs = temp_store.record_observation(
        sensor="camera_front",
        signals={"faces_detected": 1, "confidence": 0.82},
        salience=0.9,
    )
    assert obs.observation_id.startswith("obs_")
    assert obs.sensor == "camera_front"

    # Searching claims returns nothing - observation has not been turned into a claim
    claims = temp_store.query_claims("camera_front")
    assert len(claims) == 0


def test_claim_with_provenance_and_evidence(temp_store: SqliteWorldStore):
    """Claims must store explicit provenance, confidence, and can be linked to evidence."""
    # 1. Raw observation
    obs = temp_store.record_observation(
        sensor="terminal_stdout",
        signals={"line": "build succeeded in 4.2s"},
    )

    # 2. Claim derived with OBSERVED provenance
    claim = temp_store.record_claim(
        subject="project_build",
        predicate="status",
        value="success",
        provenance=EpistemicProvenance.OBSERVED,
        confidence=0.98,
        source_id=obs.sensor,
    )
    assert claim.provenance == EpistemicProvenance.OBSERVED
    assert claim.confidence == 0.98

    # 3. Grounding evidence link
    evi = temp_store.link_evidence(
        target_id=claim.claim_id,
        source_type="observation",
        source_id=obs.observation_id,
        snippet="build succeeded in 4.2s",
    )
    assert evi.target_id == claim.claim_id
    assert evi.source_id == obs.observation_id


def test_relationships_link_entities(temp_store: SqliteWorldStore):
    """Directed relationships link entities with confidence and evidence."""
    user = temp_store.record_entity("Alice", "person")
    project = temp_store.record_entity("JaegerAI", "project")

    rel = temp_store.record_relationship(
        subject_entity_id=user.entity_id,
        relation="maintains",
        target_entity_id=project.entity_id,
        confidence=1.0,
    )
    assert rel.relation == "maintains"
    assert rel.subject_entity_id == user.entity_id
    assert rel.target_entity_id == project.entity_id


def test_semantic_memory_delegation():
    """SemanticMemory delegates seamlessly to SqliteWorldStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        sem_mem = SemanticMemory(state_root)

        res = sem_mem.record_claim(
            subject="operator",
            predicate="preferred_shell",
            value="zsh",
            confidence=0.95,
        )
        assert res["status"] == "recorded"
        assert res["subject"] == "operator"

        claims = sem_mem.query_claims("operator")
        assert len(claims) == 1
        assert claims[0]["predicate"] == "preferred_shell"
        assert claims[0]["value"] == "zsh"

        recent = sem_mem.list_recent()
        assert len(recent) == 1
        assert recent[0]["subject"] == "operator"

        # Verify underlying world store matches
        db_claims = sem_mem.world_store.query_claims("operator")
        assert len(db_claims) == 1
        assert db_claims[0].value == "zsh"


def test_a_withdrawn_claim_is_not_recalled(temp_store: SqliteWorldStore):
    """Recall ignored ``valid_until``, so a withdrawn claim (the audit's
    ``user.remembered_word=voice``) kept being fed to the model as belief."""
    import sqlite3
    import time

    kept = temp_store.record_claim("user", "audit_memory_token", "AUDIT-MEMORY-NOVA-7319")
    withdrawn = temp_store.record_claim("user", "remembered_word", "voice")
    with sqlite3.connect(temp_store.db_path) as conn:
        conn.execute("UPDATE world_claims SET valid_until=? WHERE claim_id=?",
                     (time.time() - 1, withdrawn.claim_id))

    recalled = [c.claim_id for c in temp_store.list_recent_claims(10)]

    assert kept.claim_id in recalled
    assert withdrawn.claim_id not in recalled


def test_semantic_claim_search_and_expiry_share_the_existing_owner(tmp_path):
    import time
    from jaeger_ai.core.world.store import SqliteWorldStore
    store=SqliteWorldStore(tmp_path/'knowledge.sqlite3')
    for i in range(52):store.record_claim('Owned subject','preference',f'Owned literal {i}%',source_id='owned-fixture')
    expired=store.record_claim('Expired subject','preference','Expired value')
    with store._get_connection() as conn:conn.execute('UPDATE world_claims SET valid_until=? WHERE claim_id=?',(time.time()-1,expired.claim_id))
    assert store.query_claims('Expired subject')==[]
    assert len(store.query_claims('Expired subject',include_inactive=True))==1
    first=store.search_claims('literal');second=store.search_claims('literal',before=first['next_before'])
    assert len(first['claims'])==50 and len(second['claims'])==2
    assert not ({c['claim_id'] for c in first['claims']}&{c['claim_id'] for c in second['claims']})
    assert store.search_claims('%')['claims'] and store.search_claims('Expired')['claims']==[]
    historic=store.search_claims('Expired',include_inactive=True)['claims'][0]
    assert not historic['active'] and not historic['recent_context_candidate'] and len(historic['revision'])==64


@pytest.mark.asyncio
async def test_semantic_memory_http_uses_only_loaded_owner_and_existing_read_scope(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.world.store import SqliteWorldStore
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    owner=SqliteWorldStore(tmp_path/'knowledge.sqlite3');owner.record_claim('Owned','preference','x'*5000,source_id='owned-fixture')
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        monkeypatch.setattr(EntityRuntime,'_instance',None)
        absent=await (await http.get('/v1/runtime/memory/claims')).json()
        assert not absent['available'] and EntityRuntime._instance is None
        monkeypatch.setattr(EntityRuntime,'_instance',SimpleNamespace(memory_subsystem=SimpleNamespace(semantic=SimpleNamespace(world_store=owner))))
        available=await (await http.get('/v1/runtime/memory/claims?q=Owned')).json()
        assert available['available'] and len(available['claims'])==1
        row=available['claims'][0];assert row['truncated'] and len(row['value'])==4000
        assert len(owner.query_claims('Owned')[0].value)==5000
        assert (await http.get('/v1/runtime/memory/claims?before=-1')).status==400
        assert gateway.store.list_requests()==[]
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as http:
        assert (await http.get('/v1/runtime/memory/claims')).status==403


def test_claim_correction_forget_restore_preserves_provenance_and_recovery(tmp_path):
    store=SqliteWorldStore(tmp_path/'knowledge.sqlite3')
    original=store.record_claim('Owned fixture','preference','old',provenance='verified',source_id='fixture-evidence')
    before=store.claim_detail(original.claim_id)
    command=dict(expected_revision=before['revision'],operation_id='owned-correction',actor='human:operator',text='new')
    receipt=store.manage_claim(original.claim_id,'correct',**command)
    assert store.manage_claim(original.claim_id,'correct',**command)==receipt
    reopened=SqliteWorldStore(store.db_path)
    assert reopened.claim_operation('owned-correction')==receipt
    historical=reopened.claim_detail(original.claim_id)
    assert historical['value']=='old' and historical['provenance']=='verified' and historical['source_id']=='fixture-evidence'
    assert not historical['active'] and historical['actions']==[]
    replacement=receipt['result']['replacement_claim_id'];detail=reopened.claim_detail(replacement)
    assert detail['replaces_claim_id']==original.claim_id
    assert (detail['value'],detail['provenance'],detail['source_id'])==('new','told','human:operator')
    assert [c.claim_id for c in reopened.query_claims('Owned fixture')]==[replacement]
    assert reopened.search_claims()['claims'][0]['revision']==detail['revision']
    reopened.manage_claim(replacement,'forget',expected_revision=detail['revision'],operation_id='owned-forget',actor='human:operator')
    assert reopened.query_claims('Owned fixture')==[] and reopened.list_recent_claims()==[]
    forgotten=reopened.claim_detail(replacement);assert forgotten['actions']==['restore']
    reopened.manage_claim(replacement,'restore',expected_revision=forgotten['revision'],operation_id='owned-restore',actor='human:operator')
    restored=reopened.claim_detail(replacement)
    assert restored['value']=='new' and restored['revision']!=detail['revision']
    with pytest.raises(ValueError,match='changed'):
        reopened.manage_claim(replacement,'forget',expected_revision=detail['revision'],operation_id='owned-stale',actor='human:operator')
    with pytest.raises(ValueError,match='conflicts'):
        reopened.manage_claim(original.claim_id,'correct',**{**command,'text':'different'})
    assert len(reopened.query_claims('Owned fixture',include_inactive=True))==2


def test_claim_restore_does_not_extend_expiry_or_modify_system_claims(tmp_path,monkeypatch):
    import jaeger_ai.core.world.store as module
    store=SqliteWorldStore(tmp_path/'knowledge.sqlite3');now=1000.
    monkeypatch.setattr(module.time,'time',lambda:now)
    claim=store.record_claim('Owned','temporary','value')
    with store._get_connection() as conn:conn.execute('UPDATE world_claims SET valid_until=1010 WHERE claim_id=?',(claim.claim_id,))
    store.manage_claim(claim.claim_id,'forget',expected_revision=store.claim_detail(claim.claim_id)['revision'],operation_id='forget-expiring',actor='human:operator')
    now=1011.
    detail=store.claim_detail(claim.claim_id);assert detail['actions']==[]
    with pytest.raises(ValueError,match='validity elapsed'):
        store.manage_claim(claim.claim_id,'restore',expected_revision=detail['revision'],operation_id='restore-expired',actor='human:operator')
    protected=store.record_claim('Owned','system','value',provenance='system')
    detail=store.claim_detail(protected.claim_id);assert detail['actions']==[]
    with pytest.raises(ValueError,match='protected'):
        store.manage_claim(protected.claim_id,'forget',expected_revision=detail['revision'],operation_id='protected',actor='human:operator')


@pytest.mark.asyncio
async def test_claim_controls_existing_admin_scope_residency_and_atomic_receipt(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.entity.ownership import EntityRuntimeMode
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    owner=SqliteWorldStore(tmp_path/'knowledge.sqlite3');claim=owner.record_claim('Owned fixture','preference','saved')
    runtime=SimpleNamespace(mode=EntityRuntimeMode.OWNER,is_resident=True,memory_subsystem=SimpleNamespace(semantic=SimpleNamespace(world_store=owner)))
    monkeypatch.setattr(EntityRuntime,'_instance',runtime)
    base='/v1/runtime/memory/claims/'+claim.claim_id
    body={'operation_id':'owned-http-forget','expected_revision':owner.claim_detail(claim.claim_id)['revision']}
    async with TestClient(TestServer(gateway.app),headers=client_headers('jaegerd')) as http:
        assert (await http.post(base+'/forget',json=body)).status==403
        detail=await (await http.get(base)).json();assert detail['actions']==[]
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        runtime.is_resident=False
        assert (await http.post(base+'/forget',json=body)).status==400
        assert gateway.store.control_operation(body['operation_id']) is None
        runtime.is_resident=True
        result=await http.post(base+'/forget',json=body);assert result.status==200
        receipt=await result.json();assert receipt['ok'] and owner.query_claims('Owned fixture')==[]
        # Domain receipt remains authoritative if process dies before the Gateway receipt settles.
        with gateway.store._get_conn() as conn:
            conn.execute('UPDATE control_operations SET receipt_json=NULL,status=? WHERE operation_id=?',('reserved',body['operation_id']))
        recovered=await (await http.get('/v1/runtime/memory/claim-operations/'+body['operation_id'])).json()
        assert recovered['receipt']==receipt
        assert await (await http.post(base+'/forget',json=body)).json()==receipt
        assert len(owner.claim_detail(claim.claim_id)['changes'])==1
        assert gateway.store.list_requests()==[]


def test_concurrent_claim_commands_allow_only_one_current_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=SqliteWorldStore(tmp_path/'knowledge.sqlite3');claim=store.record_claim('Owned concurrent','preference','old')
    revision=store.claim_detail(claim.claim_id)['revision']
    def change(index):
        try:return store.manage_claim(claim.claim_id,'correct',expected_revision=revision,operation_id=f'owned-concurrent-{index}',actor='human:operator',text=f'new-{index}')
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,range(2)))
    assert sum(result is not None for result in results)==1
    assert len(store.query_claims('Owned concurrent'))==1
    assert len(store.query_claims('Owned concurrent',include_inactive=True))==2
    assert len(store.claim_detail(claim.claim_id)['changes'])==1
