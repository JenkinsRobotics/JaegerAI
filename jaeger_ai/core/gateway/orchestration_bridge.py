"""Gateway bridge to standalone Module 06 (jaeger-orchestration).

Provides a durable SQLite mailbox (``DurableMailbox``) scoped to the Gateway's
state root plus monotonic sandbox profile intersection
(``intersect_sandbox_profiles``) for orchestration tasks and subagent handoffs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)


class GatewayOrchestrationBridge:
    """Thin composition adapter over standalone ``jaeger_orchestration``."""

    def __init__(self, state_root: Path) -> None:
        self._state_root = Path(state_root)
        self._mailbox_dir = self._state_root / "orchestration"
        self._mailbox: Any = None

    def _ensure_mailbox(self) -> Any:
        if self._mailbox is None:
            from jaeger_orchestration import DurableMailbox

            self._mailbox = DurableMailbox(self._mailbox_dir)
        return self._mailbox

    def record_task_dispatch(
        self,
        *,
        sender: str,
        recipient: str,
        task_id: str,
        payload: Mapping[str, Any],
    ) -> int | None:
        """Persist an orchestration dispatch envelope in the durable mailbox."""
        try:
            mb = self._ensure_mailbox()
            return mb.send(
                sender=sender,
                recipient=recipient,
                payload={"task_id": task_id, **dict(payload)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("jaeger_orchestration mailbox send failed: %s", exc)
            return None

    def pending_for(self, recipient: str) -> list[dict[str, Any]]:
        """Drain undelivered mailbox envelopes for ``recipient``."""
        try:
            mb = self._ensure_mailbox()
            return list(mb.drain(recipient))
        except Exception as exc:  # noqa: BLE001
            logger.warning("jaeger_orchestration mailbox drain failed: %s", exc)
            return []

    @staticmethod
    def intersect_worker_sandbox(
        workspace: Path | str,
        *,
        parent_read_only: bool = False,
        parent_network: bool = False,
        worker_read_only: bool = False,
        worker_network: bool = False,
    ) -> dict[str, Any]:
        """Compute monotonically non-escalating worker sandbox profile."""
        from jaeger_contracts import SandboxProfile
        from jaeger_orchestration import intersect_sandbox_profiles

        ws = Path(str(workspace)).resolve()
        parent = SandboxProfile(
            workspace=ws,
            writable_roots=() if parent_read_only else (ws,),
            read_only_subpaths=(ws,) if parent_read_only else (),
            allow_network=bool(parent_network),
            read_only_default=bool(parent_read_only),
        )
        child = SandboxProfile(
            workspace=ws,
            writable_roots=() if worker_read_only else (ws,),
            read_only_subpaths=(ws,) if worker_read_only else (),
            allow_network=bool(worker_network),
            read_only_default=bool(worker_read_only),
        )
        eff = intersect_sandbox_profiles(parent, child)
        ro_set = {p.expanduser().resolve(strict=False) for p in eff.read_only_subpaths}
        writable = [str(p) for p in eff.writable_roots if p.expanduser().resolve(strict=False) not in ro_set]
        is_read_only = bool(eff.read_only_default and (ws in ro_set or not writable))
        return {
            "workspace": str(eff.workspace),
            "read_only": is_read_only,
            "network_access": bool(eff.allow_network),
            "writable_roots": writable,
        }
