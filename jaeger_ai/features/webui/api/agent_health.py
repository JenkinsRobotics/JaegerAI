"""Hermes agent/gateway heartbeat payload helpers (#716, #1879).

The WebUI process is not always paired with a long-running Hermes gateway. Some
setups use WebUI only, while self-hosted messaging deployments run a separate
Hermes gateway daemon that records runtime metadata in the Hermes Agent home.
This module turns those existing safe runtime signals into a small UI-facing
heartbeat without shelling out or adding psutil as a hard dependency.

Cross-container note (#1879): ``gateway.status.get_running_pid()`` uses
``fcntl.flock`` and ``os.kill(pid, 0)``, both of which require the caller to
share a PID namespace with the gateway process. In multi-container deployments
where the WebUI runs separately from ``hermes-agent`` and only a Hermes data
volume is shared, those checks always return ``None`` and the dashboard
incorrectly shows "Gateway not running". To stay accurate without forcing a
``pid: "service:hermes-agent"`` compose workaround, we accept a recent
``updated_at`` timestamp on ``gateway_state.json`` (combined with
``gateway_state == "running"``) as an equivalent live-process signal.  Older
gateway builds do not refresh that file periodically, so a stale
``gateway_state == "running"`` record is treated as inconclusive rather than a
confirmed outage.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

_GATEWAY_PID_FILE = "gateway.pid"












def _gateway_status_module():
    """Load gateway.status lazily so tests and WebUI-only installs stay isolated."""
    return importlib.import_module("gateway.status")










def _callable_code_declares_parameter(get_running_pid: Any, name: str) -> bool:
    """Return True when a Python callable's own code declares *name*."""
    target = getattr(get_running_pid, "__func__", get_running_pid)
    code = getattr(target, "__code__", None)
    if code is None:
        return False
    declared_count = int(getattr(code, "co_argcount", 0)) + int(
        getattr(code, "co_kwonlyargcount", 0)
    )
    return name in code.co_varnames[:declared_count]


def _declared_pid_path_parameter(
    get_running_pid: Any,
) -> tuple[inspect.Parameter, int, list[inspect.Parameter]] | None:
    try:
        signature = inspect.signature(get_running_pid, follow_wrapped=False)
    except (TypeError, ValueError):
        return None
    params = list(signature.parameters.values())
    for idx, param in enumerate(params):
        if param.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        name = str(param.name or "").lower()
        if (
            "path" in name
            and "pid" in name
            and _callable_code_declares_parameter(get_running_pid, param.name)
        ):
            positional_index = sum(
                1
                for earlier in params[:idx]
                if earlier.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            )
            return param, positional_index, params
    return None


def _positional_only_pid_args(
    params: list[inspect.Parameter],
    positional_index: int,
    pid_path: Path,
) -> list[Any] | None:
    positional_params = [
        param
        for param in params
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if positional_index >= len(positional_params):
        return None
    args: list[Any] = []
    for param in positional_params[:positional_index]:
        if param.default is inspect.Parameter.empty:
            return None
        args.append(param.default)
    args.append(pid_path)
    return args


def _accepts_cleanup_stale_keyword(params: list[inspect.Parameter]) -> bool:
    return any(
        param.name == "cleanup_stale"
        and param.kind
        in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        for param in params
    )


def _gateway_running_pid_strict_path(gateway_status: Any, pid_path: Path) -> int | None:
    """Read a PID from an explicit path only; never fall back to ambient state."""
    get_running_pid = gateway_status.get_running_pid
    pid_path_match = _declared_pid_path_parameter(get_running_pid)
    if pid_path_match is None:
        return None
    pid_path_param, positional_index, params = pid_path_match

    if pid_path_param.kind is inspect.Parameter.KEYWORD_ONLY:
        kwargs = {pid_path_param.name: pid_path}
        try:
            return get_running_pid(**kwargs, cleanup_stale=False)
        except TypeError:
            try:
                return get_running_pid(**kwargs)
            except TypeError:
                return None

    if pid_path_param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD:
        kwargs = {pid_path_param.name: pid_path}
        try:
            return get_running_pid(**kwargs, cleanup_stale=False)
        except TypeError:
            try:
                return get_running_pid(**kwargs)
            except TypeError:
                return None

    if pid_path_param.kind is inspect.Parameter.POSITIONAL_ONLY:
        args = _positional_only_pid_args(params, positional_index, pid_path)
        if args is None:
            return None
        if _accepts_cleanup_stale_keyword(params):
            try:
                return get_running_pid(*args, cleanup_stale=False)
            except TypeError:
                pass
        try:
            return get_running_pid(*args)
        except TypeError:
            return None
    return None


def get_active_profile_gateway_running_pid(profile: str | None = None) -> int | None:
    """Return the confirmed active-profile PID without state fallbacks.

    Update recovery needs process identity, not just a recent ``running`` state:
    an old gateway can remain alive when the restart CLI fails before executing.
    Use the same active-profile home targeted by the restart helper rather than
    the default-root health path. Keep this fail-closed when status is unavailable.
    """
    try:
        from api.profiles import get_active_hermes_home, get_hermes_home_for_profile

        gateway_status = _gateway_status_module()
        if profile is None:
            gateway_home = get_active_hermes_home()
        else:
            gateway_home = get_hermes_home_for_profile(profile)
        gateway_pid_path = Path(gateway_home) / _GATEWAY_PID_FILE
        return _gateway_running_pid_strict_path(gateway_status, gateway_pid_path)
    except Exception:
        return None




# Remote-gateway probe (#3281)
# ------------------------------------------------------------------
# In multi-container Docker deployments the WebUI container does not ship the
# ``gateway`` Python package. The lazy ``importlib.import_module("gateway.status")``
# therefore raises ``ModuleNotFoundError`` and the payload falls through to
# ``gateway_not_configured`` even though ``HERMES_API_URL`` points at a perfectly
# reachable remote gateway. The Tasks/Cron banner then shows a spurious amber
# "Gateway not configured" warning.
#
# When a gateway base URL is set in any supported env var, we treat that as an
# explicit declaration that the gateway lives elsewhere, and probe it over HTTP
# before touching any local filesystem / module signal. The probe result is
# cached briefly so a dashboard rerender that fans out to multiple panels does
# not hammer the gateway.


















