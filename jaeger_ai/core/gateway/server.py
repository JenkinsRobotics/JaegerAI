"""Jaeger Unified Gateway Daemon.

Decouples the Agent Engine from any UI window. Runs as a persistent background
service. Multi-client: allows Mac App, Web UI, and CLI to connect simultaneously,
share sessions, and stream live events without process teardown.
"""

from __future__ import annotations

import asyncio
import time
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from aiohttp import ClientSession, ClientTimeout, web

from jaeger_ai import __version__ as JAEGER_VERSION
from jaeger_ai.contract.frameworks import DEFAULT_AGENT_MODEL
from jaeger_ai.contract.legacy_paths import legacy_paths_enabled
from jaeger_ai.contract.model_ids import provider_model_name, split_routed_model_id
from jaeger_ai.contract.ports import (
    GATEWAY_PORT,
    LOOPBACK,
    OLLAMA_URL as LOCKED_OLLAMA_URL,
    WEBUI_ADAPTER_PORT,
    WEBUI_PORT,
)
from jaeger_ai.contract.sessions import normalise_surface

from .event_bus import GatewayEventBus, ReplayGap
from jaeger_ai.core.runtime.cancellation import CancellationRegistry

from .session_store import EXECUTION_INPUT_KEYS, GatewaySessionStore, RequestBusy, RequestConflict

logger = logging.getLogger("jaeger.gateway")

DEFAULT_GATEWAY_PORT = int(os.environ.get("JAEGER_GATEWAY_PORT", str(GATEWAY_PORT)))
DEFAULT_GATEWAY_HOST = os.environ.get("JAEGER_GATEWAY_HOST", LOOPBACK)

# Locked spine endpoints (docs/spine-acceptance.md M10). Chat does not use :8813.
LOCKED_BRIDGE_HEALTH_URL = os.environ.get(
    "JAEGER_BRIDGE_HEALTH_URL", f"http://{LOOPBACK}:{WEBUI_ADAPTER_PORT}/health"
).rstrip("/")
LOCKED_WEBUI_URL = os.environ.get(
    "JAEGER_WEBUI_URL", f"http://{LOOPBACK}:{WEBUI_PORT}"
).rstrip("/")
DEFAULT_OLLAMA_MODEL = os.environ.get("JAEGER_GATEWAY_OLLAMA_MODEL", "kimi-k2.7-code:cloud")
# Agent turns require native MCP. Reduced text mode must be explicitly selected.
NATIVE_LEAD_MCP_TIMEOUT_S = float(os.environ.get("JAEGER_GATEWAY_MCP_TIMEOUT_S", "300"))


# ``native_session`` marker for a request bound to the Entity's own run
# (owner-react), as opposed to a run on the native MCP server.
OWNER_RUN_SESSION_PREFIX = "owner:"

# How long a tool call waits for the operator before it is refused.
APPROVAL_WAIT_S = 300.0

# Arguments that name what a tool call will touch, in the order a human
# reading an approval on a phone needs them.
_APPROVAL_TARGET_KEYS = (
    "path", "src", "dst", "command", "url", "to", "recipient", "package",
    "script", "code", "target", "name", "query",
)


def _approval_target(request: Any) -> str:
    """What this call will touch, for the approval prompt."""
    arguments = getattr(request, "arguments", None) or {}
    parts = []
    for key in _APPROVAL_TARGET_KEYS:
        value = arguments.get(key)
        if value not in (None, ""):
            text = str(value)
            parts.append(f"{key}={text[:200]}{'…' if len(text) > 200 else ''}")
    return "; ".join(parts)


# Opening words of a request that only asks about what an image shows.
_IMAGE_QUESTION_OPENERS = frozenset({
    "what", "which", "who", "where", "when", "why", "how", "is", "are", "does",
    "do", "can", "read", "describe", "look", "tell", "identify", "count",
})


#: Streamed answer text is batched into durable ``turn.delta`` events at
#: whichever comes first: this many characters or this many seconds.
TURN_DELTA_BATCH_CHARS = 96
TURN_DELTA_BATCH_S = 0.1
TOOL_EVENT_NAME_MAX = 80
TOOL_EVENT_DURATION_MAX_S = 86_400.0


#: Shell-like tools whose command and output the operator sees inline, as in any IDE
#: agent. Everything else (file contents, credentials, arbitrary results) stays
#: unpublished. ``write_stdin`` is excluded on purpose: what is typed into a live
#: process can be a password.
_INLINE_INPUT_KEY = {"terminal": "command", "run_shell": "command", "exec_command": "cmd", "execute_code": "code"}
_INLINE_OUTPUT_KEYS = ("output", "stdout", "stderr", "result")
_INLINE_INPUT_MAX = 600
_INLINE_OUTPUT_MAX = 1500
_SECRET_TEXT = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|passwd|password|authorization|bearer)\s*[=:]\s*['\"]?|\bsk-)[A-Za-z0-9_\-./+=]{8,}"
)


def _inline_text(text: Any, limit: int) -> str:
    """Bounded, secret-redacted text for an inline tool block (best effort)."""
    value = _SECRET_TEXT.sub(lambda m: m.group(1) + "***", str(text or "")).strip()
    if len(value) <= limit:
        return value
    half = limit // 2
    return f"{value[:half]}\n…\n{value[-half:]}"


def _tool_input_text(name: str, args: Any) -> str:
    key = _INLINE_INPUT_KEY.get(name)
    return _inline_text(args.get(key), _INLINE_INPUT_MAX) if key and isinstance(args, dict) else ""


def _tool_output_text(name: str, result: Any) -> str:
    if name not in _INLINE_INPUT_KEY or not isinstance(result, dict):
        return ""
    parts = [str(result[k]) for k in _INLINE_OUTPUT_KEYS if isinstance(result.get(k), (str, int, float)) and str(result[k]).strip()]
    return _inline_text("\n".join(parts), _INLINE_OUTPUT_MAX)


def _safe_tool_event_name(value: Any) -> str:
    """Return a bounded identifier, never arbitrary tool-supplied text.

    Tool names normally come from the registered catalog, but this callback is
    an observability boundary.  If a malformed provider invents a name, do not
    copy it into the durable client stream where it could contain prompts,
    arguments, terminal control characters, or secrets.
    """
    name = str(value or "")
    if (
        not name
        or len(name) > TOOL_EVENT_NAME_MAX
        or any(
            not (char.isascii() and (char.isalnum() or char in "_.:-"))
            for char in name
        )
    ):
        return "tool"
    return name


