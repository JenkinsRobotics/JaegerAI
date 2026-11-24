"""Extracted Gateway approval & local-access confirmation providers (Wave 2).

Handles interactive tool confirmations (``WRITE_LOCAL`` / ``REQUIRE_APPROVAL``)
and owner-approved local read/write root expansions on the Gateway approval bus.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

APPROVAL_OPTIONS = ["once", "session", "deny"]

if TYPE_CHECKING:
    from .server import JaegerGatewayApp

logger = logging.getLogger(__name__)


def _get_approval_wait_s() -> float:
    from . import server as _server
    return float(_server.APPROVAL_WAIT_S)


def _approval_target(request: Any) -> str:
    from . import server as _server
    return _server._approval_target(request)


class _GatewayToolConfirmationProvider:
    """Park WRITE_LOCAL (and similar) confirms on the Gateway approval bus.

    Phone/WebUI resolve them with POST /v1/approvals/{id}. Standing
    commissioning filesystem.write grants still auto-allow.
    """

    def __init__(self, app: "JaegerGatewayApp", session_id: str, request_id: str) -> None:
        self.app = app
        self.session_id = session_id
        self.request_id = request_id

    #: Asks a human for this call when ``force_prompt`` is set (no standing
    #: grant, autonomy shortcut or remembered answer). Required by
    #: PolicyKernel REQUIRE_APPROVAL (tool_executor._owner_approves).
    fresh_approval = True

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
        # PolicyKernel REQUIRE_APPROVAL: only an explicit owner decision on an
        # approval card answers it; grants and autonomy shortcuts do not.
        if getattr(request, "force_prompt", False) is True:
            return self._decided(self._prompt(request))
        # Plan mode: write/exec tools are blocked, not offered as a card.
        if self._plan_mode() and self._write_or_exec(request):
            return False
        from jaeger_ai.core.runtime.autonomy import auto_approves, effective_autonomy
        try:
            mode = effective_autonomy(self.app._config_path())
        except Exception:
            mode = "ask"
        # Ask means ask: only explicit owner grants (session/skill/project)
        # skip the card, not the standing filesystem-write policy (P17).
        if self._in_saved_scope(request, standing_policy=(mode != "ask")):
            return True
        if auto_approves(mode):
            return True
        if mode == "ask" and getattr(request, "tier", None) != PermissionTier.READ_ONLY:
            return self._decided(self._prompt(request))
        if mode == "scoped":
            verdict, reason = self._review_out_of_scope(request)
            if verdict == "approve":
                return True
            return self._decided(self._prompt(request, reviewer_verdict=verdict, reviewer_reason=reason))
        if self._write_or_exec(request):
            return self._decided(self._prompt(request))
        return self._decided(self._prompt(request))

    def _plan_mode(self) -> bool:
        from jaeger_ai.contract.modes import normalize_interaction_tier
        try:
            row = self.app.store.get_request(self.request_id) or {}
            execution = row.get("execution") if isinstance(row.get("execution"), dict) else {}
            tier = execution.get("interaction_tier") or (row.get("metadata") or {}).get("interaction_tier")
            if not tier:
                tier = self.app._current_tier()
            return normalize_interaction_tier(tier) == "plan"
        except Exception:  # noqa: BLE001
            return False

    def _in_saved_scope(self, request: Any, standing_policy: bool = True) -> bool:
        """Standing session, skill, project, or read-only grants — 'Approve for me' auto-run."""
        from jaeger_os.core.safety.permissions import PermissionTier
        skill_name = str(getattr(request, "skill", "") or "")
        if skill_name and skill_name in self._session_grants():
            return True
        if self._approved_task_code_step(request):
            return True
        try:
            if skill_name and self._grants().is_granted(skill_name):
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.app._project_grant_allows(self.session_id, request):
                return True
        except Exception:  # noqa: BLE001
            logger.debug("project grant check failed", exc_info=True)
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            policy = load_authority_policy(rt.layout.root) if getattr(rt, "layout", None) else {}
            tier = getattr(request, "tier", None)
            if tier == PermissionTier.READ_ONLY:
                return True
            if standing_policy and tier == PermissionTier.WRITE_LOCAL and bool((policy.get("filesystem") or {}).get("write")):
                return True
        except Exception:
            pass
        return False

    def _review_out_of_scope(self, request: Any) -> tuple[str, str]:
        """Ask the reviewer model; always emit approval.reviewed. Failure is unsure."""
        from jaeger_ai.core.authority.reviewer import review_action

        skill = str(getattr(request, "skill", "") or "")
        op = str(getattr(request, "operation", "") or "")
        tool = f"{skill}.{op}" if skill else op
        args = getattr(request, "arguments", None) or getattr(request, "params", None) or getattr(request, "input", None)
        user_request = ""
        model = provider = None
        try:
            row = self.app.store.get_request(self.request_id) or {}
            user_request = str(row.get("input_text") or "")
            model = row.get("model") or None
            provider = row.get("provider") or None
            if not model:
                session = self.app.store.get_session(self.session_id) or {}
                meta = session.get("metadata") or {}
                model = session.get("model") or meta.get("model")
                provider = provider or session.get("provider") or meta.get("provider")
        except Exception:  # noqa: BLE001
            pass
        verdict, reason = review_action(
            self.app,
            user_request=user_request,
            tool=tool,
            arguments=args,
            model=str(model) if model else None,
            provider=str(provider) if provider else None,
        )
        payload = {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "tool": tool,
            "verdict": verdict,
            "reason": reason,
        }
        try:
            self.app.event_bus.publish(self.session_id, "approval.reviewed", payload)
            self.app.event_bus.publish("*", "approval.reviewed", payload)
        except Exception:  # noqa: BLE001 — a missing event must not change the decision
            logger.debug("approval.reviewed publish failed", exc_info=True)
        return verdict, reason

    _DELETE_TOOLS = frozenset({"delete_file", "remove_file", "delete_path", "delete", "rm"})
    _EXEC_TOOLS = frozenset({"execute_code", "run_code", "python_exec"})

    _CODE_STEP_TOOLS = frozenset({"execute_code", "execute_with_tools"})

    def _approved_task_code_step(self, request: Any) -> bool:
        """A code step (execute_code / execute_with_tools) inside an owner-approved durable task run."""
        if str(getattr(request, "operation", "") or "") not in self._CODE_STEP_TOOLS:
            return False
        if not str(self.session_id or "").startswith("task:"):
            return False
        try:
            owner = getattr(self.app, "task_owner", None)
            task = owner.store.get_task(self.session_id[len("task:"):]) if owner is not None else None
            if task is None or task.is_terminal:
                return False
            return task.provenance.get("authorized") is True
        except Exception:  # noqa: BLE001 - unknown task state means "ask"
            return False

    def _write_or_exec(self, request: Any) -> bool:
        names = {str(getattr(request, "operation", "") or "")}
        app_cls = type(self.app)
        return bool(names & (app_cls._PROJECT_WRITE_TOOLS | app_cls._PROJECT_SHELL_TOOLS
                             | self._DELETE_TOOLS | self._EXEC_TOOLS))

    @staticmethod
    def _autonomy_auto() -> bool:
        """Owner explicitly saved an automatic approval mode (never the default)."""
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.runtime.autonomy import auto_approves, effective_autonomy
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            return auto_approves(effective_autonomy(getattr(layout, "config_path", None)))
        except Exception:  # noqa: BLE001
            return False

    def _session_grants(self) -> set[str]:
        """Skills allowed in this session during this Gateway process."""
        try:
            meta = (self.app.store.get_session(self.session_id) or {}).get("metadata") or {}
            if meta.get("session_grants_boot_id") != self.app._session_grants_boot_id:
                return set()
            return {str(s) for s in meta.get("session_grants") or []}
        except Exception:  # noqa: BLE001 — unreadable means "ask", never "allow"
            return set()

    def _grant_for_session(self, skill: str) -> None:
        grants = sorted(self._session_grants() | {skill})
        self.app.store.update_metadata(self.session_id, {
            "session_grants": grants,
            "session_grants_boot_id": self.app._session_grants_boot_id,
        })

    def _decided(self, approved: bool) -> bool:
        if not approved and self.request_id not in self.app._owner_unanswered:
            self.app._owner_declined.add(self.request_id)
        return approved

    def _prompt(self, request: Any, reviewer_verdict: str | None = None,
                reviewer_reason: str | None = None) -> bool:
        """Park an approval card and return the owner's boolean decision."""
        return self._prompt_decision(
            request, reviewer_verdict=reviewer_verdict,
            reviewer_reason=reviewer_reason,
        )[0]

    def _prompt_decision(self, request: Any, reviewer_verdict: str | None = None,
                         reviewer_reason: str | None = None) -> tuple[bool, str]:
        """Park one approval and retain its scope for resource grants."""
        loop = getattr(self.app, "_loop", None)
        if loop is None or not loop.is_running():
            return False, "unavailable"
        skill = str(getattr(request, "skill", "") or "")
        op = str(getattr(request, "operation", "") or "")
        summary = str(getattr(request, "summary", "") or "")
        target = _approval_target(request) or summary
        tier_name = getattr(getattr(request, "tier", None), "name", str(getattr(request, "tier", "")))
        aid = f"approval_{uuid.uuid4().hex[:12]}"
        box: dict[str, Any] = {"done": threading.Event(), "approved": False}
        origin = self.app._approval_origin(self.session_id)
        # The tool call this card blocks, so the process view nests it.
        call_id = getattr(self.app, "_active_tool_call", {}).get(self.request_id)

        def _arm() -> None:
            fut = loop.create_future()
            self.app.pending_approvals[aid] = fut
            self.app.store.create_approval(
                kind="tool_confirm",
                prompt=f"Allow {skill}.{op}? {target}".strip(),
                options=APPROVAL_OPTIONS,
                session_id=self.session_id,
                request_id=self.request_id,
                approval_id=aid,
                metadata={
                    "tool": f"{skill}.{op}" if skill else op,
                    "target": target,
                    "summary": summary,
                    "reason": tier_name,
                    **({"reviewer_verdict": reviewer_verdict} if reviewer_verdict else {}),
                    **({"reviewer_reason": reviewer_reason} if reviewer_reason else {}),
                    **({"call_id": call_id} if call_id else {}),
                    **({"origin": origin} if origin else {}),
                },
            )
            self.app._publish_approval_request(self.session_id, origin, {
                "approval_id": aid,
                # Same card shape as handoff approvals (see handle_stream_events).
                "kind": "tool",
                "prompt": f"Allow {skill}.{op}? {target}".strip(),
                "tool": f"{skill}.{op}" if skill else op,
                "target": target,
                "reason": tier_name,
                "options": APPROVAL_OPTIONS,
                "session_id": self.session_id,
                "request_id": self.request_id,
                **({"reviewer_verdict": reviewer_verdict} if reviewer_verdict else {}),
                **({"reviewer_reason": reviewer_reason} if reviewer_reason else {}),
                **({"call_id": call_id} if call_id else {}),
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
        deadline = time.monotonic() + _get_approval_wait_s()
        self.app._run_interrupted(self.session_id, self.request_id, aid, {
            "tool": f"{skill}.{op}" if skill else op, "target": target,
            "call_id": call_id, "expires_in_s": _get_approval_wait_s()})
        approved = False
        try:
            approved = self._await_decision(box, aid, scope, deadline, skill, request)
        finally:
            row = self.app.store.get_approval(aid) or {}
            self.app._run_resumed(self.session_id, self.request_id, aid, row.get("decision") or "expired")
        row = self.app.store.get_approval(aid) or {}
        return approved, str(row.get("decision") or "deny")

    def _await_decision(self, box: dict[str, Any], aid: str, scope: Any, deadline: float,
                        skill: str, request: Any) -> bool:
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
            decision = (self.app.store.get_approval(aid) or {}).get("decision")
            # "always" also covers this session: under the write/exec policy the
            # persistent grant alone no longer skips the card in other sessions.
            if (approved and skill and decision in {"session", "always"}
                    and not getattr(request, "force_prompt", False)):
                try:
                    self._grant_for_session(skill)
                except Exception:  # noqa: BLE001 — the call itself stays approved
                    logger.warning("could not record session grant for %s", skill, exc_info=True)
            if (approved and not getattr(request, "force_prompt", False)
                    and decision == "always"):
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
            self.app._owner_unanswered.add(self.request_id)     # nobody answered: needs the owner
            return False
        row = self.app.store.get_approval(aid) or {}
        return row.get("decision") not in {None, "deny", "expired"}


class _GatewayLocalReadAccessProvider:
    """Codex-style expansion of a Gateway turn's local read boundary.

    The model can request a path but cannot grant it. The existing Gateway
    approval bus supplies the human decision; ``session`` decisions persist as
    exact realpath roots in session metadata. Writes and code execution never
    inherit these read grants.
    """

    _META_KEY = "local_read_roots"
    _ACCESS = "read_only"
    _OPERATION = "read_file"

    def __init__(self, app: "JaegerGatewayApp", session_id: str, request_id: str) -> None:
        self.app = app
        self.session_id = session_id
        self.request_id = request_id
        self.confirmation = _GatewayToolConfirmationProvider(app, session_id, request_id)
        self._turn_roots: set[str] = set()
        self._denied: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _real(value: Any) -> str:
        return os.path.realpath(os.path.expanduser(str(value)))

    def _saved_roots(self) -> set[str]:
        try:
            meta = (self.app.store.get_session(self.session_id) or {}).get("metadata") or {}
            return {self._real(root) for root in meta.get(self._META_KEY) or [] if root}
        except Exception:  # noqa: BLE001 — unreadable authority means ask
            return set()

    @staticmethod
    def _contains(root: str, target: str) -> bool:
        try:
            return os.path.commonpath((root, target)) == root
        except (ValueError, OSError):
            return False

    def _existing_grant(self, target: str) -> str | None:
        for root in self._turn_roots | self._saved_roots():
            if self._contains(root, target):
                return root
        return None

    def _grant_root(self, target: str) -> str:
        """Group files in one repository into one intelligible approval.

        Codex-style project work should not require a card per file. A trusted
        host may inspect ancestors to find the nearest checkout boundary; the
        model still cannot select or widen the returned scope. Non-repository
        files remain exact-file grants.
        """
        candidate = Path(target)
        current = candidate if candidate.is_dir() else candidate.parent
        home = Path.home().resolve()
        for parent in (current, *current.parents):
            resolved = parent.resolve()
            if resolved in {Path(os.path.sep), home}:
                break
            if (resolved / ".git").exists():
                return str(resolved)
        return target

    def _persist(self, root: str) -> None:
        roots = sorted(self._saved_roots() | {root})
        self.app.store.update_metadata(self.session_id, {self._META_KEY: roots})

    def __call__(self, target: Path) -> str | None:
        from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier

        resolved = self._real(target)
        existing = self._existing_grant(resolved)
        if existing:
            return existing
        # Never offer dangerously broad roots. Sensitive-path policy is
        # evaluated by workspace._resolve_read before this callback.
        if resolved in {os.path.sep, self._real(Path.home())}:
            return None
        grant_root = self._grant_root(resolved)
        with self._lock:
            existing = self._existing_grant(resolved)
            if existing:
                return existing
            if grant_root in self._denied:
                return None
            request = PermissionRequest(
                tier=self._permission_tier(PermissionTier),
                skill="local_files",
                operation=self._OPERATION,
                summary=(f"{self._ACCESS.replace('_', ' ').title()} {resolved} outside "
                         f"this chat's workspace with scope {grant_root}"),
                arguments={
                    "path": grant_root, "requested_path": resolved,
                    "access": self._ACCESS,
                },
                force_prompt=True,
            )
            approved, decision = self.confirmation._prompt_decision(request)
            if not approved:
                self._denied.add(grant_root)
                return None
            self._turn_roots.add(grant_root)
            if decision == "session":
                self._persist(grant_root)
            return grant_root

    @staticmethod
    def _permission_tier(permission_tier: Any) -> Any:
        return permission_tier.READ_ONLY


class _GatewayLocalWriteAccessProvider(_GatewayLocalReadAccessProvider):
    """Owner-approved expansion for an exact local write or repository root."""

    _META_KEY = "local_write_roots"
    _ACCESS = "write"
    _OPERATION = "write_file"

    @staticmethod
    def _permission_tier(permission_tier: Any) -> Any:
        return permission_tier.WRITE_LOCAL
