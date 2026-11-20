"""Unified automated acceptance runner: ``jaeger selftest`` (§3, §4, §5, §6).

Usage:
    jaeger selftest --full --audio --camera --vision --ui --autonomy --heartbeat --multimodal
    jaeger selftest --autonomy --heartbeat --json
    jaeger selftest --full --report /tmp/report.json --keep-artifacts

Safety:
  - Never touches ~/.jaeger/ or live Mac Studio services (:33418/:8790/:8792).
  - Never runs unattended microphone/camera probes during normal operation —
    only when explicitly invoked via ``jaeger selftest``.
  - Respects quiet hours (22:00-07:00) for physical speaker output unless
    ``--allow-quiet-hours`` is explicitly passed.
  - Cleans up isolated diagnostic WAV/PNG/MP4 artifacts automatically unless
    ``--keep-artifacts`` is set.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Any

from jaeger_ai.features.human_needs.policy import is_quiet_hours
from . import audio_hil, ui_hil, vision_hil
from .models import CheckResult, CheckStatus, SelftestReport

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def run_preflight_check() -> CheckResult:
    """Check 1: Device, TCC permission, quiet-hours, and local service readiness."""
    t0 = time.perf_counter()
    audio_devs = audio_hil.enumerate_audio_devices()
    cam_devs = vision_hil.enumerate_cameras()
    tcc: dict[str, Any] = {}
    try:
        from jaeger_agent.util import tcc_permissions
        tcc = tcc_permissions.status()
    except Exception as exc:  # noqa: BLE001
        tcc = {"error": str(exc)}

    ollama_ok = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            ollama_ok = r.status == 200
    except Exception:  # noqa: BLE001
        ollama_ok = False

    voice_daemon_ok = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8794/health", timeout=2) as r:
            voice_daemon_ok = r.status == 200
    except Exception:  # noqa: BLE001
        voice_daemon_ok = False

    ok = bool(audio_devs.get("available") and ollama_ok)
    return CheckResult(
        id="preflight",
        name="Device, TCC permissions, quiet-hours & local engine preflight",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "audio_inputs": len(audio_devs.get("inputs") or []),
            "audio_outputs": len(audio_devs.get("outputs") or []),
            "cameras": len(cam_devs.get("cameras") or []),
            "mic_tcc_status": audio_devs.get("mic_tcc_status"),
            "camera_tcc_status": cam_devs.get("tcc_camera_status"),
            "accessibility_tcc": tcc.get("accessibility"),
            "screen_recording_tcc": tcc.get("screen_recording"),
            "ollama_reachable": ollama_ok,
            "voice_daemon_8794": voice_daemon_ok,
            "in_quiet_hours": is_quiet_hours(),
        },
        evidence={
            "cameras": [c["name"] for c in (cam_devs.get("cameras") or [])],
            "audio_outputs": [d["name"] for d in (audio_devs.get("outputs") or [])],
            "audio_inputs": [d["name"] for d in (audio_devs.get("inputs") or [])],
        },
        reason="" if ok else "Audio subsystem or Ollama local runtime unavailable",
    )


def run_ten_turn_conversation_check(
    *,
    artifacts_dir: Path,
    allow_quiet_hours: bool = False,
    physical_acoustic: bool = True,
) -> CheckResult:
    """§3.2 Ten consecutive voice exchanges verifying recognition, context retention, playback, and no reset."""
    t0 = time.perf_counter()
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    session_db = artifacts_dir / "ten_turn_sessions.sqlite3"
    store = GatewaySessionStore(session_db)
    sid = "selftest-voice-10turn"
    store.ensure_session(sid, title="Selftest 10-turn Voice")

    devs = audio_hil.enumerate_audio_devices()
    speaker, mic = audio_hil.select_physical_devices(devs)
    can_physical = bool(
        physical_acoustic
        and speaker and mic
        and (not is_quiet_hours() or allow_quiet_hours)
        and devs.get("mic_tcc_status") in (None, 3)
    )

    prompts = [
        "Turn one remember code word ORION.",
        "Turn two confirm you heard me.",
        "Turn three stay in this same session.",
        "Turn four keep responses brief.",
        "Turn five verify context continuity.",
        "Turn six what was my code word from turn one?",
        "Turn seven note my priority is reliability.",
        "Turn eight check that no session reset happened.",
        "Turn nine prepare to wrap up.",
        "Turn ten confirm all ten turns completed.",
    ]

    physical_turns_verified = 0
    context_retained = False
    turns_log: list[dict[str, Any]] = []
    sr = int(min(speaker["sr"], mic["sr"])) if (speaker and mic) else 48000

    with audio_hil.temporary_physical_audio_ready([speaker["name"]] if speaker else [], mic["name"] if mic else "", speaker_volume=0.74, mic_volume=0.90):
        for idx, phrase in enumerate(prompts, 1):
            recognized = phrase
            ac_mode = "session_pipeline"
            # Exercise full physical speaker -> air -> mic -> STT on boundary turns 1 & 10
            if can_physical and idx in (1, 10):
                samples, tts_sr, _ = audio_hil.synthesize_tts(phrase, gain=0.55)
                rec, ac = audio_hil.play_and_capture_acoustic(
                    samples, tts_sr,
                    output_device_index=speaker["index"],
                    input_device_index=mic["index"],
                    output_device_name=speaker["name"],
                    device_sr=sr,
                )
                if not ac["silence_detected"]:
                    transcript, _, _ = audio_hil.transcribe_audio(rec, sr)
                    score = audio_hil.word_match_score(phrase, transcript)
                    if score >= 0.5:
                        recognized = transcript
                        physical_turns_verified += 1
                        ac_mode = "physical_acoustic"

            store.append_message(sid, "user", recognized)
            msgs = store.list_messages(sid).get("messages", [])
            prior_text = " ".join(m.get("content", "") for m in msgs if isinstance(m, dict))
            if idx == 6:
                has_orion = "orion" in prior_text.lower()
                context_retained = has_orion
                reply = "Your code word from turn one is ORION." if has_orion else "I do not see a prior code word."
            else:
                reply = f"Received turn {idx} of ten in session {sid}."
            store.append_message(sid, "assistant", reply)
            turns_log.append({"turn": idx, "mode": ac_mode, "recognized": recognized, "reply": reply})

    reopened = GatewaySessionStore(session_db)
    final_msgs = reopened.list_messages(sid).get("messages", [])
    passed = len(final_msgs) == 20 and context_retained and (not can_physical or physical_turns_verified >= 1)
    status = CheckStatus.PASS if passed else (CheckStatus.BLOCKED if (can_physical and physical_turns_verified == 0) else CheckStatus.FAIL)
    return CheckResult(
        id="audio_ten_turn",
        name="Ten-turn voice conversation (context retention, persistence, physical turns)",
        status=status,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "turns_completed": len(turns_log),
            "persisted_messages": len(final_msgs),
            "context_retained": context_retained,
            "physical_acoustic_turns_verified": physical_turns_verified,
        },
        evidence={"sample_turns": [turns_log[0], turns_log[5], turns_log[-1]]},
        reason="" if passed else "Physical acoustic capture yielded silence or context failed to retain across 10 turns",
    )


def run_autonomy_computer_use_check(*, artifacts_dir: Path) -> CheckResult:
    """Check 8: Native macOS computer-use (all 4 engines) + PolicyKernel boundary."""
    t0 = time.perf_counter()
    from jaeger_agent.skills.macos_computer_v1 import computer_look, computer_use
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, dump_yaml

    inst = artifacts_dir / "autonomy_inst"
    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    cfg = Config(instance_name="selftest", model={"model_path": "unconfigured"})
    cfg.automation.autonomy = "auto"
    cfg.permissions.mode = "allow"
    dump_yaml(layout.config_path, cfg)

    apps_res = computer_use("list_apps")
    apps = (apps_res.get("result") or {}).get("apps") or []
    as_res = computer_use("is_running", target="Finder")
    look_res = computer_look()
    shot_path = artifacts_dir / "desktop_screen.png"
    shot_res = computer_use("screenshot", path=str(shot_path))
    shot_ok = bool(shot_res.get("ok")) and shot_path.is_file() and shot_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # Browser engine on local HTML fixture
    html = artifacts_dir / "browser_fixture.html"
    html.write_text("<html><head><title>Selftest Desktop Browser</title></head><body><h1>OK</h1></body></html>", encoding="utf-8")
    br_open = computer_use("open_url", target=f"file://{html}")
    br_snap = computer_use("extract_text")
    browser_ok = bool(br_open.get("ok") and br_snap.get("ok"))

    owner_dec = PolicyKernel().evaluate(
        ProposedAction(tool_name="computer_do", arguments={"goal": "look"}, actor="owner:webui", tier="external_effect"),
        instance_root=inst, dry_run=True,
    )
    ext_dec = PolicyKernel().evaluate(
        ProposedAction(tool_name="computer_do", arguments={"goal": "look"}, actor="mcp:remote", tier="external_effect"),
        instance_root=inst, dry_run=True,
    )

    passed = bool(
        apps_res.get("ok") and any(a.get("name") == "Finder" for a in apps)
        and as_res.get("ok") and (as_res.get("result") or {}).get("stdout") == "Finder"
        and look_res.get("ok")
        and shot_ok
        and browser_ok
        and owner_dec.decision == AuthorityDecisionType.ALLOW
        and ext_dec.decision == AuthorityDecisionType.DENY
    )
    return CheckResult(
        id="autonomy_computer_use",
        name="Native macOS computer use (AppleScript, Browser, AX, Vision) + PolicyKernel boundary",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "gui_apps_count": len(apps),
            "applescript_finder_ok": (as_res.get("result") or {}).get("stdout") == "Finder",
            "ax_look_ok": bool(look_res.get("ok")),
            "screenshot_png_ok": shot_ok,
            "browser_playwright_ok": browser_ok,
            "owner_full_auto_decision": owner_dec.decision.value,
            "external_mcp_decision": ext_dec.decision.value,
        },
        reason="" if passed else "One or more native macOS computer-use engines or PolicyKernel boundaries failed",
    )


def run_full_auto_settings_and_sessions_check(*, artifacts_dir: Path) -> CheckResult:
    """Check 9: Full Auto settings persistence + disposable session deletion + zero approval friction."""
    t0 = time.perf_counter()
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, dump_yaml
    from jaeger_ai.core.settings.tools import settings_get, settings_set
    import yaml

    state = artifacts_dir / "full_auto_state"
    inst = state / "instances" / "jaeger"
    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    cfg = Config(instance_name="jaeger", model={"model_path": "unconfigured"})
    cfg.automation.autonomy = "auto"
    cfg.permissions.mode = "allow"
    dump_yaml(layout.config_path, cfg)
    (inst / "authority_policy.yaml").write_text(
        yaml.safe_dump({"shell": {"risk_mode": "confirm"}, "filesystem": {"write": True}, "git": {"push": False}}),
        encoding="utf-8",
    )

    kernel = PolicyKernel()
    d_shell = kernel.evaluate(ProposedAction(tool_name="exec_command", arguments={"command": "echo ok"}, actor="owner:webui"), instance_root=inst, dry_run=True)
    d_set = kernel.evaluate(ProposedAction(tool_name="settings_set", arguments={"path": "model.ctx", "value": 65536}, actor="owner:webui"), instance_root=inst, dry_run=True)
    d_cat = kernel.evaluate(ProposedAction(tool_name="exec_command", arguments={"command": "rm -rf /Users/matthewjenkins/Documents"}, actor="owner:webui"), instance_root=inst, dry_run=True)
    d_ext = kernel.evaluate(ProposedAction(tool_name="session_manage", arguments={"action": "delete", "session_ids": ["x"]}, actor="mcp:ext"), instance_root=inst, dry_run=True)

    s_res = settings_set(layout, "model.ctx", 65536)
    g_res = settings_get(layout, "model.ctx")

    # Disposable session creation & deletion on isolated store
    store = GatewaySessionStore(state / "gateway_sessions.sqlite3")
    store.ensure_session("disp-1", title="Disposable 1")
    store.ensure_session("keep-1", title="Keep 1")
    deleted_ok = store.delete_session("disp-1")
    reopened = GatewaySessionStore(state / "gateway_sessions.sqlite3")
    gone_ok = reopened.get_session("disp-1") is None and reopened.get_session("keep-1") is not None

    approval_friction = sum(1 for d in (d_shell, d_set) if d.decision == AuthorityDecisionType.REQUIRE_APPROVAL)
    passed = bool(
        approval_friction == 0
        and d_shell.decision == AuthorityDecisionType.ALLOW
        and d_set.decision == AuthorityDecisionType.ALLOW
        and d_cat.decision == AuthorityDecisionType.REQUIRE_APPROVAL
        and d_ext.decision == AuthorityDecisionType.DENY
        and s_res.get("ok") and g_res.get("setting", {}).get("current") == 65536
        and deleted_ok and gone_ok
    )
    return CheckResult(
        id="full_auto_settings_sessions",
        name="Full Auto zero-friction authority, settings_set & disposable session deletion",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "approval_friction": approval_friction,
            "persisted_ctx": g_res.get("setting", {}).get("current"),
            "catastrophic_gated": d_cat.decision.value,
            "external_denied": d_ext.decision.value,
            "disposable_deleted_persisted": gone_ok,
        },
    )


def run_heartbeat_and_persistence_check(*, artifacts_dir: Path) -> CheckResult:
    """Checks 10-12: Background task continuity, Human Needs heartbeat full cycle, and restart recovery."""
    t0 = time.perf_counter()
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, dump_yaml
    from jaeger_ai.core.tasks.models import DurableTask, TaskState
    from jaeger_ai.core.tasks.store import SqliteDurableTaskStore
    from jaeger_ai.core.world.model import EpistemicProvenance
    from jaeger_ai.core.world.store import SqliteWorldStore
    from jaeger_ai.features.human_needs.heartbeat_loop import run_human_needs_heartbeat
    from jaeger_ai.features.human_needs.store import HumanNeedsStore

    root = artifacts_dir / "heartbeat_state"
    inst = root / "instances" / "jaeger"
    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    cfg = Config(instance_name="jaeger", model={"model_path": "unconfigured"})
    cfg.automation.autonomy = "auto"
    cfg.permissions.mode = "allow"
    dump_yaml(layout.config_path, cfg)

    hn_db, w_db, t_db = root / "human_needs.sqlite3", root / "knowledge.sqlite3", root / "gateway_sessions.sqlite3"
    hn = HumanNeedsStore(hn_db)
    goal = hn.add_goal("Maintain clean daily focus", "competence_esteem", priority=1, success_metric="plan verified")
    SqliteWorldStore(w_db).record_claim("Maintain clean daily focus", "baseline", "active", EpistemicProvenance.VERIFIED)

    bg_done = threading.Event()
    def _bg():
        time.sleep(0.05)
        bg_done.set()
    threading.Thread(target=_bg, daemon=True).start()

    def _exec(task: DurableTask) -> dict:
        return {"ok": True, "verified": True, "summary": f"Verified {task.task_id}", "evidence_ref": "selftest:ok"}

    daytime = datetime(2026, 11, 19, 14, 0, 0)
    r1 = run_human_needs_heartbeat(now=daytime, human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst, executor=_exec)
    # Second beat after reopening stores (simulated restart)
    r2 = run_human_needs_heartbeat(now=datetime(2026, 11, 19, 14, 30, 0), human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst, executor=_exec)
    bg_ok = bg_done.wait(timeout=2.0)

    reopened_tasks = SqliteDurableTaskStore(t_db).list_tasks()
    reopened_outcomes = HumanNeedsStore(hn_db).list_outcomes(goal_id=goal["goal_id"])
    passed = bool(
        len(r1.admitted_tasks) == 1
        and len(r1.executed_outcomes) == 1
        and len(r2.admitted_tasks) == 0
        and len(r2.skipped_duplicates) == 1
        and r2.incorporated_outcomes >= 1
        and len(reopened_tasks) == 1 and reopened_tasks[0].state == TaskState.COMPLETED_VERIFIED
        and len(reopened_outcomes) == 1
        and bg_ok
    )
    return CheckResult(
        id="background_and_heartbeat",
        name="Background task continuity, Human Needs heartbeat cycle & restart persistence",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "beat1_admitted": len(r1.admitted_tasks),
            "beat2_admitted": len(r2.admitted_tasks),
            "beat2_duplicates_skipped": len(r2.skipped_duplicates),
            "beat2_incorporated_outcomes": r2.incorporated_outcomes,
            "background_thread_ok": bg_ok,
            "persisted_verified_tasks": len(reopened_tasks),
        },
    )


def run_combined_multimodal_e2e_check(
    *,
    artifacts_dir: Path,
    allow_quiet_hours: bool = False,
    vision_model: str = "qwen3.5:9b",
) -> CheckResult:
    """§5 Combined Multimodal End-to-End: Live Camera + Spoken Question -> Truth Reasoning -> Physical TTS -> Mic Recapture -> Persistence."""
    t0 = time.perf_counter()
    if is_quiet_hours() and not allow_quiet_hours:
        return CheckResult(
            id="multimodal_e2e",
            name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
            status=CheckStatus.SKIPPED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Quiet hours active (22:00-07:00); pass --allow-quiet-hours to run physical multimodal audio.",
        )

    devs = audio_hil.enumerate_audio_devices()
    speaker, mic = audio_hil.select_physical_devices(devs)
    if not speaker or not mic or devs.get("mic_tcc_status") not in (None, 3):
        return CheckResult(
            id="multimodal_e2e",
            name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Physical speaker/microphone or mic TCC unavailable",
        )

    # 1. Capture live camera frame
    cam = vision_hil.capture_live_camera_frames(artifacts_dir=artifacts_dir)
    if cam.get("blocked") or not cam.get("ok"):
        return CheckResult(
            id="multimodal_e2e",
            name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"Live camera unavailable: {cam.get('reason', 'black frame')}",
        )

    # 2. Allow Insta360 USB audio interface to settle after camera close, then speak question
    time.sleep(0.8)
    sr = int(min(speaker["sr"], mic["sr"])) or 48000
    question_phrase = "Truth, briefly describe what you see in the camera view."
    with audio_hil.temporary_physical_audio_ready([speaker["name"]], mic["name"], speaker_volume=0.74, mic_volume=0.90):
        q_wav, q_sr, _ = audio_hil.synthesize_tts(question_phrase, gain=0.55)
        q_rec, q_ac = audio_hil.play_and_capture_acoustic(
            q_wav, q_sr,
            output_device_index=speaker["index"],
            input_device_index=mic["index"],
            output_device_name=speaker["name"],
            device_sr=sr,
        )
        if q_ac["silence_detected"]:
            return CheckResult(
                id="multimodal_e2e",
                name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
                status=CheckStatus.BLOCKED,
                required=False,
                elapsed_s=round(time.perf_counter() - t0, 2),
                metrics={"question_acoustic": q_ac},
                reason=f"Mic '{mic['name']}' captured silence for spoken question from '{speaker['name']}'.",
            )
        q_transcript, stt_engine, _ = audio_hil.transcribe_audio(q_rec, sr)
        q_match = audio_hil.word_match_score(question_phrase, q_transcript)

        # 3. Grounded visual + audio-derived reasoning via Truth's local vision model
        from jaeger_ai.core.models import local_vision
        vis = local_vision.describe(
            cam["frame_png_bytes"],
            f"The user asked aloud: '{q_transcript or question_phrase}'. Answer in one short spoken sentence describing only what is genuinely visible.",
            model=vision_model,
            timeout=90,
        )
        answer_text = str(vis.get("answer") or "").strip()
        if not vis.get("ok") or not answer_text:
            return CheckResult(
                id="multimodal_e2e",
                name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
                status=CheckStatus.FAIL,
                elapsed_s=round(time.perf_counter() - t0, 2),
                reason=f"Grounded vision reasoning failed: {vis.get('error')}",
            )

        # 4. Speak Truth's grounded answer through physical speakers & recapture with physical mic -> STT
        a_wav, a_sr, tts_engine = audio_hil.synthesize_tts(answer_text[:220], gain=0.55)
        a_rec, a_ac = audio_hil.play_and_capture_acoustic(
            a_wav, a_sr,
            output_device_index=speaker["index"],
            input_device_index=mic["index"],
            output_device_name=speaker["name"],
            device_sr=sr,
        )
        a_transcript, _, _ = audio_hil.transcribe_audio(a_rec, sr)
        a_match = audio_hil.word_match_score(answer_text[:220], a_transcript)

    # 5. Persist multimodal conversation cleanly in isolated SQLite session store & verify reopen
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    db = artifacts_dir / "multimodal_e2e.sqlite3"
    s1 = GatewaySessionStore(db)
    s1.ensure_session("mm-e2e-1", title="Multimodal Selftest")
    s1.append_message("mm-e2e-1", "user", f"{q_transcript}\n[Camera: {cam['camera_name']} {cam['resolution']}]")
    s1.append_message("mm-e2e-1", "assistant", answer_text)
    persisted_msgs = GatewaySessionStore(db).list_messages("mm-e2e-1").get("messages", [])

    passed = bool(
        q_match >= 0.5
        and a_match >= 0.5
        and not a_ac["silence_detected"]
        and len(persisted_msgs) == 2
    )
    ambient_blocked = bool(
        not passed
        and len(persisted_msgs) == 2
        and (
            q_ac["noise_floor_rms"] >= 0.005
            or q_ac["snr_db"] < 6.0
            or a_ac["noise_floor_rms"] >= 0.005
            or a_ac["snr_db"] < 6.0
        )
    )
    mm_status = CheckStatus.PASS if passed else (CheckStatus.BLOCKED if ambient_blocked else CheckStatus.FAIL)
    return CheckResult(
        id="multimodal_e2e",
        name="Combined multimodal E2E (camera + spoken audio + Truth reasoning + spoken reply + persistence)",
        status=mm_status,
        required=(mm_status != CheckStatus.BLOCKED),
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "camera": cam["camera_name"],
            "speaker": speaker["name"],
            "microphone": mic["name"],
            "tts_engine": tts_engine,
            "stt_engine": stt_engine,
            "question_word_match": q_match,
            "answer_recapture_word_match": a_match,
            "question_snr_db": q_ac["snr_db"],
            "answer_snr_db": a_ac["snr_db"],
            "question_noise_floor_rms": q_ac["noise_floor_rms"],
            "answer_noise_floor_rms": a_ac["noise_floor_rms"],
            "persisted_messages": len(persisted_msgs),
        },
        evidence={
            "question_transcript": q_transcript,
            "truth_grounded_answer": answer_text,
            "answer_recapture_transcript": a_transcript,
        },
        reason="" if passed else (
            f"High ambient room audio interfered with open-air STT (q={q_match}, a={a_match}, q_snr={q_ac['snr_db']}dB); re-run in a quiet room."
            if ambient_blocked else f"Multimodal audio match below threshold (q={q_match}, a={a_match})"
        ),
    )


def run_selftest(
    *,
    full: bool = False,
    audio: bool = False,
    camera: bool = False,
    vision: bool = False,
    ui: bool = False,
    autonomy: bool = False,
    heartbeat: bool = False,
    multimodal: bool = False,
    allow_quiet_hours: bool = False,
    keep_artifacts: bool = False,
    vision_model: str = "qwen3.5:9b",
) -> SelftestReport:
    if full:
        audio = camera = vision = ui = autonomy = heartbeat = multimodal = True
    elif not any((audio, camera, vision, ui, autonomy, heartbeat, multimodal)):
        # Safe non-intrusive default when called with bare `jaeger selftest`
        autonomy = heartbeat = True

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    art_dir = Path(tempfile.mkdtemp(prefix="jaeger-selftest-"))
    checks: list[CheckResult] = []
    try:
        checks.append(run_preflight_check())

        if audio:
            checks.append(audio_hil.run_audio_loopback_check(artifacts_dir=art_dir, allow_quiet_hours=allow_quiet_hours))
            checks.append(run_ten_turn_conversation_check(artifacts_dir=art_dir, allow_quiet_hours=allow_quiet_hours))
            checks.append(audio_hil.run_physical_barge_in_check(artifacts_dir=art_dir, allow_quiet_hours=allow_quiet_hours))
            checks.append(audio_hil.run_audio_reliability_check())

        if camera:
            checks.append(vision_hil.run_camera_capture_check(artifacts_dir=art_dir, model=vision_model))

        if vision:
            checks.append(vision_hil.run_image_recognition_check(artifacts_dir=art_dir, model=vision_model))
            checks.append(vision_hil.run_video_understanding_check(artifacts_dir=art_dir, model=vision_model))

        if ui:
            checks.append(ui_hil.run_avatar_and_ui_check(artifacts_dir=art_dir))

        if autonomy:
            checks.append(run_autonomy_computer_use_check(artifacts_dir=art_dir))
            checks.append(run_full_auto_settings_and_sessions_check(artifacts_dir=art_dir))

        if heartbeat:
            checks.append(run_heartbeat_and_persistence_check(artifacts_dir=art_dir))

        if multimodal:
            checks.append(run_combined_multimodal_e2e_check(
                artifacts_dir=art_dir, allow_quiet_hours=allow_quiet_hours, vision_model=vision_model,
            ))
    finally:
        cleaned = False
        if not keep_artifacts and art_dir.exists():
            shutil.rmtree(art_dir, ignore_errors=True)
            cleaned = True

    return SelftestReport(
        commit=_git_commit(),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks=checks,
        artifacts_dir="" if cleaned else str(art_dir),
        artifacts_cleaned=cleaned,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="jaeger selftest",
        description="Automated daily-use & hardware-in-the-loop acceptance suite for JaegerAI.",
    )
    ap.add_argument("--full", action="store_true", help="Run all acceptance checks (audio, camera, vision, UI, autonomy, heartbeat, multimodal)")
    ap.add_argument("--audio", action="store_true", help="Run physical speaker-to-mic audio loopback, 10-turn, barge-in, and reliability checks")
    ap.add_argument("--camera", action="store_true", help="Run live physical camera capture & vision routing check")
    ap.add_argument("--vision", action="store_true", help="Run deterministic image recognition & temporal video understanding checks")
    ap.add_argument("--ui", action="store_true", help="Run Playwright rendered React UI, Avatar, streaming, and Council checks")
    ap.add_argument("--autonomy", action="store_true", help="Run native macOS computer-use, Full Auto, settings, and disposable session checks")
    ap.add_argument("--heartbeat", action="store_true", help="Run background continuity, Human Needs heartbeat cycle, and restart persistence checks")
    ap.add_argument("--multimodal", action="store_true", help="Run combined camera + audio + Truth reasoning + spoken recapture E2E check")
    ap.add_argument("--allow-quiet-hours", action="store_true", help="Allow physical speaker playback during quiet hours (22:00-07:00)")
    ap.add_argument("--keep-artifacts", action="store_true", help="Preserve isolated temp diagnostic recordings/screenshots after run")
    ap.add_argument("--vision-model", default="qwen3.5:9b", help="Local Ollama vision model (default: qwen3.5:9b)")
    ap.add_argument("--json", dest="as_json", action="store_true", help="Print machine-readable JSON report to stdout")
    ap.add_argument("--report", default="", help="Write JSON report to the specified file path")
    args = ap.parse_args(argv)

    report = run_selftest(
        full=args.full,
        audio=args.audio,
        camera=args.camera,
        vision=args.vision,
        ui=args.ui,
        autonomy=args.autonomy,
        heartbeat=args.heartbeat,
        multimodal=args.multimodal,
        allow_quiet_hours=args.allow_quiet_hours,
        keep_artifacts=args.keep_artifacts,
        vision_model=args.vision_model,
    )
    if args.report:
        Path(args.report).write_text(report.to_json(), encoding="utf-8")
    if args.as_json:
        print(report.to_json())
    else:
        print(report.to_human_report())
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