def _safe_tool_duration(value: Any) -> float:
    """Normalize the sole tool-result datum allowed onto the public stream."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not 0.0 <= seconds <= TOOL_EVENT_DURATION_MAX_S:
        return 0.0
    return round(seconds, 3)


def _admitted_execution(request_row: dict[str, Any]) -> dict[str, Any] | None:
    """The frozen execution snapshot of an admitted request, or ``None`` for a
    digest-v1 receipt admitted before snapshots existed."""
    if int(request_row.get("digest_version") or 1) < 2:
        return None
    execution = request_row.get("execution")
    return execution if isinstance(execution, dict) else None


def _asks_about_the_image(request: str) -> bool:
    """True for a question about an image; anything else goes to the Entity.

    The direct vision lane has no tools. Defaulting to it made "save the
    phrase to a file" in an image session a tool-less reply recorded as
    completed, and ``is_actionable_request`` does not recognise that
    sentence as work. So the tool-less lane is opt-in by shape of request:
    a question, or a read/describe-style ask. A heuristic, deliberately
    narrow — a misread costs a slower turn, not a lost action.
    """
    words = request.strip().lower().split()
    return bool(words) and (request.strip().endswith("?") or words[0].strip(",.:") in _IMAGE_QUESTION_OPENERS)


_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


@web.middleware
async def _reject_browser_cross_site(request: web.Request, handler: Any) -> web.StreamResponse:
    """Refuse requests a web page could forge.

    The Gateway has no credentials of its own; loopback is its boundary. That
    boundary does not stop a browser: any page the operator opens can send a
    ``text/plain`` POST here without a CORS preflight, and ``request.json()``
    does not check the content type. The 2026-09-21 audit created a session
    and started an agent turn that way with ``Origin: https://evil.example``.

    Its real clients (the WebUI's server-side proxy, the Mac app, CLIs, the
    MCP server) send no ``Origin``. A browser always does on a cross-origin
    POST, and a DNS-rebinding page cannot fake ``Host``.
    """
    if request.url.host not in _LOOPBACK_HOSTNAMES:
        return web.json_response({"error": "Gateway accepts loopback Host only"}, status=421)
    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            from yarl import URL
            source = URL(origin)
        except ValueError:
            source = None
        if source is None or source.host not in _LOOPBACK_HOSTNAMES or source.port != request.url.port:
            return web.json_response({"error": "Cross-origin requests are refused"}, status=403)
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return web.json_response({"error": "Cross-site requests are refused"}, status=403)
    return await handler(request)


class _GatewayToolConfirmationProvider:
    """Park WRITE_LOCAL (and similar) confirms on the Gateway approval bus.

    Phone/WebUI resolve them with POST /v1/approvals/{id}. Standing
    commissioning filesystem.write grants still auto-allow.
    """

    def __init__(self, app: "JaegerGatewayApp", session_id: str, request_id: str) -> None:
        self.app = app
        self.session_id = session_id
        self.request_id = request_id

    def _grants(self) -> Any:
        """The instance's persistent per-skill grants — the same
        ``<instance>/permissions.json`` the bridge and console read, so an
        "always" answered on any client applies on every client."""
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_os.core.safety.permissions import PermissionGrants

        layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        return PermissionGrants.load(layout.root if layout is not None else None)

    def confirm(self, request: Any) -> bool:
        from jaeger_os.core.safety.permissions import PermissionTier
        skill_name = str(getattr(request, "skill", "") or "")
        try:
            if self._grants().is_granted(skill_name):
                return True
        except Exception:  # noqa: BLE001 — unreadable grants mean "ask", never "allow"
            pass
        try:
            # Autonomy "auto" (the default) means no approval prompts: this is the
            # operator's own assistant. Hardline-blocked commands never reach here
            # (the guard sits outside the tiers), and every action stays audited.
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.runtime.autonomy import effective_autonomy
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if effective_autonomy(getattr(layout, "config_path", None)) == "auto":
                return True
        except Exception:  # noqa: BLE001 — unreadable settings mean "ask", never "allow"
            pass
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            policy = load_authority_policy(rt.layout.root) if getattr(rt, "layout", None) else {}
            tier = getattr(request, "tier", None)
            if tier == PermissionTier.READ_ONLY:
                return True
            if tier == PermissionTier.WRITE_LOCAL and bool((policy.get("filesystem") or {}).get("write")):
                return True
        except Exception:
            pass
        loop = getattr(self.app, "_loop", None)
        if loop is None or not loop.is_running():
            return False
        skill = str(getattr(request, "skill", "") or "")
        op = str(getattr(request, "operation", "") or "")
        summary = str(getattr(request, "summary", "") or "")
        target = _approval_target(request) or summary
        tier_name = getattr(getattr(request, "tier", None), "name", str(getattr(request, "tier", "")))
        aid = f"approval_{uuid.uuid4().hex[:12]}"
        box: dict[str, Any] = {"done": threading.Event(), "approved": False}

        def _arm() -> None:
            fut = loop.create_future()
            self.app.pending_approvals[aid] = fut
            self.app.store.create_approval(
                kind="tool_confirm",
                prompt=f"Allow {skill}.{op}? {target}".strip(),
                options=["once", "deny"],
                session_id=self.session_id,
                request_id=self.request_id,
                approval_id=aid,
                metadata={
                    "tool": f"{skill}.{op}" if skill else op,
                    "target": target,
                    "summary": summary,
                    "reason": tier_name,
                },
            )
            self.app.event_bus.publish(self.session_id, "approval.request", {
                "approval_id": aid,
                "tool": f"{skill}.{op}" if skill else op,
                "target": target,
                "reason": tier_name,
                "session_id": self.session_id,
                "request_id": self.request_id,
            })

            def _done(f: asyncio.Future) -> None:
                try:
                    box["approved"] = bool(f.result())
                except Exception:
                    box["approved"] = False
                box["done"].set()

            fut.add_done_callback(_done)

        loop.call_soon_threadsafe(_arm)
        scope = self.app._cancellations.get(self.request_id)
        deadline = time.monotonic() + APPROVAL_WAIT_S
        while not box["done"].wait(timeout=0.05):
            if scope is not None and scope.cancelled:
                # Cancelled while parked: close the approval (first writer
                # wins) and refuse, whatever a racing decision says.
                self.app.pending_approvals.pop(aid, None)
                self.app.store.resolve_approval(aid, approved=False, decision="cancelled")
                return False
            if time.monotonic() >= deadline:
                break
        else:
            approved = bool(box["approved"]) and not (scope is not None and scope.cancelled)
            if approved and (self.app.store.get_approval(aid) or {}).get("decision") == "always":
                try:
                    self._grants().grant_persistent(skill)
                except Exception:  # noqa: BLE001 — the call itself stays approved
                    logger.warning("could not persist grant for %s", skill, exc_info=True)
            return approved
        # The tool call is about to be refused. Close the row so the phone
        # does not keep offering an approval that can no longer take effect;
        # if the operator's answer won the race, honour it instead.
        self.app.pending_approvals.pop(aid, None)
        if self.app.store.resolve_approval(aid, approved=False, decision="expired") is not None:
            return False
        row = self.app.store.get_approval(aid) or {}
        return row.get("decision") not in {None, "deny", "expired"}


class JaegerGatewayApp:
    def __init__(
        self,
        store: GatewaySessionStore | None = None,
        event_bus: GatewayEventBus | None = None,
        background_client: Any = None,
        orchestration: Any | None = None,
    ) -> None:
        # Explicit stores are used by embedded/test gateways and never attach
        # to the operator's running bridge unless a client is supplied.
        if background_client is None and store is None:
            from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
            background_client = jaeger_bridge()
        self._background_client = background_client
        self._background_task: asyncio.Task | None = None
        self._background_status: dict[str, Any] = {"enabled": background_client is not None}
        self.store = store or GatewaySessionStore()
        from .file_changes import FileChanges
        self.file_changes = FileChanges(self.store.path.parent / "turn-file-changes")
        self.event_bus = event_bus or GatewayEventBus(store=self.store)
        if getattr(self.event_bus, "store", None) is None:
            self.event_bus.attach_store(self.store)
        self.pending_approvals: dict[str, asyncio.Future[bool]] = {}
        # Requests the agent has sent to the operator's editor, awaiting its answer.
        self._ide_pending: dict[str, tuple[str, Any]] = {}
        from jaeger_agent import task_port
        task_port.install_ide_requester(self._ide_request)
        self._running_tasks: dict[str | tuple[str, str], asyncio.Future[Any]] = {}
        # Request-scoped cancellation (R03): registered at admission, bound
        # to the executing agent, released when the worker returns.
        self._cancellations = CancellationRegistry()
        self._mcp_transport_lock = threading.RLock()
        self._mcp_transport_signature: tuple[Any, ...] | None = None
        self._mcp_transport: Any = None
        self._mcp_tool_names: frozenset[str] = frozenset()
        self._owns_store = False
        self._owner_task: asyncio.Task | None = None
        self._pending_resume = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._background_producers: Any = None
        self._last_human_at = time.monotonic()
        self._last_human_session = "desktop-app"
        if orchestration is not None:
            self.orchestration = orchestration
        else:
            try:
                from jaeger_ai.features.ide_orchestration.service import create_default_orchestration_service
                self.orchestration = create_default_orchestration_service()
            except Exception as exc:
                logger.debug("Failed to initialize default ide_orchestration: %s", exc)
                self.orchestration = None
        if self.orchestration is not None and hasattr(self.orchestration, "bind_store"):
            self.orchestration.bind_store(self.store.path)
        from jaeger_ai.core.tasks.owner import GatewayTaskOwner
        self.task_owner = GatewayTaskOwner(self)
        self.app = web.Application(middlewares=[_reject_browser_cross_site])
        self.app.on_startup.append(self._recover_interrupted)
        self.app.on_cleanup.append(self._bounded_shutdown)
        self._setup_routes()

    async def _recover_interrupted(self, app: web.Application) -> None:
        self._loop = asyncio.get_running_loop()
        lease = self.store.claim_process(source_file=str(Path(__file__).resolve()))
        if not lease.get("ok"):
            raise RuntimeError(f"Gateway store is owned by live pid {lease.get('owner_pid')}")
        self._owns_store = True
        self.store.recover_interrupted_sessions()
        expired = self.store.expire_orphaned_tool_confirms()
        if expired:
            logger.info("Expired %d tool approvals orphaned by the previous process", expired)
        runtime_for_producers = None
        try:
            from jaeger_ai.core.entity.ownership import EntityRuntimeMode
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.entity.sensors.supervisor import SensorSupervisor
            try:
                from jaeger_agent.memory import sqlite_store
                from jaeger_agent.workspace import bind as bind_workspace
                from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
                inst = os.environ.get("JAEGER_INSTANCE_DIR")
                layout = InstanceLayout(root=Path(inst) if inst else resolve_instance_dir())
                sqlite_store.bind(layout)
                bind_workspace(layout)
            except Exception as exc:
                logger.debug("sqlite_store/workspace bind skipped: %s", exc)
            rt = EntityRuntime.get_singleton(mode=EntityRuntimeMode.OWNER)
            runtime_for_producers = rt
            logger.info(
                "Gateway attached EntityRuntime %s resident=%s",
                rt.identity.entity_id,
                getattr(rt, "is_resident", False),
            )
            try:
                from jaeger_ai.core.entity.recovery import RecoveryManager
                rt._recovery_report = RecoveryManager().scan_resumable_runs()
            except Exception as exc:
                logger.debug("Recovery rescan skipped: %s", exc)
            try:
                from jaeger_ai.core.instance.commissioning import install_commissioning_permissions
                install_commissioning_permissions(getattr(rt, "layout", None))
            except Exception as exc:
                logger.debug("commissioning permissions install skipped: %s", exc)
            if getattr(rt, "is_resident", False):
                try:
                    from jaeger_ai.core.instance.schemas import Config, load_yaml
                    layout = getattr(rt, "layout", None)
                    if layout is not None:
                        cfg = load_yaml(layout.config_path, Config)
                        desktop = getattr(getattr(cfg, "sensors", None), "desktop", None)
                        if desktop is not None and getattr(desktop, "enabled", False):
                            sup = SensorSupervisor(
                                runtime=rt,
                                enabled=True,
                                interval_s=float(desktop.interval_seconds),
                            )
                            sup.start()
                            rt._sensor_supervisor = sup
                except Exception as exc:
                    logger.debug("Gateway sensor supervisor skipped: %s", exc)
                self._owner_task = asyncio.create_task(self._owner_maintenance_loop(rt))
                self._pending_resume = True
        except Exception as exc:
            logger.debug("Gateway EntityRuntime attach skipped: %s", exc)
        if runtime_for_producers is not None and getattr(runtime_for_producers, "layout", None) is not None:
            try:
                self.task_owner.migrate_legacy(runtime_for_producers.layout)
            except Exception:
                logger.exception("Legacy task import failed; original queue retained")
        self.task_owner.start()
        resume_workers = getattr(self.orchestration, 'resume_pending', None)
        if callable(resume_workers):
            resume_workers()
        if self._background_producers is None:
            self._start_background_producers(runtime_for_producers)
        if self._background_client is not None:
            self._background_task = asyncio.create_task(self._background_loop())

    async def _bounded_shutdown(self, app: web.Application) -> None:
        if not self._owns_store:
            return
        await self.task_owner.stop()
        if self._background_task is not None:
            self._background_task.cancel()
            await asyncio.gather(self._background_task, return_exceptions=True)
            self._background_task = None
        if self._owner_task is not None:
            self._owner_task.cancel()
            await asyncio.gather(self._owner_task, return_exceptions=True)
            self._owner_task = None
        if self._background_producers is not None:
            try:
                self._background_producers.stop()
            except Exception:
                logger.debug("background producer shutdown skipped", exc_info=True)
            self._background_producers = None
        cancel_all = getattr(self.orchestration, "cancel_all", None)
        if callable(cancel_all):
            try:
                unresolved = await cancel_all(timeout_seconds=1.5)
                if unresolved:
                    logger.warning(
                        "IDE worker cancellation unconfirmed during shutdown: %s",
                        ", ".join(unresolved),
                    )
            except Exception:
                logger.exception("IDE orchestration shutdown failed")
        tasks = list(self._running_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=2.0)
        self.store.recover_interrupted_sessions()
        self.store.release_process()
        self._owns_store = False

    async def _collect_background(self) -> int:
        client = self._background_client
        rows = await asyncio.to_thread(client.query, "background_messages", {"limit": 50}, timeout_s=5)
        if not isinstance(rows, list):
            raise ValueError("Native background outbox returned an invalid response")
        for row in rows:
            receipt = self.store.receive_background(row)
            if not receipt["replayed"]:
                self.event_bus.fanout(receipt["event"])
                try:
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    EntityRuntime.get_singleton().record_background_completed(
                        str(row.get("id") or row.get("delivery_id") or ""),
                        row,
                        session_id=str(row.get("session_id") or "dispatcher"),
                    )
                except Exception:
                    pass
            # Receipt + transcript + event are committed before native ACK.
            # Failed/lost ACK retries delivery, never the model or its tools.
            await asyncio.to_thread(client.command, "acknowledge_background", {"delivery_id": row["delivery_id"]})
        return len(rows)

    async def _owner_maintenance_loop(self, runtime: Any) -> None:
        """Heartbeat, sleep-time, and indexing owned by the resident Gateway."""
        interval = float(os.environ.get("JAEGER_HEARTBEAT_INTERVAL_S") or 0) or 30.0
        while True:
            try:
                await asyncio.to_thread(self._owner_tick, runtime)
            except Exception as exc:
                logger.warning("Owner maintenance tick failed: %s", exc)
            await asyncio.sleep(max(1.0, interval))

    def _owner_tick(self, runtime: Any) -> None:
        """Sleep-time consolidation. Heartbeat/board/cron live on the producer lease."""
        sleep_due = os.environ.get("JAEGER_SLEEP_DUE", "").strip() in {"1", "true", "yes"}
        force_hb = os.environ.get("JAEGER_HEARTBEAT_DUE", "").strip() in {"1", "true", "yes"}
        if not (sleep_due or force_hb):
            return
        try:
            runtime.sleep_time_processor.run_sleep_cycle(reason="gateway_idle")
        except Exception as exc:
            logger.debug("Sleep-time cycle skipped: %s", exc)

    def _start_background_producers(self, runtime: Any) -> None:
        from jaeger_ai.core.runtime.background_producers import BackgroundProducers

        layout = getattr(runtime, "layout", None)
        if layout is None:
            try:
                from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
                inst = os.environ.get("JAEGER_INSTANCE_DIR")
                layout = InstanceLayout(root=Path(inst) if inst else resolve_instance_dir())
            except Exception as exc:
                logger.debug("Gateway background producer layout unavailable: %s", exc)
                return
        name = ""
        try:
            name = str(getattr(runtime.identity, "display_name", "") or "")
        except Exception:
            name = ""
        producers = BackgroundProducers(layout, self._background_sink(), display_name=name)
        if producers.try_start():
            self._background_producers = producers
            logger.info("Gateway owns instance background producers")
        else:
            logger.info("Gateway skipped background producers; another process holds the lease")

    def _background_sink(self) -> Any:
        app = self

        class _Sink:
            def is_busy(self) -> bool:
                return bool(app._running_tasks)

            def last_user_quiet_s(self) -> float:
                return time.monotonic() - app._last_human_at

            def last_user_session(self) -> str:
                return app._last_human_session or "desktop-app"

            def submit_turn(self, prompt: str, *, session: str, request_id: str, source: str) -> dict[str, Any]:
                return app.submit_background_turn(
                    prompt, session_id=session, request_id=request_id, source=source,
                )

        return _Sink()

    def submit_background_turn(
        self,
        prompt: str,
        *,
        session_id: str,
        request_id: str,
        source: str,
    ) -> dict[str, Any]:
        """Admit and run a background turn on the Gateway event loop.

        Safe to call from a producer thread. Identical request_id replays;
        a busy session is skipped rather than crashing the producer.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return {"text": "", "error": "gateway loop is not running", "halt_reason": "error"}
        future = asyncio.run_coroutine_threadsafe(
            self._run_background_turn(
                prompt, session_id=session_id, request_id=request_id, source=source,
            ),
            loop,
        )
        return future.result(timeout=float(os.environ.get("JAEGER_BACKGROUND_TURN_WAIT_S") or 3600))

    async def _run_background_turn(
        self,
        prompt: str,
        *,
        session_id: str,
        request_id: str,
        source: str,
    ) -> dict[str, Any]:
        requested = {"options": {"source": source, "background": True}}
        try:
            admitted = self.store.admit_request(
                session_id, prompt, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            # Same request_id with different text or choices is a conflict.
            # Returning the old output would hide the changed input.
            return {
                "text": "",
                "error": str(exc),
                "status": "conflict",
                "replayed": False,
                "halt_reason": "conflict",
            }
        except RequestBusy:
            return {"text": "", "error": "Turn already in progress", "halt_reason": "busy", "skipped": True}
        except ValueError as exc:
            return {"text": "", "error": str(exc), "halt_reason": "error"}

        self._start_admitted_turn(admitted, session_id, prompt)
        rid = admitted["request_id"]
        task = self._running_tasks.get(rid)
        if task is not None:
            await task
        row = self.store.get_request(rid) or {}
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        return {
            "text": str(result.get("output") or ""),
            "error": result.get("error"),
            "status": row.get("status"),
            "replayed": bool(admitted.get("replayed")),
            "halt_reason": "interrupted" if row.get("status") == "cancelled" else None,
            "execution_unknown": row.get("status") == "execution_unknown",
        }

    def _start_admitted_turn(
        self, admitted: dict[str, Any], session_id: str, text: str,
    ) -> None:
        turn_id = admitted["turn_id"]
        rid = admitted["request_id"]
        if admitted.get("event"):
            self.event_bus.fanout(admitted["event"])
        elif not admitted.get("replayed"):
            self.event_bus.publish(session_id, "turn.start", {
                "turn_id": turn_id, "request_id": rid, "text": text,
            })
        if admitted.get("accepted") and rid not in self._running_tasks:
            self._cancellations.register(rid)
            self._running_tasks[rid] = asyncio.create_task(
                self._execute_turn(
                    session_id, turn_id, text, request_id=rid,
                    execution=_admitted_execution(admitted),
                )
            )

    def _resume_safe_unknown_requests(self, runtime: Any) -> None:
        """Continue execution_unknown turns whose runs RecoveryManager resumed.

        Pending EffectLedger rows stay BLOCKED. A request with no native_run_id
        is re-dispatched only when no effect is indeterminate.
        """
        report = getattr(runtime, "_recovery_report", None)
        resumed = set(getattr(report, "resumed", None) or [])
        pending_keys = list(getattr(report, "pending_effects", None) or [])
        pending_run_ids = set()
        for key in pending_keys:
            # Effect keys are `{run_id}:{tool}:{payload}`.
            pending_run_ids.add(str(key).split(":", 1)[0])
        try:
            unknown = self.store.list_requests(status="execution_unknown")
        except Exception:
            return
        for req in unknown:
            rid = str(req.get("request_id") or "")
            sid = str(req.get("session_id") or "")
            turn_id = str(req.get("turn_id") or "")
            text = str(req.get("input_text") or "")
            native = str(req.get("native_run_id") or "")
            if not rid or not sid or not text:
                continue
            if native and native in pending_run_ids:
                logger.warning("Request %s stays blocked; pending effects on run %s", rid, native)
                continue
            if not native and pending_keys:
                logger.warning("Request %s stays blocked; indeterminate effects present", rid)
                continue
            if rid in self._running_tasks:
                continue
            logger.info("Re-dispatching recovered request %s run=%s", rid, native or "unbound")
            self._cancellations.register(rid)
            self._running_tasks[rid] = asyncio.create_task(
                self._execute_turn(sid, turn_id, text, request_id=rid,
                                   execution=_admitted_execution(req))
            )

    async def _background_loop(self) -> None:
        while True:
            try:
                count = await self._collect_background()
                self._background_status = {"enabled": True, "ok": True, "last_poll": time.time(), "received": count}
            except Exception as exc:
                self._background_status = {"enabled": True, "ok": False, "error": str(exc)}
                logger.warning("Background delivery pending: %s", exc)
            await asyncio.sleep(2)

    def _setup_routes(self) -> None:
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/v1/runtime/status", self.handle_runtime_status)
        self.app.router.add_get("/version", self.handle_version)
        # Agent catalog — persistence spine for Mac app + WebUI clients.
        self.app.router.add_get("/v1/agents", self.handle_list_agents)
        self.app.router.add_post("/v1/agents", self.handle_create_agent)
        self.app.router.add_get("/v1/agents/{id}", self.handle_get_agent)
        self.app.router.add_post("/v1/agents/{id}/activate", self.handle_activate_agent)
        self.app.router.add_post("/v1/agents/{id}/handoff", self.handle_handoff_agent)
        self.app.router.add_get("/v1/handoffs", self.handle_list_handoffs)
        self.app.router.add_get("/v1/sessions", self.handle_list_sessions)
        self.app.router.add_post("/v1/sessions", self.handle_create_session)
        self.app.router.add_get("/v1/sessions/{id}", self.handle_get_session)
        self.app.router.add_delete("/v1/sessions/{id}", self.handle_delete_session)
        self.app.router.add_patch("/v1/sessions/{id}", self.handle_rename_session)
        self.app.router.add_post("/v1/sessions/{id}/turns", self.handle_send_turn)
        self.app.router.add_post("/v1/sessions/{id}/cancel", self.handle_cancel_turn)
        self.app.router.add_post("/v1/sessions/{id}/reconcile", self.handle_reconcile)
        self.app.router.add_get("/v1/sessions/{id}/requests/{request_id}", self.handle_get_request)
        self.app.router.add_get("/v1/sessions/{id}/requests/{request_id}/changes", self.handle_file_changes)
        self.app.router.add_post("/v1/sessions/{id}/requests/{request_id}/changes/undo", self.handle_file_changes)
        self.app.router.add_post("/v1/sessions/{id}/handoff", self.handle_session_handoff)
        self.app.router.add_get("/v1/sessions/{id}/stream", self.handle_stream_events)
        self.app.router.add_get("/v1/sessions/{id}/events", self.handle_session_events_json)
        self.app.router.add_get("/v1/requests/{request_id}", self.handle_get_request_any_session)
        self.app.router.add_get("/v1/sessions/{id}/activity", self.handle_activity_history)
        self.app.router.add_get("/v1/handoffs/{id}", self.handle_get_handoff)
        self.app.router.add_post("/v1/approvals/{id}", self.handle_resolve_approval)
        self.app.router.add_get("/v1/approvals", self.handle_list_approvals)
        self.app.router.add_get("/v1/runtime/frameworks", self.handle_runtime_frameworks)
        self.app.router.add_get("/v1/runtime/models", self.handle_runtime_models)
        self.app.router.add_get("/v1/runtime/capabilities", self.handle_runtime_capabilities)
        self.app.router.add_get("/v1/runtime/skills", self.handle_runtime_skills)
        self.app.router.add_post("/v1/sessions/{id}/ide/{ide_request_id}", self.handle_ide_result)
        self.app.router.add_get("/v1/runtime/autonomy", self.handle_get_autonomy)
        self.app.router.add_post("/v1/runtime/autonomy", self.handle_set_autonomy)
        self.app.router.add_get("/v1/sessions/{id}/attachments", self.handle_list_attachments)
        self.app.router.add_post("/v1/sessions/{id}/attachments", self.handle_add_attachment)
        self.app.router.add_get("/v1/tasks", self.handle_tasks)
        self.app.router.add_post("/v1/tasks", self.handle_tasks)
        self.app.router.add_get("/v1/tasks/{id}", self.handle_task)
        self.app.router.add_post("/v1/tasks/{id}/cancel", self.handle_task_cancel)
        self.app.router.add_post("/v1/tasks/{id}/approve", self.handle_task_approve)
        self.app.router.add_get("/v1/orchestration/workers", self.handle_list_orchestration_workers)
        self.app.router.add_post("/v1/orchestration/tasks", self.handle_create_orchestration_task)
        self.app.router.add_get("/v1/orchestration/tasks/{id}", self.handle_get_orchestration_task)
        self.app.router.add_post("/v1/orchestration/tasks/{id}/cancel", self.handle_cancel_orchestration_task)

    async def handle_version(self, request: web.Request) -> web.Response:
        """Stable, read-only identity for clients and deployment checks."""
        return web.json_response({
            "component": "jaeger-gateway",
            "version": JAEGER_VERSION,
            "protocol_version": "1",
        })

    async def _probe_http(self, url: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
        """Probe a dependency; never raises — fail-closed callers inspect ok=False.

        HTTP 2xx alone is not enough: bridge may answer 200 with ``{"ok": false}``.
        """
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    body = await resp.text()
                    payload_ok: bool | None = None
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and "ok" in parsed:
                            payload_ok = bool(parsed.get("ok"))
                        elif isinstance(parsed, dict) and "status" in parsed:
                            payload_ok = str(parsed.get("status")).lower() in {
                                "ok", "healthy", "up", "ready",
                            }
                    except Exception:  # noqa: BLE001
                        payload_ok = None
                    http_ok = 200 <= resp.status < 300
                    ok = http_ok if payload_ok is None else (http_ok and payload_ok)
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "payload_ok": payload_ok,
                        "body_excerpt": body[:200],
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {"ok": False, "status_code": 0, "url": url, "error": str(exc)}

    async def _probe_webui_legacy_chat(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Probe locked WebUI legacy ``/api/chat``. HTTP 500 ⇒ fail-closed (M8).

        Non-500 responses (including 400/404 validation) mean the route is alive.
        Connection errors also fail closed — chat surface unreachable.
        """
        url = f"{LOCKED_WEBUI_URL}/api/chat"
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json={"session_id": "__jaeger_health_probe__", "message": "ping"},
                ) as resp:
                    body = await resp.text()
                    # CoS: must not claim all_green while legacy /api/chat returns 500.
                    # Validation errors establish reachability only, not readiness.
                    ok = 200 <= resp.status < 300
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "required": True,
                        "body_excerpt": body[:200],
                        "note": (
                            "legacy /api/chat returned 500"
                            if resp.status == 500
                            else "legacy chat readiness is not verified by a validation response"
                        ),
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {
                "ok": False,
                "status_code": 0,
                "url": url,
                "required": True,
                "error": str(exc),
                "note": "legacy /api/chat unreachable",
            }

    async def _probe_native_mcp(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Read-only MCP and native-agent readiness; never executes chat."""
        from jaeger_ai.core.frameworks.jaeger import (
            MCP_URL, MCP_HOST_HEADER, mcp_api_key,
        )
        headers = {"Accept": "application/json, text/event-stream", "Host": MCP_HOST_HEADER}

        async def terminate_session() -> None:
            """Release the stdio backend allocated by the MCP handshake."""
            if "Mcp-Session-Id" not in headers:
                return
            try:
                timeout = ClientTimeout(total=min(1.0, timeout_s))
                async with ClientSession(timeout=timeout) as client:
                    async with client.delete(MCP_URL, headers=headers) as response:
                        # Session termination is best-effort health-check cleanup. A
                        # proxy may answer 404 after already reaping the session.
                        if response.status not in {200, 202, 204, 404}:
                            response.raise_for_status()
            except Exception:  # noqa: BLE001 — cleanup must not hide probe health
                pass

        async def rpc(client, method, params, identity):
            async with client.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "id": identity, "method": method, "params": params,
            }) as response:
                response.raise_for_status()
                if response.headers.get("Mcp-Session-Id"):
                    headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                # A server may keep SSE open after the response; consume only
                # the matching RPC result, with a bounded total body and timeout.
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    size = 0
                    async for line in response.content:
                        size += len(line)
                        if size > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                        if line.startswith(b"data:"):
                            value = json.loads(line[5:])
                            if value.get("id") == identity:
                                break
                    else:
                        raise ValueError("MCP returned no matching result")
                else:
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                    value = json.loads(raw)
                if value.get("error") or value.get("id") != identity:
                    raise ValueError("MCP rejected readiness probe")
                return value.get("result", {})

        try:
            key = mcp_api_key()
            if key:
                headers["Authorization"] = f"Bearer {key}"
            async with asyncio.timeout(timeout_s):
                async with ClientSession(timeout=ClientTimeout(total=timeout_s)) as client:
                    await rpc(client, "initialize", {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "jaeger-health", "version": "1"},
                    }, 1)
                    async with client.post(MCP_URL, headers=headers, json={
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                    }) as response:
                        response.raise_for_status()
                    catalog = await rpc(client, "tools/list", {}, 2)
                    names = {t.get("name") for t in catalog.get("tools", [])}
                    chat_available = bool(names & {"chat", "jaeger_chat"})
                    health_tool = next((n for n in ("jaeger_bridge_health", "bridge_health") if n in names), None)
                    agent_ready = False
                    if chat_available and health_tool:
                        health_result = await rpc(client, "tools/call", {"name": health_tool, "arguments": {}}, 3)
                        if not health_result.get("isError"):
                            health = health_result.get("structuredContent")
                            if not isinstance(health, dict):
                                health = json.loads(self._mcp_chat_text(health_result))
                            agent_ready = bool(health.get("ok")) and health.get("ready", {}).get("agent") == "ready"
                    transport_ready = chat_available
                    ok = chat_available and agent_ready
                    return {
                        "ok": ok, "required": True, "url": MCP_URL,
                        "transport_ready": transport_ready,
                        "chat_tool_available": chat_available,
                        "agent_ready": agent_ready,
                        "execution_verified": False,
                        "note": "Native bridge readiness; model execution not probed",
                    }
        except Exception as exc:
            return {
                "ok": False, "required": True, "url": MCP_URL,
                "error": type(exc).__name__,
                "transport_ready": False,
                "chat_tool_available": False,
                "agent_ready": False,
                "execution_verified": False,
            }
        finally:
            await terminate_session()

    async def handle_health(self, request: web.Request) -> web.Response:
        """Backend readiness is independent of optional HTTP adapters and UIs."""
        owner = self._probe_owner_runtime()
        bridge, ollama, webui_chat, native_mcp = await asyncio.gather(
            self._probe_http(LOCKED_BRIDGE_HEALTH_URL),
            self._probe_http(f"{LOCKED_OLLAMA_URL}/api/tags"),
            self._probe_http(LOCKED_WEBUI_URL),
            self._probe_native_mcp(),
        )
        # Read-only surface availability. Never create fake chat requests from
        # health checks, and never mistake a 404 for a working conversation.
        checks = {
            "gateway": {"ok": True, "url": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}"},
            "bridge": {**bridge, "required": False},
            "ollama": {**ollama, "required": True},
            "webui": {**webui_chat, "required": False, "chat_execution_verified": False},
            "native_mcp": native_mcp,
            "owner_runtime": owner,
        }
        native_mcp["required"] = not owner["ok"]
        required_ok = (
            bool(ollama.get("ok"))
            and (owner["ok"] or bool(native_mcp.get("ok")))
        )
        all_green = required_ok
        status = "ok" if all_green else "unhealthy"
        payload = {
            "status": status,
            "service": "jaeger-gateway",
            "version": JAEGER_VERSION,
            "architecture": "openclaw-parity",
            "persistence_spine": True,
            "agents_api": "/v1/agents",
            "fundamentals_fee_gated": False,
            "fail_closed": True,
            "health_scope": "backend_transport_readiness",
            "all_green": all_green,
            "checks": checks,
            "diagnostics": {"source_file": str(Path(__file__).resolve()),
                            "background_delivery": self._background_status,
                            "session_store": str(self.store.path.resolve()),
                            "instance_root": str(self._instance_root()),
                            "schema_version": self.store.schema_version(),
                            "process_lease": self.store.process_lease(),
                            **self._entity_diagnostics()},
            "capabilities": {
                "native_agent": owner["ok"] or bool(native_mcp.get("ok")),
                "transport_ready": bool(native_mcp.get("transport_ready") or native_mcp.get("chat_tool_available")),
                "agent_ready": owner["ok"] or bool(native_mcp.get("agent_ready")),
                "execution_verified": bool(native_mcp.get("execution_verified")),
                "end_to_end_chat_verified": False,
            },
            "locked_endpoints": {
                "ollama": LOCKED_OLLAMA_URL,
                "webui": LOCKED_WEBUI_URL,
                "gateway": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}",
            },
        }
        return web.json_response(payload, status=200 if all_green else 503)

    @staticmethod
    def _probe_owner_runtime() -> dict[str, Any]:
        """Check the same resident OWNER used by turn execution, without a turn."""
        from jaeger_ai.core.entity.ownership import EntityRuntimeMode
        from jaeger_ai.core.entity.runtime import EntityRuntime

        try:
            runtime = EntityRuntime.get_singleton()
            resident = bool(getattr(runtime, "is_resident", False))
            owner = runtime.mode == EntityRuntimeMode.OWNER
            runtime.event_store.count()
            return {"ok": owner and resident, "resident": resident, "owner": owner,
                    "execution_verified": False}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "execution_verified": False}

    async def handle_runtime_status(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.entity.runtime_status import collect_runtime_status
        payload = collect_runtime_status(include_network=True)
        return web.json_response(payload, status=200 if payload.get("ready") else 503)

    def _entity_diagnostics(self) -> dict[str, Any]:
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            return {
                "entity_id": rt.identity.entity_id,
                "entity_resident": bool(getattr(rt, "is_resident", False)),
                "event_count": int(rt.current_state.total_events_processed),
            }
        except Exception as exc:
            return {"entity_id": None, "entity_error": str(exc)}

    def _registry(self):
        from jaeger_ai.core.agent_registry import AgentRegistry

        return AgentRegistry()

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        """List JaegerNativeAgent + ThirdPartyAgent for Mac app / WebUI.

        Query: ``?kind=`` and/or ``?role=lead|specialist|runtime``.
        Unfiltered response is the full catalog including ``lead``.
        """
        kind = request.query.get("kind")
        role = request.query.get("role")
        registry = self._registry()
        if kind or role:
            agents = [
                a.to_dict()
                for a in registry.list_agents(kind=kind or None, role=role or None)
            ]
            payload: dict[str, Any] = {"agents": agents}
            if kind:
                payload["kind"] = kind
            if role:
                payload["role"] = role
            return web.json_response(payload)
        return web.json_response(registry.to_catalog())

    async def handle_create_agent(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        name = str(body.get("name") or "").strip()
        if not name:
            return web.json_response({"error": "name is required"}, status=400)
        kind = str(body.get("kind") or "jaeger_native").strip()
        try:
            record = self._registry().create_agent(
                name,
                kind=kind,
                role=(str(body["role"]) if body.get("role") else None),
                display_name=(str(body["display_name"]) if body.get("display_name") else None),
                adapter=(str(body["adapter"]) if body.get("adapter") else None),
                profile_id=(str(body["profile_id"]) if body.get("profile_id") else None),
                endpoint=(str(body["endpoint"]) if body.get("endpoint") else None),
                port=(int(body["port"]) if body.get("port") is not None else None),
                metadata=dict(body.get("metadata") or {}),
                make_active=bool(body.get("make_active", False)),
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        self.event_bus.publish("*", "agent.created", {"agent": record.to_dict()})
        return web.json_response(record.to_dict(), status=201)

    async def handle_get_agent(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        return web.json_response(record.to_dict())

    async def handle_activate_agent(self, request: web.Request) -> web.Response:
        """Switch active agent — never fee-gated (fundamentals stay open)."""
        agent_id = request.match_info["id"]
        try:
            record = self._registry().set_active(agent_id)
        except KeyError:
            return web.json_response({"error": "Agent not found"}, status=404)
        self.event_bus.publish("*", "agent.activated", {"agent": record.to_dict()})
        return web.json_response(record.to_dict())

    async def handle_handoff_agent(self, request: web.Request) -> web.Response:
        """Lead → specialist handoff using a real isolated child run."""
        to_agent_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        task = str(body.get("task") or "").strip()
        if not task:
            return web.json_response({"error": "task is required"}, status=400)
        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        from_id = str(body.get("from_agent_id") or "native:jaeger").strip()
        require_approval = bool(body.get("require_approval", True))
        request_id = str(body.get("request_id") or uuid.uuid4().hex)
        parent_run_id = body.get("parent_run_id") or body.get("parent_request_id")
        parent_chain = list(body.get("parent_chain") or [])
        depth = int(body.get("delegation_depth") or len(parent_chain))
        permitted_context = str(body.get("permitted_context") or "")
        timeout_s = int(body.get("timeout_seconds") or 120)
        allowed_tools = body.get("allowed_tools") or []
        if not isinstance(allowed_tools, list) or any(not isinstance(x, str) or not x.strip() for x in allowed_tools):
            return web.json_response({"error": "allowed_tools must be a list of tool names"}, status=400)
        if "dispatcher" in permitted_context.lower() and "dispatcher transcript" in permitted_context.lower():
            return web.json_response({"error": "dispatcher transcript is not permitted specialist context"}, status=403)

        existing = self.store.get_handoff_by_request(request_id)
        if existing:
            prior = existing.get("metadata") or {}
            if (existing["task"] != task or existing["to_agent_id"] != target.id
                or existing["from_agent_id"] != from_id
                or existing.get("parent_run_id") != parent_run_id
                or existing["require_approval"] != require_approval
                or prior.get("permitted_context", "") != permitted_context
                or sorted(prior.get("allowed_tools") or []) != sorted(allowed_tools)
                or prior.get("timeout_seconds", 120) != timeout_s):
                return web.json_response(
                    {"error": "Request identity was already used for different input"},
                    status=409,
                )
            return web.json_response(existing, status=200)

        from jaeger_ai.core.agent_registry.specialist_runtime import check_delegation_limits
        limit_error = check_delegation_limits(
            from_agent_id=from_id,
            to_agent_id=target.id,
            parent_chain=parent_chain,
            depth=depth,
            active_children=self.store.count_active_handoffs(parent_run_id=str(parent_run_id) if parent_run_id else None),
        )
        if limit_error:
            return web.json_response({"error": limit_error, "ok": False, "status": "rejected"}, status=409)

        approval_id = f"approval_{uuid.uuid4().hex[:12]}" if require_approval else None
        handoff_id = f"handoff_{uuid.uuid4().hex[:12]}"
        record = {
            "id": handoff_id,
            "request_id": request_id,
            "from_agent_id": from_id,
            "to_agent_id": target.id,
            "parent_run_id": parent_run_id,
            "child_run_id": None,
            "task": task,
            "status": "pending_approval" if require_approval else "admitted",
            "require_approval": require_approval,
            "approval_id": approval_id,
            "result": {},
            "metadata": {
                "target_display": target.display_name,
                "target_role": (target.metadata or {}).get("role"),
                "specialty": (target.metadata or {}).get("specialty"),
                "permitted_context": permitted_context,
                "allowed_tools": list(allowed_tools),
                "timeout_seconds": timeout_s,
                "parent_chain": [*parent_chain, from_id],
                "delegation_depth": depth + 1,
            },
        }
        saved = self.store.save_handoff(record)
        if require_approval and approval_id:
            self.store.create_approval(
                approval_id=approval_id,
                kind="handoff",
                prompt=f"Allow handoff to {target.display_name}?",
                options=["once", "deny"],
                request_id=request_id,
                metadata={"handoff_id": handoff_id, "to_agent_id": target.id},
            )
            loop = asyncio.get_running_loop()
            self.pending_approvals[approval_id] = loop.create_future()
            self.event_bus.publish("*", "approval.request", {
                "approval_id": approval_id,
                "handoff_id": handoff_id,
                "kind": "handoff",
                "from_agent_id": from_id,
                "to_agent_id": target.id,
                "task": task,
                "options": ["once", "deny"],
                "prompt": f"Allow handoff to {target.display_name}?",
            })
        else:
            self._running_tasks[request_id] = asyncio.create_task(self._execute_handoff(handoff_id))
        self.event_bus.publish("*", "agent.handoff", {"handoff": saved})
        return web.json_response(saved, status=202 if require_approval else 200)

    async def handle_list_handoffs(self, request: web.Request) -> web.Response:
        records = self.store.list_handoffs()
        return web.json_response({"handoffs": records, "count": len(records)})

    async def handle_get_handoff(self, request: web.Request) -> web.Response:
        record = self.store.get_handoff(request.match_info["id"])
        if record is None:
            return web.json_response({"error": "Handoff not found"}, status=404)
        if record["status"] == "execution_unknown":
            import hashlib
            from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
            rid = record.get("request_id") or record["id"]
            native_id = hashlib.sha256(("handoff:" + rid).encode()).hexdigest()
            session = specialist_session(record["to_agent_id"], rid)
            receipt = self._native_receipt(native_id, session)
            if receipt and not receipt.get("execution_unknown") and receipt.get("status") in {"completed", "failed", "cancelled"}:
                reply = receipt.get("reply") or {}
                record = self.store.save_handoff({**record, "status": receipt["status"],
                    "result": {"ok": receipt["status"] == "completed", "status": receipt["status"],
                               "summary": reply.get("text") or reply.get("error") or reply.get("halt_reason") or "",
                               "worker_session_id": session, "metadata": {"native_receipt": receipt}}})
                self.event_bus.publish("*", "agent.handoff.finished", {"handoff": record})
        return web.json_response(record)

    async def handle_list_sessions(self, request: web.Request) -> web.Response:
        profile = request.query.get("profile")
        sessions = self.store.list_sessions(profile=profile)
        return web.json_response({"sessions": sessions})

    async def handle_create_session(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        # The Gateway mints and owns session IDs. A client-supplied id is a
        # hint at most: it is never trusted as the stored identity, because a
        # second writer of the namespace is how three session stores happened.
        # Clients adopt the id the Gateway returns (cross-client continuation
        # works because every client reads the same row).
        session_id = uuid.uuid4().hex
        title = str(body.get("title") or "New Conversation")
        workspace = str(body.get("workspace") or "")
        metadata = dict(body.get("metadata") or {})
        # Profile binding is enforced HERE, gateway-side. The client may name a
        # profile; the gateway validates it against the framework registry and
        # stamps it — the id no longer carries the profile, so a client cannot
        # mint a "hermes" session by shaping its id.
        profile = str(body.get("profile") or "").strip()
        if not profile:
            profile = "jaeger"
        from jaeger_ai.contract.frameworks import canonical_runtime, UnknownFramework
        try:
            profile = canonical_runtime(profile)
        except UnknownFramework:
            return web.json_response({"error": f"Unknown profile: {profile}"}, status=400)
        # Record where it was started so the sidebar can split browser from
        # terminal conversations for each framework.
        surface = normalise_surface(body.get("source") or metadata.get("source"))
        if surface and "source" not in metadata:
            metadata = {**metadata, "source": surface}

        session = self.store.ensure_session(
            session_id,
            title=title,
            profile=profile,
            workspace=workspace,
            metadata=metadata,
        )
        self.event_bus.publish(session_id, "session.created", {"session": session})
        return web.json_response(session, status=201)

    async def handle_get_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        # Surfaces chrome polls GET without SSE — stamp role/display_name
        # after handoff so the UI can render the active agent identity.
        return web.json_response(self._enrich_session_agent(session))

    async def handle_activity_history(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if not self.store.get_session(session_id):
            return web.json_response({"error": "Session not found"}, status=404)
        try:
            after = max(0, int(request.query.get("after", "0")))
        except ValueError:
            return web.json_response({"error": "Invalid cursor"}, status=400)
        return web.json_response(self.store.activity_history(session_id, after))

    async def handle_rename_session(self, request: web.Request) -> web.Response:
        """PATCH /v1/sessions/{id} ``{"title": "..."}`` — the one place titles change."""
        session_id = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        title = body.get("title") if isinstance(body, dict) else None
        if not isinstance(title, str) or not title.strip():
            return web.json_response({"error": "title must be a non-empty string"}, status=400)
        session = self.store.rename_session(session_id, title.strip()[:200])
        if session is None:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.updated", {"session": session})
        return web.json_response(session)

    async def handle_delete_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        deleted = self.store.delete_session(session_id)
        if not deleted:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.deleted", {"session_id": session_id})
        return web.json_response({"deleted": True})

    async def handle_session_handoff(self, request: web.Request) -> web.Response:
        """Transfer a session to another agent (P6) — never fee-gated.

        Body: ``{to_agent_id, reason?, keep_history?: true}``.
        Updates session ``agent_id`` metadata; optionally clears transcript.
        """
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        to_agent_id = str(body.get("to_agent_id") or "").strip()
        if not to_agent_id:
            return web.json_response({"error": "to_agent_id is required"}, status=400)
        keep_history = bool(body.get("keep_history", True))
        reason = str(body.get("reason") or "").strip() or None

        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            # Surfaces: missing agent must be a clean 404 (not 500 / empty body).
            return web.json_response({"error": "Agent not found"}, status=404)
        # Lead ↔ specialist (and runtime) handoffs are all allowed; role is not gated.

        previous_agent_id = session.get("agent_id") or (session.get("metadata") or {}).get(
            "agent_id"
        )
        if not keep_history:
            self.store.clear_messages(session_id)

        patch = {
            "agent_id": target.id,
            "previous_agent_id": previous_agent_id,
            "handoff_reason": reason,
            "handed_off_at": time.time(),
        }
        updated = self.store.update_metadata(session_id, patch)
        if updated is None:
            return web.json_response({"error": "Session not found"}, status=404)

        agent = target.to_dict()
        self.event_bus.publish(
            session_id,
            "session.handoff",
            {
                "session_id": session_id,
                "from_agent_id": previous_agent_id,
                "to_agent_id": target.id,
                "agent": agent,
                "reason": reason,
                "keep_history": keep_history,
            },
        )
        return web.json_response(
            {
                "session_id": session_id,
                "agent_id": target.id,
                "previous_agent_id": previous_agent_id,
                "agent": agent,
                "session": updated,
                "keep_history": keep_history,
                "reason": reason,
            }
        )

    async def handle_send_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "Missing turn text"}, status=400)
        # Profile binding is enforced gateway-side: a turn may not switch the
        # profile a session was created with. Cross-client continuation
        # (start on the phone, finish in the IDE) works because both clients
        # address the same gateway-owned session id.
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            session = self.store.get_session(session_id)
            if session is None:
                return web.json_response({"error": "Session not found"}, status=404)
            bound = str(session.get("profile") or "").strip().lower()
            if bound and bound != requested_profile.strip().lower():
                return web.json_response(
                    {"error": f"This conversation belongs to {bound}; start a new chat to talk to {requested_profile}"},
                    status=409,
                )
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None

        requested = {key: body.get(key) for key in EXECUTION_INPUT_KEYS if body.get(key) is not None}
        options = requested.get("options")
        if isinstance(options, dict) and "ide" in options:
            # The IDE's view of what is open. Only the allow-listed, size-capped
            # fields survive; nothing else can ride in through this key.
            from jaeger_ai.core.entity.ide_context import clean as clean_ide_context
            options = {**options}
            cleaned = clean_ide_context(options.pop("ide"))
            if cleaned:
                options["ide"] = cleaned
            if options:
                requested["options"] = options
            else:
                requested.pop("options")
        if requested.get("model") and not requested.get("provider"):
            # A routed id ("ollama-cloud/glm") names its provider lane.
            lane, _ = split_routed_model_id(str(requested["model"]))
            if lane:
                requested["provider"] = lane
        try:
            admitted = self.store.admit_request(
                session_id, text, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            session = self.store.get_session(session_id) or {}
            return web.json_response(
                {
                    "error": str(exc),
                    "session_id": session_id,
                    "status": session.get("status"),
                    "agent_id": self._session_agent_id(session),
                },
                status=409,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        turn_id = admitted["turn_id"]
        rid = admitted["request_id"]
        options = (admitted.get("execution") or {}).get("options") or {}
        if not options.get("background"):
            self._last_human_at = time.monotonic()
            self._last_human_session = session_id
        self._start_admitted_turn(admitted, session_id, text)

        result = admitted.get("result") or {}
        payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "request_id": rid,
            "status": admitted["status"] if admitted.get("replayed") else "running",
            "replayed": bool(admitted.get("replayed")),
        }
        if result.get("output") is not None:
            payload["output"] = result.get("output")
        if admitted.get("event"):
            # Durable cursor of this turn's turn.start: a client streams
            # ``?last_event_id=<start_event_id - 1>`` to follow just this turn.
            payload["start_event_id"] = admitted["event"]["event_id"]
        return web.json_response(payload)

    def _session_agent_id(self, session: dict[str, Any] | None) -> str | None:
        """Resolve session agent_id from top-level or metadata (handoff patch)."""
        if not session:
            return None
        aid = session.get("agent_id")
        if aid:
            return str(aid)
        meta = session.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("agent_id"):
            return str(meta["agent_id"])
        return None

    def _enrich_session_agent(self, session: dict[str, Any]) -> dict[str, Any]:
        """Attach agent_id / role / display_name for chrome GET without SSE."""
        out = dict(session)
        agent_id = self._session_agent_id(session)
        if not agent_id:
            return out
        out["agent_id"] = agent_id
        try:
            agent = self._registry().get_agent(agent_id)
        except Exception:  # noqa: BLE001 — GET must stay readable
            logger.exception("Failed to enrich session agent %s", agent_id)
            agent = None
        if agent is None:
            out.setdefault("role", None)
            out.setdefault("display_name", None)
            return out
        role = getattr(agent, "role", None)
        out["role"] = role.value if hasattr(role, "value") else (str(role) if role else None)
        out["display_name"] = agent.display_name
        return out

    def _resolve_session_agent(self, session_id: str):
        """Look up the session's AgentRecord via AgentRegistry (or None)."""
        session = self.store.get_session(session_id)
        agent_id = self._session_agent_id(session)
        if not agent_id:
            return None
        try:
            return self._registry().get_agent(agent_id)
        except Exception:  # noqa: BLE001 — chat must not fail closed on registry
            logger.exception("Failed to resolve session agent %s", agent_id)
            return None

    @staticmethod
    def _instance_root() -> Path:
        """Resolve the active Jaeger instance root (SI character + memory home)."""
        try:
            from jaeger_ai.core.instance.instance import resolve_instance_dir

            return resolve_instance_dir()
        except Exception:  # noqa: BLE001 — gateway must still answer without instance
            home = Path(os.environ.get("JAEGER_HOME", str(Path.home() / ".jaeger")))
            return home / "instances" / "jaeger"

    @staticmethod
    def _si_character_prompt() -> str | None:
        """Load the live SI brief from personality/Character.character_block()."""
        try:
            from jaeger_ai.features.personality.character import active_character

            character = active_character(JaegerGatewayApp._instance_root())
            if character is None:
                return None
            block = (character.character_block() or "").strip()
            return block or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("SI character prompt unavailable: %s", exc)
            return None

    @staticmethod
    def _si_soul_prompt() -> str | None:
        """Load SOUL.md via load_soul(InstanceLayout) — same root as character.

        Returns None on an error or empty document. Used only for the
        explicitly selected lead/default text-mode system prompt.
        """
        try:
            from jaeger_ai.core.instance.instance import InstanceLayout
            from jaeger_ai.core.prompt_documents import load_soul

            layout = InstanceLayout(root=JaegerGatewayApp._instance_root())
            soul = (load_soul(layout) or "").strip()
            return soul or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("SI SOUL prompt unavailable: %s", exc)
            return None

    @staticmethod
    def _system_prompt_for_agent(agent) -> str:
        """Build the turn system prompt.

        Lead / default text-mode turns use readable SI sections:
        ``[Identity]`` from ``Character.character_block``, then optional
        ``[SOUL]`` from ``load_soul(InstanceLayout)`` (same
        ``resolve_instance_dir`` root). Empty SOUL is omitted. Specialist
        handoffs keep a thin specialty overlay — not a second soul.
        MCP native lead path does not use this prompt.
        """
        role = getattr(agent, "role", None) if agent is not None else None
        role_s = role.value if hasattr(role, "value") else (str(role) if role else "")

        if agent is not None and role_s == "specialist":
            display = str(
                getattr(agent, "display_name", None)
                or getattr(agent, "name", None)
                or "Specialist"
            )
            meta = getattr(agent, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            specialty = str(meta.get("specialty") or meta.get("role") or "").strip()
            summary = str(meta.get("summary") or "").strip()
            parts = [f"You are {display}."]
            parts.append(f"You are the {specialty or display} specialist.")
            parts.append(
                f"When asked for your display name, reply with exactly: SPECIALIST:{display}."
            )
            if summary:
                parts.append(summary.rstrip(".") + ".")
            parts.append("Reply briefly and helpfully.")
            return " ".join(parts)

        sections: list[str] = []
        si = JaegerGatewayApp._si_character_prompt()
        if si:
            sections.append(f"[Identity]\n{si}")
        soul = JaegerGatewayApp._si_soul_prompt()
        if soul:
            sections.append(f"[SOUL]\n{soul}")
        if sections:
            return "\n\n".join(sections)

        if agent is None:
            return "You are Jaeger. Reply briefly and helpfully."
        display = str(
            getattr(agent, "display_name", None)
            or getattr(agent, "name", None)
            or "Jaeger"
        )
        meta = getattr(agent, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        summary = str(meta.get("summary") or "").strip()
        parts = [f"You are {display}."]
        if role_s == "lead":
            parts.append("You are the lead assistant.")
        if summary:
            parts.append(summary.rstrip(".") + ".")
        parts.append("Reply briefly and helpfully.")
        return " ".join(parts)

    @staticmethod
    def _mcp_chat_text(result: Any) -> str:
        """Extract assistant text from an MCP tools/call chat result."""
        if not isinstance(result, dict):
            return str(result or "").strip()
        if result.get("isError"):
            content = result.get("content", [])
            err = ""
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        err += str(item.get("text") or "")
            elif isinstance(content, str):
                err = content
            raise RuntimeError(err or "MCP tool error")
        content = result.get("content", [])
        text = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text += str(item.get("text") or "")
        elif isinstance(content, str):
            text = content
        else:
            # Some adapters nest reply under structuredContent / text.
            nested = result.get("structuredContent") or result.get("text")
            if isinstance(nested, str):
                text = nested
            elif isinstance(nested, dict):
                text = str(nested.get("text") or nested.get("reply") or "")
        return text.strip()

    async def _native_lead_turn(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        mcp_session: str | None = None,
        allowed_tools: list[str] | None = None,
        is_subordinate: bool = True,
    ) -> tuple[str, str] | None:
        """Lead turn via the Jaeger-owned native MCP server on loopback.

        Returns ``(response_text, backend_label)`` on success, or ``None`` when
        no result was confirmed. An uncertain execution must not be retried here.
        Does not invent a parallel agent runtime — reuses hermes adapters.

        Shared MCP chat session: literal ``dispatcher`` — same key Mac Chat /
        WebUI / Hermes adapter bind via DispatcherStore (see
        core.frameworks/jaeger.py rewrite to session_id='dispatcher',
        features/webui/service/session_unify.py, features/dispatcher/store.py
        DISPATCHER). Gateway /v1/sessions UUID stays separate for SSE/store;
        only the MCP chat session_id is shared so one self / one transcript.
        Specialist child runs pass an isolated ``mcp_session``.
        """
        native_session = mcp_session or "dispatcher"

        def _blocking_chat() -> tuple[str, str]:
            from urllib.parse import urlparse

            from jaeger_ai.core.frameworks.jaeger import (
                MCPClient,
                MCP_URL,
                MCP_HOST_HEADER,
                mcp_api_key,
            )

            # Reuse the framework MCP client against Jaeger's native HTTP server.
            args: dict[str, Any] = {"message": text, "session_id": native_session}
            if request_id:
                args["request_id"] = request_id
            if allowed_tools is not None:
                args["allowed_tools"] = allowed_tools
            if is_subordinate:
                args["is_subordinate"] = True
            logger.info(
                "native MCP chat session_id=%s request_id=%s",
                native_session,
                request_id,
            )
            key = mcp_api_key()
            signature = (MCPClient, MCP_URL, key, MCP_HOST_HEADER)
            with self._mcp_transport_lock:
                if signature != self._mcp_transport_signature:
                    client = MCPClient(MCP_URL, key, MCP_HOST_HEADER)
                    client.initialize()
                    names = frozenset(tool.get("name") for tool in client.list_tools())
                    self._mcp_transport = client
                    self._mcp_tool_names = names
                    self._mcp_transport_signature = signature
                client = self._mcp_transport
                tool_name = next(
                    (name for name in ("jaeger_chat", "chat") if name in self._mcp_tool_names), None)
                if tool_name is None:
                    raise RuntimeError("MCP chat tool unavailable")
                if request_id and self.store.get_request(request_id) is not None:
                    self.store.bind_native(
                        request_id,
                        native_run_id=request_id,
                        native_session=native_session,
                        status="running",
                    )
                result = client._execute_call(tool_name, args)
            if result.get("isError"):
                raise RuntimeError("MCP chat returned a tool error")
            response_text = JaegerGatewayApp._mcp_chat_text(result)
            if not response_text:
                raise RuntimeError("MCP chat returned empty content")
            label = "mcp"
            host = (urlparse(MCP_URL).netloc or "").strip()
            if host:
                label = f"mcp:{host}"
            return response_text, label

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_blocking_chat),
                timeout=NATIVE_LEAD_MCP_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — caller records the unconfirmed turn
            logger.warning(
                "native MCP turn has no confirmed result: %s",
                exc,
            )
            if "MCP credential missing" in str(exc):
                raise
            if getattr(exc, "code", None) in {401, 403}:
                raise RuntimeError(f"MCP credential rejected (HTTP {exc.code})") from exc
            return None

    @staticmethod
    def _history_before_admitted_user(
        session: dict[str, Any] | None,
        request_row: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Return history before this request's separately supplied prompt.

        Admission persists the current user message and request row with the
        same timestamp. Model callsites then pass the current prompt as a
        separate argument. Remove only that exact final admitted row; never
        value-deduplicate, because an earlier identical user message is valid
        conversation history. Callers without a durable admission row retain
        their history unchanged.
        """
        messages = list((session or {}).get("messages") or [])
        if not messages or not request_row:
            return messages
        tail = messages[-1]
        if (
            isinstance(tail, dict)
            and tail.get("role") == "user"
            and tail.get("timestamp") == request_row.get("created_at")
        ):
            return messages[:-1]
        return messages

    async def _ollama_chat(
        self,
        text: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        """Live text turn via locked Ollama — never routes through :8813."""
        target_model = model or DEFAULT_OLLAMA_MODEL
        if not target_model:
            raise RuntimeError(
                "Explicit text-only mode requires JAEGER_GATEWAY_OLLAMA_MODEL"
            )
        sys_content = system_prompt or "You are Jaeger. Reply briefly and helpfully."

        # Capability inventory injection when user asks about capabilities or tools
        if any(w in text.lower() for w in ("capabilities", "tools available", "what can you do", "what tools")):
            try:
                from jaeger_ai.interfaces.mcp_server import capability_inventory
                inv = capability_inventory()
                tool_list = []
                for grp, gdata in (inv.get("groups") or {}).items():
                    tool_list.extend(gdata.get("agent_tools") or [])
                if tool_list:
                    tools_str = ", ".join(sorted(set(tool_list)))
                    sys_content += f"\n\n[Live Capabilities Inventory]\nAvailable tools: {tools_str}"
            except Exception:
                pass

        messages = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in (history or [])
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        if not messages or messages[-1] != {"role": "user", "content": text}:
            messages.append({"role": "user", "content": text})

        # Multimodal / Vision extraction: find uploaded image references in attachments, history, or text
        import base64
        import re
        from pathlib import Path

        image_b64s: list[str] = []
        all_text_blobs = [text] + [str(item.get("content") or "") for item in (history or [])]
        seen_paths: set[str] = set()

        for att in (attachments or []):
            safe_path = att.get("safe_path")
            mime = att.get("mime_type") or ""
            if safe_path and (mime.startswith("image/") or Path(safe_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}):
                p = Path(safe_path)
                if p.is_file() and str(p) not in seen_paths:
                    seen_paths.add(str(p))
                    try:
                        image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                    except Exception:
                        pass
        for blob in all_text_blobs:
            for match in re.finditer(r"stored at\s+([^\s]+\.(?:png|jpg|jpeg|webp|gif))", blob, re.IGNORECASE):
                img_path = match.group(1).strip()
                if img_path not in seen_paths:
                    seen_paths.add(img_path)
                    p = Path(img_path)
                    if p.is_file():
                        try:
                            image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                        except Exception:
                            pass
            for match in re.finditer(r"(?:image attachment|attached image|file):\s*(?:[^\s]+\s+at\s+)?([^\s)]+\.(?:png|jpg|jpeg|webp|gif))", blob, re.IGNORECASE):
                img_path = match.group(1).strip()
                if img_path not in seen_paths:
                    seen_paths.add(img_path)
                    p = Path(img_path)
                    if p.is_file():
                        try:
                            image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                        except Exception:
                            pass

        if image_b64s and messages:
            messages[-1]["images"] = image_b64s
            # If target model lacks vision, switch to known-good vision model kimi-k2.7-code:cloud
            if target_model not in {"kimi-k2.7-code:cloud", "qwen3.5:397b-cloud", "minicpm-v:latest"}:
                target_model = "kimi-k2.7-code:cloud"

        payload = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": sys_content,
                },
                *messages,
            ],
            "stream": False,
        }
        # Ollama Cloud models (":cloud" suffix, e.g. kimi-k2.7-code:cloud)
        # require Authorization: Bearer <key>. This call never attached one,
        # unlike every other model path in the codebase (see
        # external_model.py:556) — confirmed root cause of real 401s
        # ("Ollama chat HTTP 401: {\"error\":\"Unauthorized\"}\n") on the
        # vision-test / non-image-doc-test sessions in
        # gateway_sessions.sqlite3. Local Ollama needs no key, so an absent
        # one is fine (matches external_model.py's `if key else {}`).
        ollama_headers: dict[str, str] = {}
        ollama_key = (
            os.environ.get("OLLAMA_API_KEY")
            or os.environ.get("OLLAMA_CLOUD_API_KEY")
            or os.environ.get("OLLAMA_KEY")
        )
        if not ollama_key:
            try:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                from jaeger_agent import credentials as creds
                layout = getattr(EntityRuntime.get_singleton(), "layout", None)
                if layout is not None:
                    ollama_key = creds.get_credential(layout, "ollama_cloud_api_key") or None
            except Exception:
                ollama_key = None
        if ollama_key:
            ollama_headers["Authorization"] = f"Bearer {ollama_key}"

        timeout = ClientTimeout(total=90)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{LOCKED_OLLAMA_URL}/api/chat", json=payload, headers=ollama_headers
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Ollama chat HTTP {resp.status}: {body[:500]}"
                    )
                data = json.loads(body)
        message = (data.get("message") or {})
        content = str(message.get("content") or "").strip()
        if not content:
            raise RuntimeError(f"Ollama returned empty content: {body[:500]}")
        return content

    def _turn_attachments(
        self, session_id: str, execution: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Attachments this turn may use: exactly those frozen at admission.

        An upload after admission belongs to a later turn. A snapshotted
        attachment whose content no longer matches its admitted sha256 is
        withheld rather than silently substituted.
        """
        rows = self.store.list_attachments(session_id)
        if execution is None:
            return rows
        by_id = {row.get("attachment_id"): row for row in rows}
        chosen = []
        for ref in execution.get("attachments") or []:
            row = by_id.get(ref.get("attachment_id"))
            if row is None:
                continue
            if ref.get("sha256") and row.get("sha256") and ref["sha256"] != row["sha256"]:
                logger.warning("Attachment %s changed after admission; withheld", ref.get("attachment_id"))
                continue
            chosen.append(row)
        return chosen

    def _turn_stream_callbacks(self, session_id: str, request_id: str) -> tuple[Any, Callable[[], None]]:
        """Agent callbacks that stream this turn to clients as durable events.

        ``turn.delta`` carries answer text (what Swift's voice loop and the
        bridge speak/render incrementally); ``turn.reasoning`` carries model
        deliberation, never part of the answer. Tool lifecycle events contain
        only a catalog-shaped name, phase, outcome, and bounded duration: raw
        arguments, results, and errors never enter the client event stream.
        Deltas are batched — each publish is a durable row — and are flushed
        before reasoning/tool boundaries and the terminal event so replay
        reproduces the exact observed order.
        """
        from jaeger_agent.loop.callbacks import AgentCallbacks

        row = self.store.get_request(request_id) or {}
        ids = {"turn_id": row.get("turn_id") or request_id, "request_id": request_id}
        lock = threading.Lock()
        pending: list[str] = []
        last = [time.monotonic()]
        # ``AgentCallbacks`` predates call ids.  Starts and finishes are serial
        # at the loop boundary (including parallel read batches), so a FIFO per
        # raw catalog name pairs them without publishing either the args or the
        # raw name. UUIDs remain stable because the event payload is durable.
        active_tools: dict[str, list[str]] = {}
        file_snapshots: dict[str, list[dict]] = {}

        def flush() -> None:
            with lock:
                text = "".join(pending)
                pending.clear()
                last[0] = time.monotonic()
            if text:
                self.event_bus.publish(session_id, "turn.delta", {**ids, "delta": text, "channel": "provisional"})

        def on_delta(piece: str) -> None:
            with lock:
                pending.append(str(piece))
                due = sum(map(len, pending)) >= TURN_DELTA_BATCH_CHARS or (
                    time.monotonic() - last[0] >= TURN_DELTA_BATCH_S)
            if due:
                flush()

        def on_reasoning(text: str) -> None:
            flush()
            if text:
                self.event_bus.publish(session_id, "turn.reasoning", {**ids, "text": str(text)})

        def on_tool_progress(name: str, phase: str, data: Any) -> None:
            # ``done`` is followed immediately by the richer ``tool_done``
            # callback, which knows success/failure. Publishing here would
            # create two terminal rows for one call.
            if phase != "start":
                return
            flush()
            raw_name = str(name or "")
            self.event_bus.publish(session_id, "turn.progress", {**ids, "channel": "progress"})
            activity_id = f"tool_{uuid.uuid4().hex}"
            with lock:
                active_tools.setdefault(raw_name, []).append(activity_id)
            if raw_name in {"write_file", "append_file", "patch", "delete_file", "move_file", "copy_file"} and isinstance(data, dict):
                try:
                    from jaeger_agent.workspace import _resolve_write
                    keys = ["src", "dst"] if raw_name == "move_file" else ["dst"] if raw_name == "copy_file" else ["path"]
                    file_snapshots[activity_id] = [self.file_changes.begin(_resolve_write(str(data[key]))) for key in keys]
                except Exception:
                    logger.debug("File change checkpoint unavailable for %s", raw_name)
            self.event_bus.publish(session_id, "tool.started", {
                **ids,
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": "started",
                "success": None,
                "ok": None,
                "text": "Started",
                **({"input": shown} if (shown := _tool_input_text(raw_name, data)) else {}),
            })

        def on_tool_done(
            name: str,
            args: dict[str, Any],
            result: Any,
            ok: bool,
            error: str | None,
            elapsed_s: float,
        ) -> None:
            # Arguments, result and error are intentionally not published. They
            # can contain credentials, file contents, prompts, or command output.
            # The one exception is ``update_plan``: its result is the plan the
            # model chose to show the operator, and only that validated payload
            # (steps, statuses, an optional note) leaves this callback.
            output_text = _tool_output_text(str(name or ""), result)
            plan_payload = None
            if str(name or "") == "update_plan" and ok and isinstance(result, dict) and result.get("ok"):
                plan_payload = {
                    "plan": [
                        {"step": str(item.get("step", ""))[:500], "status": str(item.get("status", ""))}
                        for item in (result.get("plan") or []) if isinstance(item, dict)
                    ][:50],
                    "summary": dict(result.get("summary") or {}),
                }
                if isinstance(result.get("explanation"), str):
                    plan_payload["explanation"] = result["explanation"][:500]
            del args, result, error
            flush()
            raw_name = str(name or "")
            with lock:
                queued = active_tools.get(raw_name)
                activity_id = queued.pop(0) if queued else f"tool_{uuid.uuid4().hex}"
                if queued == []:
                    active_tools.pop(raw_name, None)
            succeeded = bool(ok)
            snapshots = file_snapshots.pop(activity_id, [])
            if snapshots:
                try:
                    for snapshot in snapshots:
                        self.file_changes.finish(session_id, request_id, snapshot)
                    self.event_bus.publish(session_id, "files.changed", {
                        **ids, **self.file_changes.describe(session_id, request_id)})
                except (OSError, ValueError, UnicodeError):
                    logger.warning("File change checkpoint could not settle for %s", raw_name)
            duration = _safe_tool_duration(elapsed_s)
            phase = "completed" if succeeded else "failed"
            detail = (
                f"Completed in {duration:.3f}s"
                if succeeded
                else f"Failed after {duration:.3f}s"
            )
            self.event_bus.publish(session_id, f"tool.{phase}", {
                **ids,
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": phase,
                "success": succeeded,
                "ok": succeeded,
                "elapsed_s": duration,
                "text": detail,
                **({"output": output_text} if output_text else {}),
            })
            if plan_payload is not None:
                self.event_bus.publish(session_id, "turn.plan", {**ids, **plan_payload})

        return AgentCallbacks(
            stream_delta=on_delta,
            reasoning=on_reasoning,
            tool_progress=on_tool_progress,
            tool_done=on_tool_done,
        ), flush

    def _owner_react_turn(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        execution: dict[str, Any] | None = None,
        continuation_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one inner ReAct step in the EntityRuntime OWNER process."""
        from jaeger_ai.core.entity.runtime import EntityRuntime

        runtime = EntityRuntime.get_singleton()
        native = None
        try:
            row = self.store.get_request(request_id)
            native = str((row or {}).get("native_run_id") or "") or None
        except Exception:
            pass
        if execution is not None:
            # Admitted request: execute exactly what was frozen at admission.
            selection = execution
            lane, selected_model = split_routed_model_id(str(execution.get("model") or ""))
        else:
            # Pre-snapshot (digest v1) request recovered after upgrade.
            session = self.store.get_session(session_key) or {}
            selection = session.get("metadata") or {}
            lane, selected_model = split_routed_model_id(str(selection.get("model") or session.get("model") or ""))
        callbacks, flush = self._turn_stream_callbacks(session_key, request_id)
        from jaeger_agent.tool_executor import tool_allowlist

        grant = execution.get("allowed_tools") if execution is not None else None
        try:
            # The admitted tool grant scopes the agent built for this turn
            # ([] = no tools; absent = the owner's normal catalog).
            from jaeger_agent.task_port import task_scope
            request_row = self.store.get_request(request_id) or {}
            options = selection.get("options") or {}
            source = "background" if options.get("background") else "user"
            with task_scope(self.task_owner, session_id=session_key, request_id=request_id,
                            execution=selection, user_text=request_row.get("input_text", prompt), source=source), \
                    tool_allowlist(list(grant) if grant is not None else None):
                return runtime.run_subordinate_react(
                    prompt,
                    session_key=session_key,
                    request_id=request_id,
                    callbacks=callbacks,
                    continuation_state=continuation_state,
                    project_root=str(selection.get("workspace") or "") or None,
                    confirmation_provider=_GatewayToolConfirmationProvider(self, session_key, request_id),
                    native_run_id=native,
                    model=selected_model or None,
                    provider=str(selection.get("provider") or lane or "") or None,
                    on_model=on_model,
                    cancellation=self._cancellations.get(request_id),
                    on_run=lambda run_id: self.store.bind_native(
                        request_id,
                        native_run_id=run_id,
                        native_session=f"{OWNER_RUN_SESSION_PREFIX}{session_key}",
                    ),
                )
        finally:
            flush()

    def _continued_owner_react(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        execution: dict[str, Any] | None = None,
        objective: str = "",
    ) -> dict[str, Any]:
        """One admitted request: inner ReAct plus owner-side continuation."""
        from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn

        continuation_state: dict[str, Any] = {}

        def step(inner_prompt: str) -> dict[str, Any]:
            out = self._owner_react_turn(
                inner_prompt, session_key=session_key, request_id=request_id,
                on_model=on_model, execution=execution,
                continuation_state=continuation_state,
            )
            return {
                **out,
                "text": out.get("text") or "",
                "halt_reason": out.get("halt_reason"),
                "status": "completed",
            }

        from jaeger_ai.core.runtime.work_ledger import ledger_scope, last_completion
        with ledger_scope(session_key, resume_completed=bool(((execution or {}).get("options") or {}).get("task_id")) and not bool(((execution or {}).get("options") or {}).get("verification_error"))):
            result = run_continued_turn(
                step, prompt, objective=objective or prompt,
                durable=bool(((execution or {}).get("options") or {}).get("task_id")),
                max_steps=8 if ((execution or {}).get("options") or {}).get("task_id") else None,
                is_cancelled=lambda: self._cancellations.is_cancelled(request_id),
                on_checkpoint=lambda checkpoint: self.event_bus.publish(
                    session_key, "turn.checkpoint", {**checkpoint, "request_id": request_id}),
            )
            return {**result, "task_completion": last_completion()}

    async def _execute_turn(
        self,
        session_id: str,
        turn_id: str,
        text: str,
        *,
        request_id: str | None = None,
        execution: dict[str, Any] | None = None,
    ) -> None:
        """Background turn executor: lead via native MCP, specialist via Ollama.

        ``execution`` is the snapshot frozen at admission (model, provider,
        attachment revisions). ``None`` only for a pre-snapshot request
        recovered after upgrade, which keeps the historical session reads.

        Final assistant text is persisted before turn.finish is published.
        Cancellation is explicit; a dropped SSE client does not stop work.
        """
        session = self.store.get_session(session_id)
        session_agent_id = self._session_agent_id(session)
        agent = self._resolve_session_agent(session_id)
        system_prompt = self._system_prompt_for_agent(agent)
        agent_fields: dict[str, Any] = {}
        if session_agent_id:
            agent_fields["agent_id"] = session_agent_id
            agent_fields["role"] = None
            agent_fields["display_name"] = None
        if agent is not None:
            role = getattr(agent, "role", None)
            agent_fields = {
                "agent_id": agent.id,
                "role": role.value if hasattr(role, "value") else str(role),
                "display_name": agent.display_name,
            }
        role_s = str(agent_fields.get("role") or "")
        rid = request_id or turn_id
        admitted_request = self.store.get_request(rid)
        # What the operator wrote, before attachment notes are inlined. Lane
        # decisions read this: an inlined "inspect it with the vision_analyze
        # tool" note made a plain question about an image look actionable.
        request_text = text

        try:
            atts = self._turn_attachments(session_id, execution)
        except Exception:
            atts = []
        if atts:
            try:
                from jaeger_ai.core.frameworks.run_input import inline_webui_text_attachments
                mapped = [
                    {
                        "path": a.get("safe_path"),
                        "name": a.get("original_filename") or a.get("stored_filename"),
                        "mime": a.get("mime_type"),
                        "is_image": str(a.get("mime_type") or "").startswith("image/"),
                    }
                    for a in atts
                ]
                text = inline_webui_text_attachments(text, mapped)
            except Exception:
                logger.debug("attachment materialize failed", exc_info=True)

        try:
            if self._cancellations.is_cancelled(rid):
                self._finish_cancelled(session_id, turn_id, rid, agent_fields, "cancelled before native dispatch")
                return

            backend = LOCKED_OLLAMA_URL
            model = DEFAULT_OLLAMA_MODEL
            response_text: str | None = None

            text_only = (session or {}).get("metadata", {}).get("execution_mode") == "text_only"
            from jaeger_ai.core.runtime.autonomous_runner import is_actionable_request
            actionable = bool(
                (session or {}).get("metadata", {}).get("actionable")
                or is_actionable_request(request_text)
            )

            loop = asyncio.get_running_loop()

            async def _run_native_coro(prompt: str) -> tuple[str, str] | None:
                if self._cancellations.is_cancelled(rid):
                    raise RuntimeError("cancelled before native dispatch")
                return await self._native_lead_turn(session_id, prompt, request_id=rid, is_subordinate=True)

            def _sync_react(prompt: str, session_key: str = session_id) -> dict[str, Any]:
                nonlocal backend, model
                session_atts = self._turn_attachments(session_id, execution)
                has_image = any(str(a.get("mime_type") or "").startswith("image/") for a in session_atts)
                if not has_image:
                    # The operator's request, not ``prompt``: the Entity
                    # prefixes recalled history, and an image filename from
                    # another session's turn sent an unrelated WebUI question
                    # down the tool-less vision lane.
                    import re as _re
                    has_image = bool(_re.search(r"\.(?:png|jpg|jpeg|webp)\b", request_text, _re.IGNORECASE))
                # A question about an image goes straight to a vision model.
                # Anything that asks for work goes through the Entity with its
                # tools and Authority: in an image session, "save this to a
                # file" used to be answered "I'll create the file" by a model
                # with no tools, and recorded as completed.
                if has_image and not actionable and _asks_about_the_image(request_text):
                    backend = LOCKED_OLLAMA_URL
                    model = "kimi-k2.7-code:cloud"
                    current = self.store.get_session(session_id) or {}
                    chat_fut = asyncio.run_coroutine_threadsafe(
                        self._ollama_chat(
                            # request_text, not prompt: prompt has been
                            # rewritten by inline_webui_text_attachments to
                            # say "inspect it with the vision_analyze tool",
                            # a tool this bare _ollama_chat call never
                            # attaches. The model spent its whole output
                            # budget narrating a tool call it couldn't make
                            # and returned empty content (verified against
                            # real failures: session da59748d.../97afa8d5...,
                            # "Ollama returned empty content", thinking cut
                            # off mid-"I'll use visi[on_analyze]"). This path
                            # already sends the image directly as base64 via
                            # attachments=session_atts below, so it needs the
                            # operator's actual question, not a tool note.
                            request_text,
                            model=model,
                            system_prompt=system_prompt,
                            history=self._history_before_admitted_user(
                                current, admitted_request,
                            ),
                            attachments=session_atts,
                        ),
                        loop,
                    )
                    txt = chat_fut.result()
                    return {"text": txt, "status": "completed"}

                owner_first = os.environ.get("JAEGER_OWNER_REACT", "").strip() in {"1", "true", "yes"}
                try:
                    from jaeger_ai.core.entity.ownership import EntityRuntimeMode
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    rt = EntityRuntime.get_singleton()
                    if rt.mode == EntityRuntimeMode.OWNER and getattr(rt, "is_resident", False):
                        owner_first = True
                except Exception:
                    pass
                # The native-MCP-first lead turn is an isolated second path: the
                # resident Entity is the one executor. It runs only when the
                # operator re-enabled legacy paths, never as a silent fallback.
                if not owner_first and legacy_paths_enabled():
                    try:
                        native_res = asyncio.run_coroutine_threadsafe(_run_native_coro(prompt), loop).result()
                        if native_res is not None:
                            txt, b_end = native_res
                            backend = b_end
                            model = "jaeger-mcp"
                            return {"text": txt, "status": "completed"}
                    except Exception as ex:
                        logger.warning("Native MCP unavailable; OWNER in-process ReAct: %s", ex)
                def selected_model(name: str) -> None:
                    nonlocal model
                    model = name

                backend = "owner-react"
                return self._continued_owner_react(
                    prompt, session_key=session_key, request_id=rid,
                    on_model=selected_model,
                    execution=execution if session_key == session_id else None,
                    objective=request_text,
                )

            session_meta = (session.get("metadata") or {}) if isinstance(session, dict) and isinstance(session.get("metadata"), dict) else {}
            if execution is not None:
                req_model = provider_model_name(execution.get("model") or "")
            else:
                req_model = provider_model_name(session_meta.get("model") or (session or {}).get("model") or "")
            active_model = req_model or DEFAULT_OLLAMA_MODEL

            def _model_only_lane(prompt: str) -> dict[str, Any]:
                """A plain model answer with no tools: text-only chats and specialist agents.

                These are session-level choices made by the operator (a text-only
                conversation, an agent registered as a specialist), so they are an
                explicit lane at the Gateway boundary, next to the image lane. They
                do not pass through the agent loop and therefore never call tools.
                """
                nonlocal backend, model
                backend = LOCKED_OLLAMA_URL
                model = active_model
                current = self.store.get_session(session_id) or {}
                chat_fut = asyncio.run_coroutine_threadsafe(
                    self._ollama_chat(
                        prompt,
                        model=active_model,
                        system_prompt=system_prompt,
                        history=self._history_before_admitted_user(current, admitted_request),
                        attachments=self._turn_attachments(session_id, execution),
                    ),
                    loop,
                )
                return {"text": chat_fut.result(), "status": "completed"}

            from jaeger_ai.core.entity.runtime import EntityRuntime
            runtime = EntityRuntime.get_singleton()

            turn_meta = {
                "execution_mode": "text_only" if text_only else "agent",
                "actionable": actionable,
                "role": role_s,
                "agent_id": agent_fields.get("agent_id"),
                "specialist": agent_fields.get("agent_id") if role_s == "specialist" else None,
            }

            # One turn shape. The main loop is the agent loop: build the request with
            # its fenced memory, run it, record the answer. Chat turns and durable
            # child tasks take exactly this path; nothing gates it.
            try:
                prepared = await asyncio.to_thread(
                    runtime.prepare_turn,
                    text,
                    session_id=session_id,
                    source="gateway",
                    request_id=rid,
                    gateway_session=session,
                    metadata=turn_meta,
                    ide_context=((execution or {}).get("options") or {}).get("ide"),
                )
                prompt = prepared.prompt
            except Exception:
                # Memory is an enrichment: if reading it fails the operator's
                # request must still reach the agent, unadorned.
                logger.warning("turn context unavailable for %s; running the bare request", rid, exc_info=True)
                prepared, prompt = None, text
            model_only = (text_only and not actionable) or role_s == "specialist"
            turn_result = await asyncio.to_thread(_model_only_lane if model_only else _sync_react, prompt)
            if prepared is not None and not turn_result.get("error"):
                try:
                    await asyncio.to_thread(runtime.finish_turn, prepared, str(turn_result.get("text") or ""))
                except Exception:
                    logger.warning("could not record the answer for %s", rid, exc_info=True)

            if self._cancellations.is_cancelled(rid):
                if self._settle_cancelled(session_id, turn_id, rid, agent_fields):
                    return
                raise RuntimeError(
                    "Cancellation requested after native acceptance; "
                    "outcome is unconfirmed until reconcile"
                )

            if turn_result.get("error"):
                raise RuntimeError(str(turn_result["error"]))

            response_text = str(turn_result.get("text") or "")

            self.event_bus.publish(session_id, "turn.delta", {
                "turn_id": turn_id,
                "request_id": rid,
                "delta": "",
                "model": model,
                "backend": backend,
                **agent_fields,
            })

            agent_lane = str(backend).startswith("mcp") or backend == "owner-react"
            result = {
                "output": response_text,
                "status": "completed",
                "backend": backend,
                "model": model,
                "turn_id": turn_id,
                "execution_mode": "agent" if agent_lane else "text_only",
                "capabilities": {
                    "native_tools": agent_lane,
                    "native_memory": agent_lane,
                },
                "verification": turn_result.get("verification"),
                "task_completion": turn_result.get("task_completion"),
                "halt_reason": turn_result.get("halt_reason"),
                "trace_id": turn_result.get("trace_id"),
                **agent_fields,
            }
            self._persist_terminal(rid, session_id, "completed", result, assistant_text=response_text, record_entity_event=False)
        except Exception as exc:
            if self._cancellations.is_cancelled(rid) and self._settle_cancelled(
                session_id, turn_id, rid, agent_fields,
            ):
                return
            logger.exception("Turn execution failed: %s", exc)
            bound = self.store.get_request(rid) or {}
            after_native = bool(bound.get("native_run_id"))
            owner_run = str(bound.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX)
            if after_native and owner_run:
                # The Entity's own run: its effect ledger, not the MCP
                # receipt store, says whether anything was left half-done.
                from jaeger_ai.core.entity.runtime import EntityRuntime
                after_native = EntityRuntime.run_has_indeterminate_effects(str(bound["native_run_id"]))
            status = "execution_unknown" if after_native else "failed"
            receipt = (
                self._native_receipt(bound.get("native_run_id"), bound.get("native_session"))
                if after_native and not owner_run else None
            )
            reply = (receipt or {}).get("reply") if isinstance(receipt, dict) else None
            reply = reply if isinstance(reply, dict) else {}
            if receipt and receipt.get("execution_unknown") is False and receipt.get("status") in {"completed", "failed", "cancelled"}:
                status = receipt["status"]
            result = {"error": str(exc), "turn_id": turn_id, "status": status, **agent_fields}
            if status == "completed":
                result = {
                    "output": str(reply.get("text") or ""),
                    "status": "completed",
                    "turn_id": turn_id,
                    "backend": "native_receipt",
                    **agent_fields,
                }
            if receipt:
                result["native_receipt"] = receipt
            self._persist_terminal(
                rid,
                session_id,
                status,
                result,
                assistant_text=str(reply.get("text") or "") or None if status == "completed" else None,
            )
        finally:
            self._running_tasks.pop(rid, None)
            self._cancellations.release(rid)

    def _settle_cancelled(
        self,
        session_id: str,
        turn_id: str,
        request_id: str,
        agent_fields: dict[str, Any],
    ) -> bool:
        """Persist the single authoritative outcome of a cancelled request.

        The effect ledger decides: no run bound yet → ``cancelled``; the
        Entity's own run with every claimed effect resolved → ``cancelled``
        (completed effects stay recorded); a pending effect →
        ``execution_unknown`` until reconciled. Returns False for a legacy
        MCP-dispatched run, whose outcome only its native receipt can settle.
        """
        bound = self.store.get_request(request_id) or {}
        run_id = str(bound.get("native_run_id") or "")
        if not run_id:
            self._finish_cancelled(session_id, turn_id, request_id, agent_fields,
                                   "cancelled before native acceptance")
            return True
        if not str(bound.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX):
            return False
        from jaeger_ai.core.entity.runtime import EntityRuntime
        if EntityRuntime.run_has_indeterminate_effects(run_id):
            self._persist_terminal(request_id, session_id, "execution_unknown", {
                "status": "execution_unknown", "turn_id": turn_id, "output": None,
                "error": "cancelled with an external effect whose outcome is unknown; reconcile",
                **agent_fields,
            })
            return True
        self._finish_cancelled(session_id, turn_id, request_id, agent_fields,
                               "cancelled during execution")
        return True

    def _persist_terminal(
        self,
        request_id: str,
        session_id: str,
        status: str,
        result: dict[str, Any],
        *,
        assistant_text: str | None = None,
        record_entity_event: bool = True,
    ) -> None:
        session_status = "idle" if status in {"completed", "cancelled"} else status
        if assistant_text and status == "completed" and record_entity_event:
            try:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                EntityRuntime.get_singleton().record_agent_response(
                    assistant_text,
                    session_id=session_id,
                    model=str(result.get("model") or ""),
                    metadata=result,
                )
            except Exception:
                pass
        persisted = None
        try:
            persisted = self.store.complete_request(
                request_id,
                status=status,
                result=result,
                assistant_text=assistant_text,
                session_status=session_status,
            )
            if persisted.get("event"):
                self.event_bus.fanout(persisted["event"])
            if status == "completed" and not persisted.get("replayed"):
                try:
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    artifacts = []
                    if isinstance(result, dict):
                        for key in ("artifact", "path", "output_path"):
                            if result.get(key):
                                artifacts.append(str(result.get(key)))
                    EntityRuntime.get_singleton().record_background_completed(
                        request_id,
                        {
                            "summary": (assistant_text or str((result or {}).get("output") or ""))[:500],
                            "originating_event_id": str((result or {}).get("turn_id") or request_id),
                            "artifact_refs": artifacts,
                        },
                        session_id=session_id,
                    )
                except Exception:
                    pass
        except KeyError:
            if assistant_text is not None:
                self.store.append_message(session_id, "assistant", assistant_text)
            self.store.update_status(session_id, session_status)
            self.event_bus.publish(session_id, {
                "completed": "turn.finish", "failed": "turn.failed",
                "cancelled": "turn.cancelled", "execution_unknown": "turn.unknown",
            }[status], {**result, "request_id": request_id})

    def _finish_cancelled(
        self,
        session_id: str,
        turn_id: str,
        request_id: str,
        agent_fields: dict[str, Any],
        reason: str,
    ) -> None:
        result = {
            "status": "cancelled",
            "turn_id": turn_id,
            "output": None,
            "error": reason,
            **agent_fields,
        }
        self._persist_terminal(request_id, session_id, "cancelled", result)

    async def handle_file_changes(self, request: web.Request) -> web.Response:
        sid, rid = request.match_info["id"], request.match_info["request_id"]
        row = self.store.get_request(rid)
        if not row or row.get("session_id") != sid:
            return web.json_response({"error": "Request not found"}, status=404)
        if request.method == "POST" and row.get("status") not in {"completed", "failed", "cancelled"}:
            return web.json_response({"error": "Wait for the turn to settle before undoing"}, status=409)
        if request.method == "POST" and any(not task.done() for task in self._running_tasks.values()):
            return web.json_response({"error": "Wait for active Gateway turns to finish before undoing"}, status=409)
        try:
            if request.method == "POST":
                data = await asyncio.to_thread(self.file_changes.undo, sid, rid)
                self.event_bus.publish(sid, "files.changed", {"request_id": rid, **data})
            else:
                data = await asyncio.to_thread(self.file_changes.describe, sid, rid,
                                               contents=request.query.get("contents") == "1")
            return web.json_response(data)
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_get_request(self, request: web.Request) -> web.Response:
        row = self.store.get_request(request.match_info["request_id"])
        if row is None or row["session_id"] != request.match_info["id"]:
            return web.json_response({"error": "Request not found"}, status=404)
        return web.json_response(row)

    async def handle_get_request_any_session(self, request: web.Request) -> web.Response:
        """GET /v1/requests/{request_id} — request lookup without knowing the session.

        The WebUI shim holds only the request_id a turn admission returned;
        the session id is the Gateway's business. Resolves by request_id
        first, then by turn_id (the same fallback handle_cancel_turn uses).
        """
        rid = request.match_info["request_id"]
        row = self.store.get_request(rid) or self.store.get_request_by_turn(rid)
        if row is None:
            return web.json_response({"error": "Request not found"}, status=404)
        return web.json_response(row)

    async def handle_session_events_json(self, request: web.Request) -> web.Response:
        """GET /v1/sessions/{id}/events?since_event_id=N — the replay window as JSON.

        The SSE stream is for live subscribers; polling clients (the WebUI
        shim's run feed) need the same durable events as one JSON document.
        Same store, same schema, same cursor semantics as the stream.
        """
        session_id = request.match_info["id"]
        if not self.store.get_session(session_id):
            return web.json_response({"error": "Session not found"}, status=404)
        try:
            since = int(request.query.get("since_event_id") or 0)
        except ValueError:
            return web.json_response({"error": "Invalid since_event_id"}, status=400)
        window = self.event_bus.replay_window(session_id, since)
        return web.json_response(window)

    async def handle_cancel_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        request_id = str(body.get("request_id") or body.get("turn_id") or "").strip()
        if not request_id:
            return web.json_response({"error": "request_id is required"}, status=400)
        row = self.store.get_request(request_id) or self.store.get_request_by_turn(request_id)
        if row is None or row["session_id"] != session_id:
            return web.json_response({"error": "Request not found"}, status=404)
        if row["status"] in {"completed", "failed", "cancelled"}:
            return web.json_response({**row, "cancel_requested": False, "already_terminal": True})
        scope = self._cancellations.cancel(row["request_id"])
        updated = self.store.mark_request_status(row["request_id"], "cancelling") or row
        native_requested = False
        owner_run = str(updated.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX)
        if updated.get("native_run_id") and not owner_run:
            # Legacy MCP-dispatched run: only the native side can stop it.
            native_requested = await self._request_native_cancel(
                updated["native_run_id"], updated.get("native_session") or "dispatcher"
            )
        self._close_pending_approvals(row["request_id"])
        self.event_bus.publish(session_id, "turn.cancel", {
            "request_id": updated["request_id"],
            "turn_id": updated["turn_id"],
            "native_cancel_requested": native_requested,
            "native_cancel_confirmed": False,
            "interrupt_delivered": scope.interrupt_delivered,
        })
        return web.json_response({
            **updated,
            "cancel_requested": True,
            "native_cancel_requested": native_requested,
            "interrupt_delivered": scope.interrupt_delivered,
            "cancellation_confirmed": False,
        })

    def _close_pending_approvals(self, request_id: str) -> None:
        """Deny every approval still pending for a cancelled request.

        First writer wins in the store, so an operator decision that landed
        first is kept on record — but the confirm wait also sees the
        cancellation and refuses the action either way.
        """
        for approval in self.store.list_pending_approvals():
            if approval.get("request_id") != request_id:
                continue
            aid = approval["approval_id"]
            self.store.resolve_approval(aid, approved=False, decision="cancelled")
            future = self.pending_approvals.pop(aid, None)
            if future is not None and not future.done():
                future.set_result(False)

    async def _request_native_cancel(self, native_run_id: str, native_session: str) -> bool:
        try:
            from jaeger_ai.core.frameworks.jaeger import (
                MCPClient, MCP_URL, MCP_HOST_HEADER, mcp_api_key,
            )
            def _call() -> bool:
                client = MCPClient(MCP_URL, mcp_api_key(), MCP_HOST_HEADER)
                client.initialize()
                names = {tool.get("name") for tool in client.list_tools()}
                tool = next((n for n in ("cancel_turn", "jaeger_cancel_turn") if n in names), None)
                if tool is None:
                    return False
                result = client._execute_call(tool, {
                    "session_id": native_session,
                    "request_id": native_run_id,
                })
                return not result.get("isError")
            return await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001 — cancel request is best-effort
            logger.warning("native cancel request failed: %s", exc)
            return False

    async def handle_reconcile(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        request_id = str(body.get("request_id") or "").strip()
        if not request_id:
            if self.store.get_session(session_id) is None:
                return web.json_response({"error": "Session not found"}, status=404)
            return web.json_response({"error": "request_id is required"}, status=400)
        row = self.store.get_request(request_id)
        if row is None or row["session_id"] != session_id:
            return web.json_response({"error": "Request not found"}, status=404)
        if row["status"] in {"completed", "failed", "cancelled"}:
            return web.json_response({**row, "reconciled": False, "already_terminal": True})
        receipt = self._native_receipt(row.get("native_run_id"), row.get("native_session"))
        if receipt is None or receipt.get("execution_unknown") is not False:
            return web.json_response({
                **row,
                "reconciled": False,
                "execution_unknown": True,
                "error": "Native execution remains unknown; not replaying",
                "receipt": receipt,
            }, status=409)
        status = receipt.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            return web.json_response({
                **row,
                "reconciled": False,
                "execution_unknown": True,
                "error": "Native receipt is not terminal; not replaying",
                "receipt": receipt,
            }, status=409)
        output = ""
        reply = receipt.get("reply") or {}
        if isinstance(reply, dict):
            output = str(reply.get("text") or "")
        result = {
            "output": output,
            "status": status,
            "backend": "native_receipt",
            "turn_id": row["turn_id"],
            "reconciliation": receipt,
        }
        persisted = self.store.complete_request(
            request_id,
            status=status,
            result=result,
            assistant_text=output or None,
            session_status="idle" if status in {"completed", "cancelled"} else "failed",
            event_name="turn.reconciled",
        )
        if persisted.get("event"):
            self.event_bus.fanout(persisted["event"])
        return web.json_response({**persisted, "reconciled": True, "receipt": receipt})

    def _native_receipt(self, native_run_id: str | None, native_session: str | None) -> dict[str, Any] | None:
        if not native_run_id or not native_session:
            return None
        try:
            from jaeger_ai.core.runtime.native_turns import NativeTurns
            root = self._instance_root() / "run"
            result = NativeTurns(root, read_only=True).get(native_run_id, native_session)
            return result if result is not None else {"execution_unknown": True, "error": "run_not_found"}
        except Exception as exc:  # noqa: BLE001 — reconciliation must not crash
            logger.warning("native receipt lookup failed: %s", exc)
            return {"execution_unknown": True, "error": type(exc).__name__}

    async def handle_stream_events(self, request: web.Request) -> web.StreamResponse:
        """SSE for session + global (``*``) events.

        Surfaces P8 — approval request payload on the stream::

            event: approval.request
            data: {
              "approval_id": "approval_…",
              "kind": "handoff" | "tool" | str,
              "prompt": "Allow …?",
              "options": ["once", "deny"],
              "session_id": "…" | null,
              "handoff_id": "…" | null,
              "from_agent_id": "…" | null,
              "to_agent_id": "…" | null,
              "task": "…" | null
            }

        Resolve with ``POST /v1/approvals/{approval_id}`` body
        ``{"approved": true|false}`` → emits ``approval.resolved``.
        """
        session_id = request.match_info["id"]
        last_event_id = int(request.query.get("last_event_id") or 0)
        window = self.event_bus.replay_window(session_id, last_event_id)
        if window.get("cursor_expired"):
            return web.json_response(
                {
                    "error": "Resume cursor is no longer retained",
                    "oldest_event_id": window.get("oldest_event_id"),
                    "latest_event_id": window.get("latest_event_id"),
                    "valid_cursor": False,
                },
                status=410,
            )

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        try:
            async for evt in self.event_bus.subscribe(session_id, since_event_id=last_event_id):
                payload = json.dumps({
                    "event_id": evt.event_id,
                    "session_id": evt.session_id,
                    "event": evt.event,
                    "data": evt.data,
                    "timestamp": evt.timestamp,
                })
                chunk = f"id: {evt.event_id}\nevent: {evt.event}\ndata: {payload}\n\n"
                await response.write(chunk.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError, ReplayGap):
            pass

        return response

    async def handle_list_approvals(self, request: web.Request) -> web.Response:
        pending = self.store.list_pending_approvals()
        return web.json_response({"approvals": pending})

    async def handle_runtime_frameworks(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import framework_inventory
        return web.json_response({"frameworks": framework_inventory()})

    async def handle_runtime_models(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import provider_model_inventory, webui_model_catalog
        return web.json_response({
            **provider_model_inventory(),
            "webui_catalog": webui_model_catalog(),
        })

    async def handle_runtime_capabilities(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import capability_snapshot
        return web.json_response(capability_snapshot())

    # ── IDE bridge: the agent asks the operator's editor to do something ──────

    _IDE_KINDS = frozenset({"context", "open_file", "diagnostics"})

    def _ide_request(self, session_id: str, request_id: str, kind: str, args: dict, timeout: float) -> dict[str, Any]:
        """Blocking; called from the agent's worker thread. Publishes ``ide.request`` on the
        session stream, which the IDE extension answers via POST .../ide/{id}."""
        import concurrent.futures

        loop = getattr(self, "_loop", None)
        if kind not in self._IDE_KINDS or loop is None or not loop.is_running():
            return {"ok": False, "error": "The IDE bridge is unavailable"}
        ide_request_id = uuid.uuid4().hex[:12]
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._ide_pending[ide_request_id] = (session_id, future)
        payload = {"ide_request_id": ide_request_id, "request_id": request_id, "kind": kind,
                   "args": {k: (v if isinstance(v, (int, float)) else str(v)[:500]) for k, v in (args or {}).items()}}
        loop.call_soon_threadsafe(self.event_bus.publish, session_id, "ide.request", payload)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": "The IDE did not answer. Is the Jaeger panel open in your editor?"}
        finally:
            self._ide_pending.pop(ide_request_id, None)

    async def handle_ide_result(self, request: web.Request) -> web.Response:
        """POST /v1/sessions/{id}/ide/{ide_request_id}: the extension's answer. First one wins."""
        pending = self._ide_pending.get(request.match_info["ide_request_id"])
        if pending is None or pending[0] != request.match_info["id"]:
            return web.json_response({"error": "No such pending IDE request"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be an object"}, status=400)
        answer = {"ok": bool(body.get("ok")), **({"result": body["result"]} if body.get("ok") else {"error": str(body.get("error") or "IDE request failed")[:300]})}
        if not pending[1].done():
            pending[1].set_result(answer)
        return web.json_response({"delivered": True})

    def _config_path(self) -> Path | None:
        from jaeger_ai.core.entity.runtime import EntityRuntime

        layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        return getattr(layout, "config_path", None)

    async def handle_get_autonomy(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/autonomy: how much the agent asks before acting (saved setting)."""
        from jaeger_ai.core.runtime.autonomy import AUTONOMY, effective_autonomy

        return web.json_response({"autonomy": effective_autonomy(self._config_path()), "options": list(AUTONOMY)})

    async def handle_set_autonomy(self, request: web.Request) -> web.Response:
        """POST /v1/runtime/autonomy ``{"autonomy": "auto|scoped|ask"}``: saved to the
        instance config, which the approval provider reads on every tool call."""
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        from jaeger_ai.core.runtime.autonomy import AUTONOMY

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        mode = str((body or {}).get("autonomy") or "").strip().lower() if isinstance(body, dict) else ""
        if mode not in AUTONOMY:
            return web.json_response({"error": f"autonomy must be one of {list(AUTONOMY)}"}, status=400)
        path = self._config_path()
        if path is None or not Path(path).is_file():
            return web.json_response({"error": "No instance config to save to"}, status=409)
        config = load_yaml(Path(path), Config)
        config.automation.autonomy = mode
        dump_yaml(Path(path), config)
        return web.json_response({"autonomy": mode, "options": list(AUTONOMY)})

    async def handle_runtime_skills(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/skills[?q=text] — the skills a client can offer, one row each.

        Read-only. Rows carry name, category, description and lifecycle, never the
        skill body or its path, so a client menu can list them safely.
        """
        from jaeger_agent.skill_registry.playbook_skills import discover_playbooks

        query = str(request.query.get("q") or "").strip().lower()
        rows = [
            {"name": s.name, "category": s.category, "description": s.description[:300],
             "lifecycle": s.lifecycle}
            for s in discover_playbooks()
            if not query or query in s.name.lower() or query in s.description.lower()
        ]
        return web.json_response({"skills": rows, "count": len(rows)})

    async def handle_list_attachments(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        return web.json_response({"attachments": self.store.list_attachments(session_id)})

    async def handle_add_attachment(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        path = Path(str(body.get("safe_path") or body.get("path") or ""))
        try:
            from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
            root = InstanceLayout(root=resolve_instance_dir()).workspace_dir.resolve()
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                return web.json_response({"error": "attachment path escapes workspace"}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)
        # The Gateway receives a workspace file reference, not verified client
        # metadata. Freeze the bytes' actual size/hash here for every surface.
        def file_metadata():
            import hashlib

            if not resolved.is_file():
                raise ValueError("attachment must reference an existing regular file")
            digest = hashlib.sha256()
            size = 0
            with resolved.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            return {"safe_path": str(resolved), "size_bytes": size, "sha256": digest.hexdigest()}

        try:
            metadata = await asyncio.to_thread(file_metadata)
        except (OSError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        row = self.store.add_attachment(session_id, {**body, **metadata})
        self.event_bus.publish(session_id, "attachment.added", {"attachment": row})
        return web.json_response(row, status=201)

    async def handle_resolve_approval(self, request: web.Request) -> web.Response:
        """Resolve a pending approval. First writer wins; denial prevents effects."""
        approval_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        approved = bool(body.get("approved", True))
        decision = str(body.get("decision") or body.get("choice") or ("once" if approved else "deny"))
        if decision not in {"once", "deny", "always", "allow", "yes"}:
            return web.json_response({"error": "Unsupported approval decision"}, status=400)
        approved = decision != "deny"

        resolved = self.store.resolve_approval(approval_id, approved=approved, decision=decision)
        future = self.pending_approvals.pop(approval_id, None)
        if resolved is None and future is None:
            existing = self.store.get_approval(approval_id) or {}
            if existing.get("decision") == "cancelled":
                return web.json_response(
                    {"error": "Request was cancelled; approval no longer applies"}, status=409,
                )
            return web.json_response({"error": "Approval not found"}, status=404)
        if future is not None and not future.done():
            future.set_result(approved)

        handoff_row = None
        if resolved is not None and (resolved.get("metadata") or {}).get("task_id"):
            self.task_owner.resolve(resolved["metadata"]["task_id"], approved)
        if resolved is not None:
            hid = (resolved.get("metadata") or {}).get("handoff_id")
            if hid:
                handoff_row = self.store.get_handoff(str(hid))
            if handoff_row is None:
                for item in self.store.list_handoffs():
                    if item.get("approval_id") == approval_id:
                        handoff_row = item
                        break
            if handoff_row is not None:
                if approved:
                    handoff_row = self.store.save_handoff({**handoff_row, "status": "approved"})
                    rid = handoff_row.get("request_id") or handoff_row["id"]
                    if rid not in self._running_tasks:
                        self._running_tasks[rid] = asyncio.create_task(
                            self._execute_handoff(handoff_row["id"])
                        )
                else:
                    handoff_row = self.store.save_handoff({
                        **handoff_row,
                        "status": "denied",
                        "result": {"ok": False, "status": "denied", "summary": "Handoff denied by operator."},
                    })

        payload = {
            "approval_id": approval_id,
            "resolved": True,
            "approved": approved,
            "decision": decision,
            "handoff": handoff_row,
        }
        self.event_bus.publish("*", "approval.resolved", payload)
        return web.json_response(payload)

    async def _execute_handoff(self, handoff_id: str) -> None:
        record = self.store.get_handoff(handoff_id)
        if record is None:
            return
        if record["status"] not in {"admitted", "approved"}:
            return
        try:
            self.store.save_handoff({**record, "status": "running"})
            from jaeger_agent.cognition.runs import InMemoryRunStore
            from jaeger_agent.delegates.contracts import DelegateRequest
            from jaeger_agent.delegates.executor import DelegateExecutor, DelegateExecutionError
            from jaeger_agent.delegates.registry import DelegateRegistry
            from jaeger_ai.core.agent_registry.specialist_runtime import (
                NativeSpecialistRuntime, bounded_prompt, DEFAULT_TIMEOUT_S,
            )

            meta = dict(record.get("metadata") or {})
            registry = self._registry()
            target = registry.get_agent(record["to_agent_id"])
            display = getattr(target, "display_name", None) or record["to_agent_id"]
            specialty = meta.get("specialty") or (getattr(target, "metadata", None) or {}).get("specialty") or display
            allowed = meta.get("allowed_tools") or []
            prompt = bounded_prompt(
                display_name=str(display),
                specialty=str(specialty),
                task=record["task"],
                permitted_context=str(meta.get("permitted_context") or ""),
                allowed_tools=frozenset(str(x) for x in allowed) if allowed else None,
            )
            timeout = int(meta.get("timeout_seconds") or DEFAULT_TIMEOUT_S)
            runs = InMemoryRunStore()
            child = runs.create(
                f"handoff:{record['id']}",
                owner_pid=os.getpid(),
                payload={"handoff_id": record["id"], "to_agent_id": record["to_agent_id"]},
                parent_run_id=None,
                relation="delegate",
            )
            self.store.save_handoff({**record, "status": "running", "child_run_id": child.id})
            runtime = NativeSpecialistRuntime(self._specialist_chat)
            delegates = DelegateRegistry()
            delegates.register(runtime, replace=True)
            executor = DelegateExecutor(delegates, runs)
            request = DelegateRequest(
                task_id=child.id,
                prompt=prompt,
                parent_task_id=str(record.get("parent_run_id") or "") or None,
                timeout_seconds=max(1, timeout),
                idempotency_key=str(record.get("request_id") or record["id"]),
                allowed_tools=frozenset(str(x) for x in allowed),
                metadata={
                    "to_agent_id": record["to_agent_id"],
                    "handoff_id": record["id"],
                    "from_agent_id": record["from_agent_id"],
                },
            )
            result = await executor.execute(runtime.runtime_id, request)
            status = "execution_unknown" if result.metadata.get("execution_unknown") else result.status
            ok = status == "completed"
            saved = self.store.save_handoff({
                **record,
                "status": status,
                "child_run_id": child.id,
                "result": {
                    "ok": ok,
                    "status": result.status,
                    "summary": result.summary,
                    "evidence": list(result.evidence),
                    "metadata": dict(result.metadata),
                    "worker_session_id": result.worker_session_id,
                },
            })
            self.event_bus.publish("*", "agent.handoff.finished", {"handoff": saved})
        except Exception as exc:  # noqa: BLE001 — specialist failure must not kill the gateway
            logger.exception("specialist handoff failed: %s", exc)
            saved = self.store.save_handoff({
                **record,
                "status": "failed",
                "result": {"ok": False, "status": "failed", "summary": f"{type(exc).__name__}: {exc}"},
            })
            self.event_bus.publish("*", "agent.handoff.finished", {"handoff": saved})
        finally:
            self._running_tasks.pop(record.get("request_id") or handoff_id, None)

    async def _specialist_chat(self, session_id: str, text: str, *, request_id: str,
                               allowed_tools: list[str]) -> tuple[str, str]:
        import hashlib
        native_id = hashlib.sha256(("handoff:" + request_id).encode()).hexdigest()
        native = await self._native_lead_turn("specialist", text, mcp_session=session_id,
                                              request_id=native_id, allowed_tools=allowed_tools)
        if native is None:
            raise RuntimeError("Specialist native execution returned no confirmed result")
        return native

    async def handle_tasks(self, request: web.Request) -> web.Response:
        if request.method == 'GET':
            return web.json_response({'tasks': [t.to_dict() for t in self.task_owner.store.list_tasks()]})
        body = await request.json()
        parent = self.store.get_session(str(body.get('session_id') or ''))
        if parent is None:
            return web.json_response({'error': 'Existing session_id required'}, status=400)
        execution = dict(body.get('execution') or {})
        execution.setdefault('workspace', parent.get('workspace') or '')
        try:
            result = self.task_owner.submit(str(body.get('goal') or ''),
                context={'session_id': parent['session_id'], 'source': 'client', 'execution': execution,
                         'request_id': body.get('request_id')},
                artifacts=body.get('artifacts'), proposal=bool(body.get('proposal')))
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response(result, status=200 if result['replayed'] else 201)

    async def handle_task(self, request: web.Request) -> web.Response:
        task = self.task_owner.store.get_task(request.match_info['id'])
        return web.json_response(task.to_dict() if task else {'error': 'Task not found'}, status=200 if task else 404)

    async def handle_task_approve(self, request: web.Request) -> web.Response:
        task_id = request.match_info['id']
        task = self.task_owner.store.get_task(task_id)
        if task is None:
            return web.json_response({'error': 'Task not found'}, status=404)
        if task.provenance.get('authorized'):
            return web.json_response({'task_id': task_id, 'status': task.state.value})
        self.task_owner.resolve(task_id, True)
        for approval in self.store.list_pending_approvals():
            if (approval.get('metadata') or {}).get('task_id') == task_id:
                self.store.resolve_approval(approval['approval_id'], approved=True, decision='once')
        return web.json_response({'task_id': task_id, 'status': 'queued'})

    async def handle_task_cancel(self, request: web.Request) -> web.Response:
        cancelled = await self.task_owner.cancel(request.match_info['id'])
        return web.json_response({'cancelled': cancelled}, status=200 if cancelled else 404)

    async def handle_list_orchestration_workers(self, request: web.Request) -> web.Response:
        """List registered IDE orchestration workers and their availability."""
        if self.orchestration is None:
            return web.json_response({"workers": []})
        workers = await self.orchestration.list_workers()
        return web.json_response({"workers": workers})

    async def handle_create_orchestration_task(self, request: web.Request) -> web.Response:
        """Validate and reserve a worker request before acknowledging admission."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)

        from jaeger_ai.features.ide_orchestration.contracts import (
            ParentTask,
            TaskBudget,
        )
        from jaeger_ai.features.ide_orchestration.service import (
            DuplicateSubmissionConflict,
            WorkerUnavailableError,
        )

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("Request body must be an object")
            for field in ("task_id", "goal", "worker"):
                if not isinstance(body.get(field), str) or not body[field].strip():
                    raise ValueError(f"{field} must be a nonempty string")
            task_id = body["task_id"].strip()
            key = body.get("idempotency_key", task_id)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("idempotency_key must be a nonempty string")
            read_only = body.get("read_only", True)
            if not isinstance(read_only, bool):
                raise TypeError("read_only must be a boolean")
            if not read_only:
                return web.json_response(
                    {
                        "error": (
                            "Writable IDE orchestration requires a server-owned "
                            "authorization and verification plan"
                        )
                    },
                    status=403,
                )
            metadata = body.get("metadata", {})
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be an object")
            capabilities = body.get("required_capabilities", [])
            if not isinstance(capabilities, list) or any(
                not isinstance(value, str) or not value.strip() for value in capabilities
            ):
                raise ValueError("required_capabilities must be a list of nonempty strings")
            workspace = body.get("workspace")
            if workspace is not None and (not isinstance(workspace, str) or not workspace):
                raise ValueError("workspace must be an absolute path or null")
            budget_raw = body.get("budget", {})
            if not isinstance(budget_raw, dict):
                raise TypeError("budget must be an object")
            for field in ("max_seconds", "max_cost_usd"):
                value = budget_raw.get(field, 300.0 if field == "max_seconds" else 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"{field} must be numeric")
            turns = budget_raw.get("max_turns", 1)
            if isinstance(turns, bool) or not isinstance(turns, int):
                raise TypeError("max_turns must be an integer")
            parent_task = ParentTask(
                task_id=task_id,
                goal=body["goal"].strip(),
                assigned_worker=body["worker"].strip(),
                idempotency_key=key.strip(),
                workspace=Path(workspace) if workspace is not None else None,
                read_only=read_only,
                budget=TaskBudget(
                    max_seconds=float(budget_raw.get("max_seconds", 300.0)),
                    max_turns=turns,
                    max_cost_usd=float(budget_raw.get("max_cost_usd", 0.0)),
                ),
                metadata=metadata,
                required_capabilities=frozenset(capabilities),
            )
            operation, replayed = self.orchestration.admit_parent_task(parent_task)
        except DuplicateSubmissionConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except WorkerUnavailableError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

        if not replayed:
            # Reuse the Gateway's existing shutdown/cancellation tracking. There
            # is no untracked fire-and-forget task or guessed queued response.
            operation_key = ("orchestration", task_id)
            self._running_tasks[operation_key] = operation

            def completed(done: asyncio.Task) -> None:
                if self._running_tasks.get(operation_key) is done:
                    self._running_tasks.pop(operation_key, None)
                if not done.cancelled() and done.exception() is not None:
                    logger.error("Orchestration task %s failed: %s", task_id, done.exception())

            operation.add_done_callback(completed)
        return web.json_response(
            self.orchestration.get_task(task_id), status=200 if replayed else 201,
        )

    async def handle_get_orchestration_task(self, request: web.Request) -> web.Response:
        """Get the current process-local worker task, progress and result."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        task = self.orchestration.get_task(task_id)
        if task is None:
            return web.json_response({"error": f"Task {task_id} not found"}, status=404)
        return web.json_response(task)

    async def handle_cancel_orchestration_task(self, request: web.Request) -> web.Response:
        """Cancel an in-flight orchestration task."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        cancelled = await self.orchestration.cancel_task(task_id)
        return web.json_response({"cancelled": cancelled, "task_id": task_id})


def create_gateway_server(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
    store: GatewaySessionStore | None = None,
    orchestration: Any | None = None,
) -> tuple[JaegerGatewayApp, web.AppRunner]:
    gateway = JaegerGatewayApp(store=store, orchestration=orchestration)
    runner = web.AppRunner(gateway.app)
    return gateway, runner


async def run_gateway_forever(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
) -> None:
    gateway, runner = create_gateway_server(host, port)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[jaeger-gateway] Listening on http://{host}:{port}", flush=True)
    if getattr(gateway, "_pending_resume", False):
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            gateway._resume_safe_unknown_requests(EntityRuntime.get_singleton())
        except Exception:
            logger.debug("post-listen resume skipped", exc_info=True)
        gateway._pending_resume = False
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main(argv: list[str] | None = None) -> int:
    """``jaeger gateway daemon`` — run the Jaeger Gateway on :8810.

    This is the daemon AGENTS.md §3 describes: persistent SQLite session
    state and SSE multi-client broadcast, with the native app, WebUI and
    CLI attaching as decoupled clients.

    It had no route for a whole release. ``jaeger gateway`` goes to
    ``features.gateway``, which manages the *external* Agentgateway on
    :8811/:8812 — a different process entirely — while
    ``jaeger_ai/features/webui/api/jaeger_agents.py`` and
    ``scripts/run-jaeger-webui.sh`` both pointed clients at :8810 with
    nothing listening. Adding the route is what makes those clients real.

    Binds loopback by default; publish to a tailnet rather than widening
    the bind.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="jaeger gateway daemon",
        description="Run the Jaeger Gateway daemon (sessions + SSE).",
    )
    parser.add_argument("--host", default=DEFAULT_GATEWAY_HOST,
                        help=f"bind address (default {DEFAULT_GATEWAY_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_GATEWAY_PORT,
                        help=f"bind port (default {DEFAULT_GATEWAY_PORT})")
    args = parser.parse_args(argv)

    try:
        asyncio.run(run_gateway_forever(args.host, args.port))
    except KeyboardInterrupt:
        print("\n[jaeger-gateway] stopped", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover — process entry point
    raise SystemExit(main())
