"""Instance-scoped cron, idle/heartbeat, and webhook producers.

Exactly one process per instance may run these. The Gateway daemon takes
the lease when it is the resident OWNER; a local-execution bridge takes
it only when the lease is free. Gateway-backed bridges never start them.

Producers submit work through a :class:`BackgroundTurnSink`; they do not
construct an agent or own an execution loop.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from typing import Any, Protocol

LEASE_SLOT = "background_producers"
LOCK_NAME = "background_producers.lock"
STATUS_NAME = "background_producers.json"
_TRUTHY = {"1", "true", "yes"}


class BackgroundTurnSink(Protocol):
    """The canonical execution owner, as seen by background producers."""

    def submit_turn(
        self,
        prompt: str,
        *,
        session: str,
        request_id: str,
        source: str,
    ) -> dict[str, Any]:
        """Run one background turn and return text/error/halt_reason."""

    def is_busy(self) -> bool:
        ...

    def last_user_quiet_s(self) -> float:
        ...

    def last_user_session(self) -> str:
        ...


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.05, float(raw))
    except ValueError:
        return default


def cron_request_id(name: str, occurrence: str) -> str:
    occ = (occurrence or "").strip() or str(int(time.time()))
    return f"cron:{name}:{occ}"


def webhook_request_id(delivery_id: str | None) -> str:
    ident = (delivery_id or "").strip()
    if ident:
        return f"webhook:{ident}"
    import uuid
    return f"webhook:{uuid.uuid4().hex}"


def _cron_job_name(session_key: str | None) -> str:
    raw = str(session_key or "cron").strip() or "cron"
    if raw.startswith("cron:"):
        return raw[5:] or "cron"
    if raw.startswith("cron_"):
        return raw[5:] or "cron"
    return raw


def _load_config(layout: Any) -> Any:
    try:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        return load_yaml(layout.config_path, Config)
    except Exception:  # noqa: BLE001
        return None


def _write_status(layout: Any, payload: dict[str, Any]) -> None:
    run_dir = getattr(layout, "run_dir", None)
    if run_dir is None:
        return
    path = run_dir / STATUS_NAME
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _clear_status(layout: Any) -> None:
    run_dir = getattr(layout, "run_dir", None)
    if run_dir is None:
        return
    try:
        (run_dir / STATUS_NAME).unlink()
    except OSError:
        pass


class BackgroundProducers:
    """Lease-gated composition of cron, idle supervision, and webhooks."""

    def __init__(
        self,
        layout: Any,
        sink: BackgroundTurnSink,
        *,
        display_name: str = "",
    ) -> None:
        self.layout = layout
        self.sink = sink
        self.display_name = display_name or getattr(layout, "root", type("R", (), {"name": "jaeger"})()).name
        self.cron: Any = None
        self.webhook_httpd: Any = None
        self.stop_event: threading.Event | None = None
        self._lock_file: Any = None
        self._idle_thread: threading.Thread | None = None
        self._accepting = False
        self.held = False
        self.webhook_port: int | None = None

    def try_start(self) -> bool:
        """Acquire the instance lease and start enabled producers.

        Returns False when another live holder already owns them. The
        lease is an exclusive flock, so two starters in one process
        cannot both win.
        """
        if (
            (_env_flag("JAEGER_TEST_HEADLESS") or bool(os.environ.get("PYTEST_CURRENT_TEST")))
            and not _env_flag("JAEGER_BACKGROUND_PRODUCERS")
        ):
            # Isolated tests boot the bridge without opting into background
            # threads. Owned-process and producer tests set the opt-in.
            return False
        run_dir = getattr(self.layout, "run_dir", None)
        if run_dir is None:
            return False
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / LOCK_NAME
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            owner = other_holder_pid(self.layout)
            print(f"[background] producers already owned by pid {owner}", flush=True)
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._lock_file = handle
        self.held = True
        self._accepting = True
        cfg = _load_config(self.layout)
        try:
            self._start_cron()
            self._start_idle(cfg)
            self._start_webhooks(cfg)
            self._publish_status()
        except Exception:
            # Startup is one lease-owned transaction.  If a later producer
            # (commonly the webhook bind) fails after cron/idle started, stop
            # everything and release the flock before propagating the error.
            # Otherwise the caller cannot retain this object to clean it up,
            # leaving a live thread behind an apparently free owner slot.
            self.stop()
            raise
        return True

    def stop(self) -> None:
        # Refuse new work before releasing the lease, so a successor cannot
        # overlap a callback that is still inside this process.
        self._accepting = False
        if self.cron is not None:
            try:
                self.cron.shutdown(wait=True)
            except Exception:  # noqa: BLE001
                pass
            self.cron = None
        if self.stop_event is not None:
            self.stop_event.set()
            thread = self._idle_thread
            self.stop_event = None
            self._idle_thread = None
            if thread is not None:
                thread.join(timeout=2.0)
        if self.webhook_httpd is not None:
            try:
                self.webhook_httpd.shutdown()
                self.webhook_httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
            self.webhook_httpd = None
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:  # noqa: BLE001
                pass
            self._lock_file = None
        self.held = False
        _clear_status(self.layout)

    def _publish_status(self) -> None:
        _write_status(self.layout, {
            "pid": os.getpid(),
            "cron": self.cron is not None,
            "idle": self.stop_event is not None,
            "webhooks": self.webhook_httpd is not None,
            "webhook_port": self.webhook_port,
        })

    def _start_cron(self) -> None:
        from jaeger_agent.background.cron_runner import CronRunner

        poll_s = _float_env("JAEGER_CRON_POLL_S", 30.0)
        self.cron = CronRunner(self._cron_cb, llm_lock=None, poll_s=poll_s)
        self.cron.start()

    def _cron_cb(self, prompt: str, session_key: str | None = None) -> None:
        from jaeger_ai.core.runtime.background_delivery import record_result
        from jaeger_ai.core.runtime.cron_delivery import deliver_text

        name = _cron_job_name(session_key)
        session = session_key or f"cron:{name}"
        occurrence = ""
        try:
            from jaeger_agent.memory import memory as mem
            for row in mem.list_schedules() or []:
                if str(row.get("name") or "") == name:
                    occurrence = str(row.get("last_run_at") or row.get("next_run_at") or "")
                    break
        except Exception:  # noqa: BLE001
            occurrence = ""
        if not self._accepting:
            _restore_claimed_schedule(name)
            return
        request_id = cron_request_id(name, occurrence)
        try:
            result = self.sink.submit_turn(
                prompt, session=session, request_id=request_id, source="cron",
            )
        except Exception as exc:  # noqa: BLE001
            _restore_claimed_schedule(name)
            print(f"[background] cron submit failed: {exc}", flush=True)
            return
        if result.get("skipped") or result.get("halt_reason") in {"busy", "error", "conflict"}:
            if not result.get("replayed"):
                _restore_claimed_schedule(name)
            return
        try:
            record_result(
                self.layout, result, source="cron", source_session=session,
                display_name=self.display_name,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[background] cron record skipped: {exc}", flush=True)
        text = result.get("text") or ""
        try:
            sent = deliver_text(self.layout, name, text)
            if sent and not sent.get("sent"):
                print(f"[background] cron deliver skipped: {sent.get('error')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[background] cron deliver failed: {exc}", flush=True)

    def _start_idle(self, cfg: Any) -> None:
        stop = threading.Event()
        self.stop_event = stop
        poll_s = _float_env("JAEGER_IDLE_POLL_S", 2.0)

        def _loop() -> None:
            while not stop.wait(poll_s):
                if not self._accepting:
                    return
                try:
                    self._idle_once(cfg)
                except Exception as exc:  # noqa: BLE001
                    print(f"[background] idle supervisor: {exc}", flush=True)

        thread = threading.Thread(target=_loop, name="idle-supervisor", daemon=True)
        self._idle_thread = thread
        thread.start()

    def _idle_once(self, cfg: Any) -> None:
        from jaeger_agent.background.board import has_actionable_work
        from jaeger_agent.prompts import AUTO_BOARD_PROMPT

        from jaeger_ai.core.runtime import heartbeat as hb
        from jaeger_ai.core.runtime.completions import pending_batch, pending_count, completion_prompt, batch_id, acknowledge
        from jaeger_ai.core.runtime.idle_supervisor import Action, decide, window_elapsed
        from jaeger_ai.core.runtime.task_liveness import reclaim_stale

        layout = self.layout
        try:
            reclaim_stale(layout)
        except Exception:  # noqa: BLE001
            pass

        hb_cfg = getattr(cfg, "heartbeat", None) if cfg is not None else None
        enabled = True if hb_cfg is None else bool(hb_cfg.enabled)
        interval = 30 if hb_cfg is None else int(hb_cfg.interval_minutes)
        hb_session = "heartbeat" if hb_cfg is None else str(hb_cfg.session or "heartbeat")
        idle_minutes = 30
        try:
            idle_minutes = int(cfg.deep_think.auto_idle_minutes)
        except Exception:  # noqa: BLE001
            idle_minutes = 30
        quiet = self.sink.last_user_quiet_s()
        idle_ready = _env_flag("JAEGER_IDLE_READY") or window_elapsed(
            idle_minutes * 60, quiet_for=quiet,
        )
        action = decide(
            busy=self.sink.is_busy(),
            has_completions=pending_count() > 0,
            idle_ready=idle_ready,
            has_deep_think=False,
            has_board=has_actionable_work(layout),
            heartbeat_due=hb.is_due(layout, interval_minutes=interval, enabled=enabled),
        )
        if action is Action.SKIP or action is Action.IDLE:
            return
        session = self.sink.last_user_session() or "desktop-app"
        prompt = None
        source = action.value
        completion_events = []
        if action is Action.COMPLETION:
            completion_events = pending_batch(layout)
            prompt = completion_prompt(completion_events) if completion_events else None
            session = "completions"
        elif action is Action.BOARD:
            prompt = AUTO_BOARD_PROMPT
            session = "kanban_idle"
        elif action is Action.HEARTBEAT:
            event, wake_cognition, hb_prompt = hb.execute_heartbeat_event(layout)
            _ = event
            if _env_flag("JAEGER_HEARTBEAT_WAKE"):
                wake_cognition = True
                if not hb_prompt or hb.is_silent_ok(hb_prompt):
                    hb_prompt = "Say CONTRACT-ANSWER"
            if not wake_cognition:
                return
            prompt = hb_prompt
            session = hb_session
        if not prompt:
            return

        request_id = batch_id(completion_events) if completion_events else f"{source}:{int(time.time())}"
        if action is Action.HEARTBEAT:
            request_id = f"heartbeat:{int(hb.last_beat_at(layout) or time.time())}"
        result = self.sink.submit_turn(
            prompt, session=session, request_id=request_id, source=source,
        )
        if result.get("skipped"):
            return
        if completion_events and result.get("status") == "completed" and not result.get("error"):
            acknowledge(completion_events)
        from jaeger_ai.core.runtime.background_delivery import record_result
        try:
            record_result(
                layout, result, source=source, source_session=session,
                display_name=self.display_name,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[background] {source} record skipped: {exc}", flush=True)
        if action is Action.HEARTBEAT:
            text = result.get("text") or ""
            error = result.get("error")
            silent = hb.is_silent_ok(text)
            failed = bool(
                error or result.get("halt_reason") or result.get("cancelled")
                or result.get("execution_unknown")
            )
            hb.mark_beat(layout, silent=silent or failed)

    def _start_webhooks(self, cfg: Any) -> None:
        from jaeger_ai.core.runtime import webhooks as hooks

        wcfg = getattr(cfg, "webhooks", None) if cfg is not None else None
        if wcfg is not None and not bool(getattr(wcfg, "enabled", True)):
            return
        host = str(getattr(wcfg, "host", None) or hooks.DEFAULT_HOST) if wcfg else hooks.DEFAULT_HOST
        port = int(getattr(wcfg, "port", None) or hooks.DEFAULT_PORT) if wcfg else hooks.DEFAULT_PORT
        env_port = os.environ.get("JAEGER_WEBHOOK_PORT", "").strip()
        if env_port:
            port = int(env_port)
        elif _env_flag("JAEGER_TEST_HEADLESS"):
            port = 0
        secret = str(getattr(wcfg, "secret", None) or "") if wcfg else ""

        def _on_hook(interpreted: dict[str, str]) -> dict[str, Any]:
            return self._handle_webhook(interpreted)

        httpd = hooks.serve(_on_hook, host=host, port=port, secret=secret)
        self.webhook_httpd = httpd
        self.webhook_port = int(httpd.server_address[1])
        print(f"[background] webhooks on {host}:{self.webhook_port}", flush=True)

    def _handle_webhook(self, interpreted: dict[str, str]) -> dict[str, Any]:
        if not self._accepting:
            return {"ok": False, "error": "producers stopped", "fired": None}
        action = interpreted.get("action") or "board"
        title = interpreted.get("title") or "webhook"
        prompt = interpreted.get("prompt") or title
        delivery_id = (interpreted.get("delivery_id") or "").strip()
        if action == "turn":
            request_id = webhook_request_id(interpreted.get("delivery_id"))
            result = self.sink.submit_turn(
                prompt, session="webhook", request_id=request_id, source="webhook",
            )
            return {
                "fired": "turn",
                "text": (result.get("text") or "")[:500],
                "request_id": request_id,
                "replayed": bool(result.get("replayed")),
                "status": result.get("status"),
            }
        prior = _lookup_webhook_delivery(self.layout, delivery_id)
        if prior is not None:
            return {"fired": "board", "card_id": prior, "replayed": True, "request_id": webhook_request_id(delivery_id)}
        from jaeger_agent.background.board import board_for_layout
        card = board_for_layout(self.layout).add(
            title, description=prompt, column="ready",
            source="schedule", created_by="agent",
        )
        _remember_webhook_delivery(self.layout, delivery_id, card.id)
        return {"fired": "board", "card_id": card.id, "replayed": False}


def _restore_claimed_schedule(name: str) -> None:
    """Put a claimed schedule back so a busy or failed admission can retry.

    ``claim_due_schedules`` advances ``next_fire_at`` before the callback.
    Dropping the callback on a busy session would otherwise lose that
    occurrence.
    """
    from datetime import datetime, timezone

    from jaeger_agent.memory import sqlite_store

    if not name or not sqlite_store.is_bound():
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with sqlite_store.writer() as conn:
            conn.execute(
                "UPDATE schedules SET status='active', next_fire_at=? WHERE schedule_id=?",
                (now, name),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[background] could not restore schedule {name}: {exc}", flush=True)


def _delivery_path(layout: Any):
    mem = getattr(layout, "memory_dir", None)
    if mem is None:
        return None
    return mem / "webhook_deliveries.json"


def _lookup_webhook_delivery(layout: Any, delivery_id: str) -> str | None:
    if not delivery_id:
        return None
    path = _delivery_path(layout)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get(delivery_id) if isinstance(data, dict) else None
    return str(value) if value else None


def _remember_webhook_delivery(layout: Any, delivery_id: str, card_id: str) -> None:
    if not delivery_id:
        return
    path = _delivery_path(layout)
    if path is None:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[delivery_id] = card_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def other_holder_pid(layout: Any) -> int | None:
    """PID written by the live flock holder, or None when the lease is free."""
    run_dir = getattr(layout, "run_dir", None)
    if run_dir is None:
        return None
    path = run_dir / LOCK_NAME
    if not path.is_file():
        return None
    try:
        with path.open("r") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    return int(path.read_text(encoding="utf-8").strip() or "0") or None
                except ValueError:
                    return -1
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return None
    return None


__all__ = [
    "LEASE_SLOT",
    "LOCK_NAME",
    "STATUS_NAME",
    "BackgroundProducers",
    "BackgroundTurnSink",
    "cron_request_id",
    "webhook_request_id",
    "other_holder_pid",
]
