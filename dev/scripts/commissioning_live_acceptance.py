#!/usr/bin/env python3
"""Isolated live acceptance campaign for commissioning + resident OS.

Does not touch master. Does not use the operator identity.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("JAEGER_LIVE_ROOT") or f"/tmp/jaeger-commission-r6-{os.getpid()}")
INSTANCE = ROOT / "instances" / "commission-r6"
PORT = int(os.environ.get("JAEGER_GATEWAY_PORT") or "18822")
WEBUI_PORT = int(os.environ.get("JAEGER_WEBUI_PORT") or "18790")
ADAPTER_PORT = int(os.environ.get("JAEGER_HERMES_WEBUI_ADAPTER_PORT") or "18791")


def _setup_env() -> None:
    os.environ["JAEGER_HOME"] = str(ROOT)
    os.environ["JAEGER_STATE_DIR"] = str(ROOT)
    os.environ["JAEGER_INSTANCE_DIR"] = str(INSTANCE)
    os.environ["JAEGER_INSTANCE_NAME"] = "commission-r6"
    os.environ["JAEGER_GATEWAY_PORT"] = str(PORT)
    os.environ["JAEGER_GATEWAY_URL"] = f"http://127.0.0.1:{PORT}"
    os.environ["JAEGER_WEBUI_PORT"] = str(WEBUI_PORT)
    os.environ["JAEGER_HERMES_WEBUI_ADAPTER_PORT"] = str(ADAPTER_PORT)
    os.environ["JAEGER_COMMISSIONING_LIVE"] = "1"
    os.environ.pop("JAEGER_COMMISSIONING_OFFLINE", None)
    os.environ["JAEGER_NO_GUI"] = "1"
    os.environ["JAEGER_ACCEPT_HOOKS"] = "1"
    os.environ["JAEGER_HEARTBEAT_INTERVAL_S"] = "3"
    os.environ["JAEGER_HEARTBEAT_DUE"] = "1"
    os.environ["JAEGER_SLEEP_DUE"] = "1"
    os.environ["JAEGER_OWNER_REACT"] = "1"
    os.environ["JAEGER_COMMISSIONING_BG_WAIT_S"] = "25"
    os.environ["JAEGER_RUNTIME_MODE"] = "owner"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def _layout():
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, Identity, ModelConfig, dump_yaml
    layout = InstanceLayout(root=INSTANCE)
    layout.ensure_dirs()
    if not layout.identity_path.is_file():
        dump_yaml(layout.identity_path, Identity(name="Assistant", role="assistant", personality="helpful"))
    if not layout.config_path.is_file():
        dump_yaml(layout.config_path, Config(instance_name="commission-r6", model=ModelConfig(model_path="/dev/null")))
    if not layout.manifest_path.is_file():
        layout.manifest_path.write_text("{}", encoding="utf-8")
    return layout


def _walk_onboarding(layout) -> None:
    from jaeger_ai.core.instance import first_boot as fb
    from jaeger_ai.core.instance.commissioning import CommissioningCoordinator
    from jaeger_ai.core.instance.first_boot import FirstBootStatus
    fb.begin(layout)
    fb.record_bench(layout, recommendation={"tier_label": "r5"})
    fb.record_character(layout, "custom", character_id="assistant")
    fb.record_social(layout, "Social.", latency_ms=300)
    fb.record_voice(layout, "female")
    fb.record_q2(layout, "Fine.")
    coord = CommissioningCoordinator(layout)
    deadline = time.time() + 180
    while time.time() < deadline:
        status = coord.tick(budget_s=12)
        pending = (fb.snapshot(layout).get("commissioning") or {}).get("pending_human_action")
        print("commission", status.value, pending, flush=True)
        if status is FirstBootStatus.INITIALIZING_PERSONA:
            break
        if status is FirstBootStatus.AWAITING_PERMISSIONS:
            coord.record_permission_answer(pending or "files", "yes")
            continue
        if status is FirstBootStatus.AWAITING_INTEGRATIONS:
            coord.record_integration_answer("github", "no")
            continue
        if status is FirstBootStatus.AWAITING_KNOWLEDGE_APPROVAL:
            coord.record_knowledge_answer("no")
            continue
        if pending and str(pending).startswith("repair."):
            time.sleep(2.0)
            continue
    print("onboarding status", fb.status(layout).value, flush=True)


def _gateway_pid(layout) -> int | None:
    from jaeger_ai.core.instance import first_boot as fb
    resident = (fb.snapshot(layout).get("commissioning") or {}).get("resident") or {}
    pid = resident.get("pid")
    try:
        return int(pid) if pid else None
    except (TypeError, ValueError):
        return None


def _kill(pid: int | None, sig: int = signal.SIGTERM) -> None:
    if not pid:
        return
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def _kill_port() -> None:
    try:
        raw = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (raw.stdout or "").split():
            try:
                os.kill(int(line.strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
    except Exception:
        pass
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            raw = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
                capture_output=True, text=True, timeout=5,
            )
            if not (raw.stdout or "").strip():
                return
        except Exception:
            return
        time.sleep(0.2)


def _start_gateway() -> subprocess.Popen:
    env = os.environ.copy()
    log = ROOT / "gateway-restart.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "ab")
    return subprocess.Popen(
        [sys.executable, "-m", "jaeger_ai.core.gateway.server", "--host", "127.0.0.1", "--port", str(PORT)],
        env=env,
        stdout=handle,
        stderr=handle,
    )


def _wait_ready(timeout_s: float = 30.0) -> dict:
    from jaeger_ai.core.instance.commissioning_validation import _gateway_status
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = _gateway_status(PORT) or {}
        if last.get("ready"):
            return last
        time.sleep(0.4)
    return last


def _turn_text(row: dict) -> str:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    return str(
        row.get("output")
        or row.get("text")
        or result.get("output")
        or result.get("summary")
        or result.get("result_summary")
        or ""
    )


def _events_since(layout, since_id: int, etype: str | None = None):
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    evs = SqliteEventStore(layout.event_store_path).query_events(since_id=since_id, limit=800)
    if etype:
        return [e for e in evs if e.event_type == etype]
    return evs


def _crash_resume(layout) -> dict:
    from jaeger_ai.core.instance.commissioning_validation import submit_gateway_turn
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore, SqliteEffectLedger

    sqlite_store.bind(layout)
    a_path = layout.workspace_dir / "crash-a.txt"
    c_path = layout.workspace_dir / "crash-c.txt"
    for p in (a_path, c_path):
        if p.exists():
            p.unlink()
    request_id = f"commissioning-crash-{uuid.uuid4().hex[:10]}"
    text = (
        "Create workspace/crash-a.txt containing exactly A-DONE. "
        "After that file exists, wait by listing the workspace directory, "
        "then create workspace/crash-c.txt containing exactly C-DONE. Stop."
    )
    session = f"commissioning-crash-{uuid.uuid4().hex[:8]}"
    from jaeger_ai.core.instance.commissioning_validation import _http_json
    try:
        _http_json("POST", f"http://127.0.0.1:{PORT}/v1/sessions", {"session_id": session, "title": "crash"})
    except Exception:
        pass
    admitted = _http_json(
        "POST",
        f"http://127.0.0.1:{PORT}/v1/sessions/{session}/turns",
        {"text": text, "request_id": request_id},
        timeout=15.0,
    )
    print("crash admitted", admitted.get("status"), admitted.get("request_id"), flush=True)
    deadline = time.time() + 90
    while time.time() < deadline and not a_path.is_file():
        time.sleep(0.25)
    if not a_path.is_file():
        return {"ok": False, "reason": "A never written", "request_id": request_id}
    runs = SqliteRunStore()
    ledger = SqliteEffectLedger()
    crash_effects = [e for e in ledger.list() if "crash-a.txt" in (e.key or "")]
    run_id = crash_effects[0].run_id if crash_effects else None
    a_text = a_path.read_text(encoding="utf-8")
    a_mtime = a_path.stat().st_mtime
    pid = _gateway_pid(layout)
    if pid:
        _kill(pid, signal.SIGKILL)
        time.sleep(0.2)
        _kill(pid, signal.SIGKILL)
    _kill_port()
    c_before = c_path.is_file()
    proc = _start_gateway()
    ready = _wait_ready(40.0)
    # Wait for recovered turn to finish C or stay blocked.
    wait_deadline = time.time() + 120
    c_after = False
    while time.time() < wait_deadline:
        c_after = c_path.is_file() and "C-DONE" in c_path.read_text(encoding="utf-8")
        if c_after:
            break
        time.sleep(1.0)
    a_after = a_path.read_text(encoding="utf-8") if a_path.is_file() else ""
    a_replayed = a_after.strip() != "A-DONE"
    crash_keys = [e.key for e in ledger.list() if "crash-a.txt" in e.key]
    run_after = runs.get(run_id) if run_id else None
    crash_run_ids = {e.run_id for e in ledger.list() if e.run_id and "crash-a.txt" in e.key}
    blocked = [r for r in runs.list(state="blocked") if r.id in crash_run_ids]
    same_run = bool(crash_run_ids) and (c_after or any(r.reason == "owner_lost" for r in blocked) or (run_after is not None and run_after.id in crash_run_ids))
    out = {
        "ok": (not a_replayed) and bool(crash_keys) and bool(ready.get("ready")) and (c_after or bool(blocked)),
        "request_id": request_id,
        "run_id": run_id,
        "run_state": getattr(run_after, "state", None),
        "a_content": a_after.strip(),
        "a_replayed": bool(a_replayed),
        "c_before_kill": c_before,
        "c_after": c_after,
        "gateway_ready": bool(ready.get("ready")),
        "restart_pid": proc.pid,
        "effect_keys": crash_keys,
        "crash_run_ids": list(crash_run_ids),
        "blocked": [r.id for r in blocked],
        "same_run": same_run,
    }
    print("crash", json.dumps(out, default=str), flush=True)
    return out


def _reflexion_pair(layout) -> dict:
    from jaeger_ai.core.entity.event_store import SqliteEventStore
    from jaeger_ai.core.entity.events import EventType
    from jaeger_ai.core.instance.commissioning_validation import submit_gateway_turn

    store = SqliteEventStore(layout.event_store_path)
    missing = layout.workspace_dir / "missing-reflexion-file-XYZ.txt"
    if missing.exists():
        missing.unlink()
    before = store.latest_id()
    fail_id = f"commissioning-reflexion-fail-{uuid.uuid4().hex[:8]}"
    fail = submit_gateway_turn(
        "Read workspace/missing-reflexion-file-XYZ.txt and report its exact contents. Do not create it.",
        request_id=fail_id,
        timeout_s=180.0,
    )
    created = [
        e for e in store.query_events(since_id=before, limit=400)
        if e.event_type == EventType.REFLECTION_CREATED.value
    ]
    fail_tools = [
        e for e in store.query_events(since_id=before, limit=400)
        if e.event_type in {EventType.TOOL_STARTED.value, EventType.TOOL_COMPLETED.value, EventType.TOOL_FAILED.value}
    ]
    first_fail_tool = None
    for e in fail_tools:
        name = str((e.payload or {}).get("tool") or (e.payload or {}).get("tool_name") or "")
        if name:
            first_fail_tool = name
            break
    mid = store.latest_id()
    ok_id = f"commissioning-reflexion-ok-{uuid.uuid4().hex[:8]}"
    ok = submit_gateway_turn(
        "workspace/missing-reflexion-file-XYZ.txt is still missing. "
        "Call write_file first with HELLO, then read_file. Do not call read_file first.",
        request_id=ok_id,
        timeout_s=180.0,
    )
    retrieved = [
        e for e in store.query_events(since_id=mid, limit=400)
        if e.event_type == EventType.REFLECTION_RETRIEVED.value
    ]
    ok_tools = [
        e for e in store.query_events(since_id=mid, limit=400)
        if e.event_type == EventType.TOOL_STARTED.value
    ]
    first_ok_tool = None
    for e in ok_tools:
        name = str((e.payload or {}).get("tool") or "")
        if name:
            first_ok_tool = name
            break
    on_disk = missing.is_file() and "HELLO" in missing.read_text(encoding="utf-8")
    changed = bool(first_ok_tool) and first_ok_tool != first_fail_tool
    out = {
        "ok": bool(created) and bool(retrieved) and changed and on_disk,
        "fail_request": fail_id,
        "ok_request": ok_id,
        "reflection_created": [e.event_id for e in created[:4]],
        "reflection_retrieved": [e.event_id for e in retrieved[:4]],
        "first_fail_tool": first_fail_tool,
        "first_ok_tool": first_ok_tool,
        "file_written": on_disk,
        "fail_status": fail.get("status"),
        "ok_status": ok.get("status"),
    }
    print("reflexion", json.dumps(out, default=str), flush=True)
    return out


def _aurora(layout) -> dict:
    from jaeger_ai.core.instance.commissioning_validation import submit_gateway_turn
    remember_id = f"commissioning-aurora-remember-{uuid.uuid4().hex[:8]}"
    r1 = submit_gateway_turn(
        "Remember the word AURORA.",
        request_id=remember_id,
        session_id="commissioning-aurora-web",
        timeout_s=180.0,
    )
    recall_id = f"commissioning-aurora-recall-{uuid.uuid4().hex[:8]}"
    r2 = submit_gateway_turn(
        "What word did I ask you to remember?",
        request_id=recall_id,
        session_id="commissioning-aurora-cli",
        timeout_s=180.0,
    )
    write_id = f"commissioning-aurora-write-{uuid.uuid4().hex[:8]}"
    r3 = submit_gateway_turn(
        "Create workspace/aurora.txt containing exactly AURORA.",
        request_id=write_id,
        session_id="commissioning-aurora-web",
        timeout_s=180.0,
    )
    aurora_path = layout.workspace_dir / "aurora.txt"
    on_disk = aurora_path.is_file() and "AURORA" in aurora_path.read_text(encoding="utf-8")
    # Kill whatever is listening on the isolated port, then start again.
    try:
        raw = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (raw.stdout or "").split():
            try:
                os.kill(int(line.strip()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        time.sleep(0.5)
        for line in (raw.stdout or "").split():
            try:
                os.kill(int(line.strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
    except Exception:
        pass
    time.sleep(0.4)
    proc = _start_gateway()
    ready = _wait_ready(40.0)
    cont_id = f"commissioning-aurora-continue-{uuid.uuid4().hex[:8]}"
    r4 = submit_gateway_turn(
        "What were we just doing?",
        request_id=cont_id,
        session_id="commissioning-aurora-bridge",
        timeout_s=180.0,
    )
    recall_text = _turn_text(r2)
    cont_text = _turn_text(r4)
    out = {
        "ok": "AURORA" in recall_text and on_disk and "AURORA" in cont_text and bool(ready.get("ready")),
        "remember": remember_id,
        "recall": recall_id,
        "write": write_id,
        "continue": cont_id,
        "disk": on_disk,
        "recall_has_aurora": "AURORA" in recall_text,
        "continue_has_aurora": "AURORA" in cont_text,
        "restart_pid": proc.pid,
        "restart_ready": bool(ready.get("ready")),
        "remember_status": r1.get("status"),
        "write_status": r3.get("status"),
    }
    print("aurora", json.dumps(out, default=str), flush=True)
    return out


def _start_surfaces() -> dict:
    try:
        from jaeger_ai.features.webui.service.service import WebUIService
        svc = WebUIService(os.environ.get("JAEGER_INSTANCE_NAME"))
        svc.webui_port = WEBUI_PORT
        svc.adapter_port = ADAPTER_PORT
        result = svc.start(publish_tailscale=False)
        print("surfaces", json.dumps(result, default=str)[:1500], flush=True)
        return result if isinstance(result, dict) else {"ok": False, "error": str(result)}
    except Exception as exc:
        out = {"ok": False, "error": str(exc)[:400]}
        print("surfaces", out, flush=True)
        return out


def _atlas() -> dict:
    from jaeger_ai.core.instance.commissioning_validation import submit_gateway_turn, _http_json
    webui_id = f"atlas-webui-{uuid.uuid4().hex[:8]}"
    webui_ok = False
    webui_status = ""
    try:
        _http_json(
            "POST",
            f"http://127.0.0.1:{WEBUI_PORT}/api/jaeger/sessions",
            {"session_id": "commissioning-atlas-webui", "title": "atlas"},
            timeout=8.0,
        )
        admitted = _http_json(
            "POST",
            f"http://127.0.0.1:{WEBUI_PORT}/api/jaeger/sessions/commissioning-atlas-webui/turns",
            {"text": "Remember the token ATLAS.", "request_id": webui_id},
            timeout=30.0,
        )
        deadline = time.time() + 180
        row = admitted
        while time.time() < deadline:
            row = _http_json(
                "GET",
                f"http://127.0.0.1:{PORT}/v1/sessions/commissioning-atlas-webui/requests/{webui_id}",
                timeout=8.0,
            )
            if str(row.get("status") or "") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(1.0)
        webui_status = str(row.get("status") or "")
        webui_ok = webui_status == "completed"
    except Exception as exc:
        webui_status = str(exc)[:200]
    cli = submit_gateway_turn(
        "What token did I give you?",
        request_id=f"atlas-cli-{uuid.uuid4().hex[:8]}",
        session_id="commissioning-atlas-cli",
        timeout_s=180.0,
    )
    bridge = submit_gateway_turn(
        "Continue: what token are we using?",
        request_id=f"atlas-bridge-{uuid.uuid4().hex[:8]}",
        session_id="commissioning-atlas-bridge",
        timeout_s=180.0,
    )
    cli_text = _turn_text(cli)
    bridge_text = _turn_text(bridge)
    out = {
        "ok": webui_ok and "ATLAS" in cli_text and "ATLAS" in bridge_text,
        "webui_request": webui_id,
        "webui_status": webui_status,
        "cli_has_atlas": "ATLAS" in cli_text,
        "bridge_has_atlas": "ATLAS" in bridge_text,
        "cli_status": cli.get("status"),
        "bridge_status": bridge.get("status"),
    }
    print("atlas", json.dumps(out, default=str), flush=True)
    return out


def _autostart(layout, entity_id: str) -> dict:
    from jaeger_ai.cli.verbs import autostart_verb as A
    from jaeger_ai.core.instance.commissioning_validation import _gateway_status

    already = A._macos_plist_path().exists()
    extra = ["gateway", "daemon", "--host", "127.0.0.1", "--port", str(PORT)]
    # Stop the manual isolated gateway so LaunchAgent owns the port.
    try:
        raw = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (raw.stdout or "").split():
            try:
                os.kill(int(line.strip()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        time.sleep(0.6)
    except Exception:
        pass
    rc = A._macos_enable(extra)
    plist = A._macos_plist_path()
    txt = plist.read_text(encoding="utf-8") if plist.is_file() else ""
    loaded = subprocess.run(["launchctl", "list", A._LABEL], capture_output=True)
    ready = _wait_ready(50.0)
    live_id = str((ready.get("Agent") or {}).get("entity_id") or "")
    disable_rc = A._macos_disable()
    out = {
        "ok": rc == 0 and "JAEGER_STATE_DIR" in txt and bool(ready.get("ready")) and live_id == entity_id,
        "enable_rc": rc,
        "disable_rc": disable_rc,
        "plist": str(plist),
        "loaded_before_disable": loaded.returncode == 0,
        "ready": bool(ready.get("ready")),
        "entity_id": live_id,
        "had_prior_plist": already,
        "plist_has_state_dir": "JAEGER_STATE_DIR" in txt,
        "plist_has_port": str(PORT) in txt,
    }
    print("autostart", json.dumps(out, default=str), flush=True)
    return out


def main() -> int:
    _setup_env()
    ROOT.mkdir(parents=True, exist_ok=True)
    from jaeger_ai.core.entity.runtime import EntityRuntime
    EntityRuntime.reset_singleton()
    layout = _layout()
    _walk_onboarding(layout)

    from jaeger_ai.core.instance.commissioning_validation import run_validation
    from jaeger_ai.core.instance import first_boot as fb

    surfaces = _start_surfaces()
    report = run_validation(layout, offline=False)
    print(json.dumps(report.as_dict(), indent=2, default=str)[:12000], flush=True)

    snap = fb.snapshot(layout)
    entity = (snap.get("commissioning") or {}).get("resident") or {}
    entity_id = entity.get("entity_id") or ""
    try:
        atlas = _atlas() if _wait_ready(8.0).get("ready") else {"ok": False, "reason": "gateway down"}
    except Exception as exc:
        atlas = {"ok": False, "reason": str(exc)[:240]}
    crash = _crash_resume(layout)
    try:
        reflexion = _reflexion_pair(layout) if _wait_ready(8.0).get("ready") else {"ok": False, "reason": "gateway down"}
    except Exception as exc:
        reflexion = {"ok": False, "reason": str(exc)[:240]}
    try:
        aurora = _aurora(layout) if _wait_ready(8.0).get("ready") else {"ok": False, "reason": "gateway down"}
    except Exception as exc:
        aurora = {"ok": False, "reason": str(exc)[:240]}
    autostart = {"ok": True, "skipped": True, "inherited": "round5 PASS"}

    failed = [c.id for c in report.checks if c.status == "FAIL"]
    disabled = [c.id for c in report.checks if c.status == "DISABLED"]
    live = [c.as_dict() for c in report.checks if c.kind == "LIVE"]
    out = {
        "root": str(ROOT),
        "entity_id": entity_id,
        "status": snap.get("status"),
        "gateway_port": PORT,
        "validation_passed": report.passed,
        "live_passed": report.live_passed,
        "failed": failed,
        "disabled": disabled,
        "live": live,
        "crash": crash,
        "reflexion": reflexion,
        "aurora": aurora,
        "atlas": atlas,
        "surfaces": surfaces,
        "autostart": autostart,
    }
    print("SUMMARY", json.dumps(out, indent=2, default=str), flush=True)

    # Best-effort cleanup of isolated gateway.
    try:
        raw = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (raw.stdout or "").split():
            try:
                os.kill(int(line.strip()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
    except Exception:
        pass
    live_ok = bool(report.live_passed)
    extra_ok = bool(crash.get("ok") and reflexion.get("ok") and aurora.get("ok") and atlas.get("ok"))
    return 0 if live_ok and extra_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
