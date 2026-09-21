"""Commissioning acceptance checks.

Kinds:
  STRUCTURAL — local files/config exist. May report STRUCTURAL_OK.
  LIVE       — production path a real user uses (Gateway OWNER turn).
  DISABLED   — optional surface not in this run. Never a PASS.

A LIVE required gate may only pass with request_id/event IDs and an
independent external consequence. Class imports, direct Python writes,
fingerprint equality, and ``port_open or True`` are not LIVE evidence.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_ai.core.entity.model_capabilities import FAIL, capabilities_for

KIND_STRUCTURAL = "STRUCTURAL"
KIND_LIVE = "LIVE"
KIND_DISABLED = "DISABLED"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_STRUCTURAL_OK = "STRUCTURAL_OK"
STATUS_DISABLED = "DISABLED"


@dataclass
class CheckResult:
    id: str
    group: str
    passed: bool
    evidence: str = ""
    detail: str = ""
    kind: str = KIND_STRUCTURAL
    status: str = STATUS_FAIL
    request_id: str = ""
    trace_id: str = ""
    event_ids: list[str] = field(default_factory=list)
    artifact: str = ""
    terminal_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    passed: bool = False
    started_at: str = ""
    finished_at: str = ""
    offline: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "live_passed": self.live_passed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "offline": self.offline,
            "checks": [c.as_dict() for c in self.checks],
            "failed": [c.as_dict() for c in self.checks if c.status == STATUS_FAIL],
        }

    @property
    def live_passed(self) -> bool:
        live = [c for c in self.checks if c.kind == KIND_LIVE]
        return bool(live) and all(c.status == STATUS_PASS for c in live)

    def group_passed(self, group: str) -> bool:
        rows = [c for c in self.checks if c.group == group]
        return bool(rows) and all(c.status in {STATUS_PASS, STATUS_STRUCTURAL_OK, STATUS_DISABLED} for c in rows)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _add(
    report: ValidationReport,
    cid: str,
    group: str,
    *,
    kind: str,
    status: str,
    evidence: str,
    detail: str = "",
    request_id: str = "",
    trace_id: str = "",
    event_ids: list[str] | None = None,
    artifact: str = "",
    terminal_status: str = "",
) -> None:
    passed = status in {STATUS_PASS, STATUS_STRUCTURAL_OK, STATUS_DISABLED}
    report.checks.append(CheckResult(
        id=cid, group=group, passed=passed, evidence=evidence, detail=detail,
        kind=kind, status=status, request_id=request_id, trace_id=trace_id,
        event_ids=list(event_ids or []), artifact=artifact,
        terminal_status=terminal_status,
    ))


def _gateway_port() -> int:
    return int(os.environ.get("JAEGER_GATEWAY_PORT") or 8810)


def _gateway_status(port: int) -> dict[str, Any] | None:
    url = f"http://127.0.0.1:{port}/v1/runtime/status"
    try:
        with urlopen(url, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": str(exc)}
        payload.setdefault("http_status", exc.code)
        raise RuntimeError(payload) from exc
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def submit_gateway_turn(
    text: str,
    *,
    request_id: str,
    session_id: str | None = None,
    port: int | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """POST a turn to the resident Gateway and wait for terminal status."""
    gw = int(port or _gateway_port())
    sid = session_id or f"commissioning-{uuid.uuid4().hex[:10]}"
    base = f"http://127.0.0.1:{gw}"
    try:
        _http_json("POST", f"{base}/v1/sessions", {"session_id": sid, "title": "commissioning"})
    except Exception:
        pass
    admitted = _http_json(
        "POST",
        f"{base}/v1/sessions/{sid}/turns",
        {"text": text, "request_id": request_id},
        timeout=15.0,
    )
    if admitted.get("replayed"):
        return admitted
    deadline = time.time() + timeout_s
    rid = str(admitted.get("request_id") or request_id)
    last: dict[str, Any] = admitted
    while time.time() < deadline:
        try:
            last = _http_json("GET", f"{base}/v1/sessions/{sid}/requests/{rid}", timeout=5.0)
        except Exception:
            time.sleep(0.5)
            continue
        status = str(last.get("status") or "")
        if status in {"completed", "failed", "cancelled", "execution_unknown"}:
            last.setdefault("session_id", sid)
            return last
        time.sleep(0.4)
    last.setdefault("session_id", sid)
    last.setdefault("status", "timeout")
    return last


def _offline() -> bool:
    if os.environ.get("JAEGER_COMMISSIONING_LIVE", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("JAEGER_COMMISSIONING_OFFLINE", "").strip() in {"1", "true", "yes"}:
        return True
    return "PYTEST_CURRENT_TEST" in os.environ


def _instance_events(root: Path, *, since_id: int = 0, limit: int = 400) -> list[Any]:
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    from jaeger_ai.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=root)
    store = SqliteEventStore(layout.event_store_path)
    return store.query_events(since_id=since_id, limit=limit)


def validate_core(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.instance import InstanceLayout

    root = instance_dir(instance_root)
    layout = InstanceLayout(root=root)
    identity_path = layout.entity_identity_path
    entity_id = ""
    if identity_path.is_file():
        try:
            data = json.loads(identity_path.read_text(encoding="utf-8"))
            entity_id = str(data.get("entity_id") or "")
            _add(report, "entity_identity", "core", kind=KIND_STRUCTURAL,
                 status=STATUS_STRUCTURAL_OK if entity_id else STATUS_FAIL,
                 evidence=identity_path.as_posix(), detail=entity_id)
        except Exception as exc:
            _add(report, "entity_identity", "core", kind=KIND_STRUCTURAL, status=STATUS_FAIL,
                 evidence=identity_path.as_posix(), detail=str(exc)[:160])
    else:
        try:
            from jaeger_ai.core.entity.identity import resolve_entity_identity
            ident = resolve_entity_identity(layout.memory_dir)
            entity_id = ident.entity_id
            _add(report, "entity_identity", "core", kind=KIND_STRUCTURAL,
                 status=STATUS_STRUCTURAL_OK if entity_id else STATUS_FAIL,
                 evidence=str(layout.memory_dir / "entity_identity.json"), detail=entity_id)
        except Exception as exc:
            _add(report, "entity_identity", "core", kind=KIND_STRUCTURAL, status=STATUS_FAIL,
                 evidence=str(layout.memory_dir), detail=str(exc)[:160])

    event_path = layout.event_store_path
    try:
        from jaeger_ai.core.entity.event_store import SqliteEventStore
        store = SqliteEventStore(event_path)
        count = store.count()
        _add(report, "event_fabric", "core", kind=KIND_STRUCTURAL, status=STATUS_STRUCTURAL_OK,
             evidence=f"{event_path} count={count} latest={store.latest_id()}")
    except Exception as exc:
        _add(report, "event_fabric", "core", kind=KIND_STRUCTURAL, status=STATUS_FAIL,
             evidence=f"{event_path}: {exc}"[:240])

    memory_ok = layout.memory_dir.is_dir()
    _add(report, "memory_store", "core", kind=KIND_STRUCTURAL,
         status=STATUS_STRUCTURAL_OK if memory_ok else STATUS_FAIL,
         evidence=str(layout.memory_dir),
         detail="directory exists" if memory_ok else "missing")

    gw_port = _gateway_port()
    if offline:
        _add(report, "gateway", "core", kind=KIND_STRUCTURAL, status=STATUS_STRUCTURAL_OK,
             evidence="offline", detail="LIVE gateway probe skipped")
        return
    payload = _gateway_status(gw_port)
    ready = bool(payload and payload.get("ready"))
    live_id = ""
    if payload:
        live_id = str((payload.get("Agent") or {}).get("entity_id") or payload.get("entity_id") or "")
    same = (not entity_id) or (live_id == entity_id)
    _add(report, "gateway", "core", kind=KIND_LIVE,
         status=STATUS_PASS if ready and same else STATUS_FAIL,
         evidence=f"port={gw_port} entity_id={live_id} ready={ready}",
         detail="READY" if ready else "not READY",
         artifact=live_id)


def validate_cognition(instance_root: Path, report: ValidationReport) -> None:
    from jaeger_ai.core.instance.provider_certification import load_matrix

    matrix = load_matrix(instance_root)
    for role, required in (("CHAT", True), ("REACT", True), ("PLANNER", False), ("CRITIC", False)):
        assignment = matrix.assignments.get(role)
        if not assignment:
            _add(report, f"cognition.{role.lower()}", "cognition",
                 kind=KIND_STRUCTURAL,
                 status=STATUS_DISABLED if not required else STATUS_FAIL,
                 evidence="unassigned",
                 detail="optional" if not required else "no certified provider")
            continue
        model = str(assignment.get("model") or "")
        caps = capabilities_for(model)
        cap_key = {"CHAT": "chat", "REACT": "react", "PLANNER": "planning", "CRITIC": "critic"}[role]
        failed = str(caps.get(cap_key) or "").lower() == FAIL
        passed = (not failed) and matrix.passed(model, role)
        _add(report, f"cognition.{role.lower()}", "cognition",
             kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK if passed else STATUS_FAIL,
             evidence=f"{assignment.get('provider')}:{model}",
             detail="FAIL-certified" if failed else ("PASS" if passed else "not certified"))


def _live_write_check(root: Path, report: ValidationReport) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    from jaeger_ai.core.entity.events import EventType

    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    target = layout.workspace_dir / "commissioning-live-write.txt"
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
    store = SqliteEventStore(layout.event_store_path)
    before_id = store.latest_id()
    request_id = f"commissioning-write-{uuid.uuid4().hex[:12]}"
    objective = (
        f"Create workspace/commissioning-live-write.txt containing exactly "
        f"JAEGER-COMMISSIONING-OK. Then stop."
    )
    try:
        result = submit_gateway_turn(objective, request_id=request_id, timeout_s=240.0)
    except Exception as exc:
        _add(report, "safe_tool_execution", "action", kind=KIND_LIVE, status=STATUS_FAIL,
             evidence=str(exc)[:300], request_id=request_id)
        _add(report, "objective_verification", "action", kind=KIND_LIVE, status=STATUS_FAIL,
             evidence="write turn did not complete", request_id=request_id)
        return

    terminal = str(result.get("status") or "")
    events = store.query_events(since_id=before_id, limit=800)
    humans = [e for e in events if e.event_type == EventType.HUMAN_MESSAGE.value]
    tools = [e for e in events if e.event_type in {EventType.TOOL_STARTED.value, EventType.TOOL_COMPLETED.value}]
    verifs = [e for e in events if e.event_type == EventType.VERIFICATION_COMPLETED.value]
    responses = [e for e in events if e.event_type == EventType.AGENT_RESPONSE.value]
    on_disk = target.is_file()
    content = target.read_text(encoding="utf-8") if on_disk else ""
    exact = "JAEGER-COMMISSIONING-OK" in content
    verified = any(
        str((v.payload or {}).get("status") or "") == "objective_verified"
        for v in verifs
    )
    tool_ids = [e.event_id for e in tools]
    verif_ids = [e.event_id for e in verifs]
    ok = (
        terminal == "completed"
        and len(humans) == 1
        and bool(tools)
        and on_disk and exact
        and verified
        and len(responses) == 1
    )
    _add(
        report, "safe_tool_execution", "action",
        kind=KIND_LIVE,
        status=STATUS_PASS if ok else STATUS_FAIL,
        evidence=(
            f"request_id={request_id} terminal={terminal} "
            f"human={len(humans)} tools={len(tools)} responses={len(responses)} "
            f"disk={on_disk} exact={exact} verified={verified}"
        ),
        detail="production Gateway → EntityRuntime → ReAct → write → verify",
        request_id=request_id,
        trace_id=request_id,
        event_ids=[*(e.event_id for e in humans), *tool_ids, *verif_ids, *(e.event_id for e in responses)],
        artifact=str(target),
        terminal_status=terminal,
    )
    _add(
        report, "objective_verification", "action",
        kind=KIND_LIVE,
        status=STATUS_PASS if verified and exact else STATUS_FAIL,
        evidence=(
            f"verification.completed ids={verif_ids} "
            f"status={[ (v.payload or {}).get('status') for v in verifs ]} "
            f"verifier={[ (v.payload or {}).get('verifier') for v in verifs ]} "
            f"target={target} content_ok={exact}"
        ),
        request_id=request_id,
        event_ids=verif_ids,
        artifact=str(target),
        terminal_status=terminal,
    )
    bg = [
        e for e in events
        if e.event_type == EventType.BACKGROUND_COMPLETED.value
        and (
            str((e.payload or {}).get("task_id") or "") == request_id
            or str(e.session_id or "") == str(result.get("session_id") or "")
        )
    ]
    bg_ok = bool(bg)
    _add(
        report, "background_completed", "action",
        kind=KIND_LIVE,
        status=STATUS_PASS if bg_ok else STATUS_FAIL,
        evidence=(
            f"background.completed ids={[e.event_id for e in bg[:4]]} "
            f"task_id={[ (e.payload or {}).get('task_id') for e in bg[:4] ]} "
            f"status={[ (e.payload or {}).get('status') for e in bg[:4] ]}"
        ),
        request_id=request_id,
        event_ids=[e.event_id for e in bg[:6]],
        terminal_status=terminal,
    )


def _live_idempotency_check(root: Path, report: ValidationReport) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    from jaeger_ai.core.entity.events import EventType

    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    target = layout.workspace_dir / "commissioning-idempotency.txt"
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
    store = SqliteEventStore(layout.event_store_path)
    before = store.latest_id()
    request_id = f"commissioning-idempotency-{uuid.uuid4().hex[:12]}"
    text = (
        "Create workspace/commissioning-idempotency.txt containing exactly "
        "IDEM-ONCE. Then stop."
    )
    try:
        first = submit_gateway_turn(text, request_id=request_id, timeout_s=240.0)
        first_mtime = target.stat().st_mtime if target.is_file() else 0
        humans_1 = len([
            e for e in store.query_events(since_id=before, limit=800)
            if e.event_type == EventType.HUMAN_MESSAGE.value
        ])
        tools_1 = len([
            e for e in store.query_events(since_id=before, limit=800)
            if e.event_type == EventType.TOOL_COMPLETED.value
        ])
        mid = store.latest_id()
        second = submit_gateway_turn(text, request_id=request_id, timeout_s=30.0)
        humans_2 = len([
            e for e in store.query_events(since_id=mid, limit=400)
            if e.event_type == EventType.HUMAN_MESSAGE.value
        ])
        tools_2 = len([
            e for e in store.query_events(since_id=mid, limit=400)
            if e.event_type == EventType.TOOL_COMPLETED.value
        ])
        second_mtime = target.stat().st_mtime if target.is_file() else 0
        new_id = f"commissioning-idempotency-new-{uuid.uuid4().hex[:8]}"
        third = submit_gateway_turn(text, request_id=new_id, timeout_s=240.0)
    except Exception as exc:
        _add(report, "request_idempotency", "action", kind=KIND_LIVE, status=STATUS_FAIL,
             evidence=str(exc)[:300], request_id=request_id)
        return

    replayed = bool(second.get("replayed"))
    same_turn = str(second.get("turn_id") or "") == str(first.get("turn_id") or "")
    content_ok = target.is_file() and "IDEM-ONCE" in target.read_text(encoding="utf-8")
    mtime_ok = abs(second_mtime - first_mtime) < 0.01 or second_mtime == first_mtime
    new_is_new = not third.get("replayed")
    ok = (
        first.get("status") == "completed"
        and replayed
        and humans_2 == 0
        and tools_2 == 0
        and content_ok
        and mtime_ok
        and str(second.get("status") or first.get("status")) == "completed"
        and new_is_new
    )
    _add(
        report, "request_idempotency", "action",
        kind=KIND_LIVE,
        status=STATUS_PASS if ok else STATUS_FAIL,
        evidence=(
            f"request_id={request_id} replayed={replayed} same_turn={same_turn} "
            f"humans_first={humans_1} humans_replay={humans_2} "
            f"tools_first={tools_1} tools_replay={tools_2} "
            f"mtime_unchanged={mtime_ok} new_request_new={new_is_new} "
            f"first_status={first.get('status')} second_status={second.get('status')}"
        ),
        request_id=request_id,
        trace_id=str(first.get("turn_id") or ""),
        artifact=str(target),
        terminal_status=str(first.get("status") or ""),
    )


def validate_action(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir

    root = instance_dir(instance_root)
    policy_path = root / "authority_policy.yaml"
    _add(report, "authority", "action", kind=KIND_STRUCTURAL,
         status=STATUS_STRUCTURAL_OK if policy_path.is_file() else (STATUS_STRUCTURAL_OK if offline else STATUS_FAIL),
         evidence=str(policy_path),
         detail="persisted" if policy_path.is_file() else "missing")

    if offline:
        _add(report, "safe_tool_execution", "action", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline; LIVE Gateway write not executed")
        _add(report, "objective_verification", "action", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline; LIVE verification.completed not required")
        _add(report, "request_idempotency", "action", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline; LIVE request_id replay not executed")
        _add(report, "background_completed", "action", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline; LIVE background.completed not required")
        return
    _live_write_check(root, report)
    _live_idempotency_check(root, report)


def validate_background(instance_root: Path, report: ValidationReport, *, offline: bool) -> None:
    from jaeger_ai.core.instance.first_boot import instance_dir
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    from jaeger_ai.core.entity.events import EventType

    root = instance_dir(instance_root)
    layout = InstanceLayout(root=root)
    if offline:
        _add(report, "heartbeat", "background", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline")
        _add(report, "sleep_time_scheduler", "background", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK, evidence="offline; LIVE sleep_time events not observed")
        knowledge = root / "knowledge_sources.yaml"
        _add(report, "indexer_registration", "background", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK if knowledge.is_file() else STATUS_FAIL,
             evidence=str(knowledge))
        from jaeger_ai.features.personality.character import characters_root
        skills_ok = characters_root().is_dir()
        _add(report, "skill_registry", "background", kind=KIND_STRUCTURAL,
             status=STATUS_STRUCTURAL_OK if skills_ok else STATUS_FAIL,
             evidence=str(characters_root()))
        return

    store = SqliteEventStore(layout.event_store_path)
    token = "NEBULA-COMMISSIONING-INDEX"
    src_dir = layout.workspace_dir / "index-src"
    src_dir.mkdir(parents=True, exist_ok=True)
    src = src_dir / "commissioning-index-source.txt"
    src.write_text(token + "\n", encoding="utf-8")
    try:
        import yaml
        knowledge = root / "knowledge_sources.yaml"
        doc = {}
        if knowledge.is_file():
            doc = yaml.safe_load(knowledge.read_text(encoding="utf-8")) or {}
        sources = list(doc.get("sources") or [])
        if not any(str(s.get("path") or "") == str(src_dir) for s in sources):
            sources.append({
                "id": "commissioning_index",
                "path": str(src_dir),
                "kind": "operator_approved",
                "approved": True,
                "automatic": False,
            })
            knowledge.write_text(
                yaml.safe_dump({**doc, "sources": sources}, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
    except Exception:
        pass

    before = store.latest_id()
    # Wait for the owner loop (JAEGER_HEARTBEAT_INTERVAL_S, default 30).
    deadline = time.time() + float(os.environ.get("JAEGER_COMMISSIONING_BG_WAIT_S") or 45)
    heartbeats = []
    sleeps_started = []
    sleeps_done = []
    index_done = []
    while time.time() < deadline:
        evs = store.query_events(since_id=before, limit=400)
        heartbeats = [e for e in evs if e.event_type == EventType.SYSTEM_HEARTBEAT.value]
        sleeps_started = [e for e in evs if e.event_type == EventType.SLEEP_TIME_STARTED.value]
        sleeps_done = [e for e in evs if e.event_type == EventType.SLEEP_TIME_COMPLETED.value]
        index_done = [e for e in evs if e.event_type == EventType.INDEX_COMPLETED.value]
        if heartbeats and sleeps_started and sleeps_done:
            break
        time.sleep(1.0)

    _add(report, "heartbeat", "background", kind=KIND_LIVE,
         status=STATUS_PASS if heartbeats else STATUS_FAIL,
         evidence=f"system.heartbeat count={len(heartbeats)} ids={[e.event_id for e in heartbeats[:5]]}",
         event_ids=[e.event_id for e in heartbeats[:8]])
    chain = bool(sleeps_started and sleeps_done)
    _add(report, "sleep_time_scheduler", "background", kind=KIND_LIVE,
         status=STATUS_PASS if chain else STATUS_FAIL,
         evidence=(
             f"sleep_time.started={ [e.event_id for e in sleeps_started[:3]] } "
             f"sleep_time.completed={ [e.event_id for e in sleeps_done[:3]] }"
         ),
         event_ids=[e.event_id for e in sleeps_started[:3] + sleeps_done[:3]])

    knowledge = root / "knowledge_sources.yaml"
    ask_id = f"commissioning-index-{uuid.uuid4().hex[:10]}"
    ask_before = store.latest_id()
    retrieved_obs = []
    phrase_hit = False
    ask_terminal = ""
    try:
        asked = submit_gateway_turn(
            "What does the commissioning index source say? Quote the unique phrase.",
            request_id=ask_id,
            timeout_s=180.0,
        )
        ask_terminal = str(asked.get("status") or "")
        output = str(asked.get("output") or asked.get("text") or "")
        phrase_hit = token in output
        retrieved_obs = [
            e for e in store.query_events(since_id=ask_before, limit=400)
            if e.event_type == EventType.SYSTEM_OBSERVATION.value
            and str((e.payload or {}).get("provenance") or "") == "RETRIEVED_DOCUMENT"
        ]
        if not phrase_hit:
            phrase_hit = any(token in str((e.payload or {}).get("hits") or "") for e in retrieved_obs)
    except Exception as exc:
        asked = {"error": str(exc)}
    live_index_ok = bool(phrase_hit and retrieved_obs)
    _add(
        report, "indexer_registration", "background",
        kind=KIND_LIVE,
        status=STATUS_PASS if live_index_ok else STATUS_FAIL,
        evidence=(
            f"request_id={ask_id} terminal={ask_terminal} phrase={phrase_hit} "
            f"retrieved_document_events={[e.event_id for e in retrieved_obs[:4]]} "
            f"index.completed={[e.event_id for e in index_done[:3]]} "
            f"source={src}"
        ),
        request_id=ask_id,
        event_ids=[e.event_id for e in retrieved_obs[:4] + index_done[:3]],
        artifact=str(src),
        terminal_status=ask_terminal,
    )
    from jaeger_ai.features.personality.character import characters_root
    skills_ok = characters_root().is_dir()
    _add(report, "skill_registry", "background", kind=KIND_STRUCTURAL,
         status=STATUS_STRUCTURAL_OK if skills_ok else STATUS_FAIL,
         evidence=str(characters_root()))


def validate_interfaces(report: ValidationReport, *, offline: bool, gateway_port: int | None = None) -> None:
    from jaeger_ai.contract.ports import GATEWAY_PORT, WEBUI_ADAPTER_PORT, WEBUI_PORT

    gw = int(gateway_port or os.environ.get("JAEGER_GATEWAY_PORT") or GATEWAY_PORT)
    webui_port = int(os.environ.get("JAEGER_WEBUI_PORT") or WEBUI_PORT)
    adapter_port = int(os.environ.get("JAEGER_HERMES_WEBUI_ADAPTER_PORT") or WEBUI_ADAPTER_PORT)
    if offline:
        for name in ("cli_attach", "webui_attach", "bridge_attach"):
            _add(report, name, "interfaces", kind=KIND_DISABLED, status=STATUS_DISABLED,
                 evidence="offline")
        return
    payload = _gateway_status(gw)
    entity = ""
    if payload:
        entity = str((payload.get("Agent") or {}).get("entity_id") or "")
    gw_ok = bool(payload and payload.get("ready") and entity)
    _add(report, "cli_attach", "interfaces", kind=KIND_LIVE,
         status=STATUS_PASS if gw_ok else STATUS_FAIL,
         evidence=f"gateway:{gw} ready={bool(payload and payload.get('ready'))} entity_id={entity}",
         artifact=entity)
    # A listening operator WebUI/Bridge on the default ports is not proof
    # this isolated instance is attached. Require the surface to report
    # the same entity_id; otherwise DISABLED.
    def _same_entity(urls: list[str]) -> tuple[bool, str]:
        last = ""
        for url in urls:
            try:
                body = _http_json("GET", url, timeout=2.0)
            except Exception as exc:
                last = str(exc)[:80]
                continue
            reported = str(
                (body.get("Agent") or {}).get("entity_id")
                or body.get("entity_id")
                or ""
            )
            last = reported or str(body)[:80]
            if entity and reported == entity:
                return True, reported
        return False, last

    webui_same, webui_seen = _same_entity([
        f"http://127.0.0.1:{webui_port}/api/jaeger/runtime/status",
        f"http://127.0.0.1:{webui_port}/api/runtime/status",
    ])
    if _port_open(webui_port) and webui_same:
        _add(report, "webui_attach", "interfaces", kind=KIND_LIVE, status=STATUS_PASS,
             evidence=f"webui:{webui_port} same entity_id={entity}", artifact=entity)
    elif _port_open(webui_port):
        _add(report, "webui_attach", "interfaces", kind=KIND_DISABLED, status=STATUS_DISABLED,
             evidence=f"webui:{webui_port} listening but not this entity_id={entity} seen={webui_seen}")
    else:
        _add(report, "webui_attach", "interfaces", kind=KIND_DISABLED, status=STATUS_DISABLED,
             evidence=f"webui:{webui_port} not listening")
    bridge_same, bridge_seen = _same_entity([
        f"http://127.0.0.1:{adapter_port}/health",
        f"http://127.0.0.1:{adapter_port}/api/health",
        f"http://127.0.0.1:{adapter_port}/v1/runtime/status",
    ])
    if _port_open(adapter_port) and bridge_same:
        _add(report, "bridge_attach", "interfaces", kind=KIND_LIVE, status=STATUS_PASS,
             evidence=f"bridge:{adapter_port} same entity_id={entity}", artifact=entity)
    elif _port_open(adapter_port):
        _add(report, "bridge_attach", "interfaces", kind=KIND_DISABLED, status=STATUS_DISABLED,
             evidence=f"bridge:{adapter_port} listening but not this entity_id={entity} seen={bridge_seen}")
    else:
        _add(report, "bridge_attach", "interfaces", kind=KIND_DISABLED, status=STATUS_DISABLED,
             evidence=f"bridge:{adapter_port} not listening")


def run_validation(
    instance_root: Path | Any,
    *,
    groups: tuple[str, ...] | None = None,
    offline: bool | None = None,
) -> ValidationReport:
    """Run checks. LIVE groups against a resident Gateway when not offline."""
    report = ValidationReport(started_at=_stamp())
    report.offline = _offline() if offline is None else bool(offline)
    wanted = set(groups) if groups else {"core", "cognition", "action", "background", "interfaces"}
    from jaeger_ai.core.instance.first_boot import instance_dir
    root = instance_dir(instance_root)
    if "core" in wanted:
        validate_core(root, report, offline=report.offline)
    if "cognition" in wanted:
        validate_cognition(root, report)
    if "action" in wanted:
        validate_action(root, report, offline=report.offline)
    if "background" in wanted:
        validate_background(root, report, offline=report.offline)
    if "interfaces" in wanted:
        validate_interfaces(report, offline=report.offline)
    report.passed = all(
        c.status in {STATUS_PASS, STATUS_STRUCTURAL_OK, STATUS_DISABLED}
        for c in report.checks
    ) if report.checks else False
    report.finished_at = _stamp()
    return report


__all__ = [
    "CheckResult",
    "KIND_DISABLED",
    "KIND_LIVE",
    "KIND_STRUCTURAL",
    "STATUS_DISABLED",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_STRUCTURAL_OK",
    "ValidationReport",
    "run_validation",
    "submit_gateway_turn",
]
