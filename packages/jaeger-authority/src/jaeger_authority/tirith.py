"""Tirith pre-exec content scanning (standalone jaeger-authority module, MIT ported from hermes-agent)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_MAX_FINDINGS = 20
_MAX_SUMMARY_LEN = 2000
_DEFAULT_TIMEOUT = 5
_CRASH_LIMIT = 3

ALLOW = "allow"
WARN = "warn"
BLOCK = "block"

_crash_count = 0
_circuit_open = False
_warned: set[str] = set()
_config_provider: Callable[[], Any] | None = None


def configure_tirith(config_provider: Callable[[], Any] | None) -> None:
    """Register optional host config provider returning an object with enabled/fail_open/path/timeout_s."""
    global _config_provider
    _config_provider = config_provider


@dataclass(frozen=True)
class ScanResult:
    action: str = ALLOW
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == BLOCK


def reset_state() -> None:
    global _crash_count, _circuit_open
    _crash_count = 0
    _circuit_open = False
    _warned.clear()


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(msg, *args)


def _record_crash() -> None:
    global _crash_count, _circuit_open
    _crash_count += 1
    if _crash_count >= _CRASH_LIMIT and not _circuit_open:
        _circuit_open = True
        logger.warning(
            "tirith: %d consecutive failures — disabling scans for the rest of this process (circuit breaker)",
            _crash_count,
        )


def _cfg() -> Any:
    if _config_provider is not None:
        try:
            return _config_provider()
        except Exception:  # noqa: BLE001
            return None
    return None


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def enabled() -> bool:
    block = _cfg()
    return _env_bool("JAEGER_TIRITH", bool(getattr(block, "enabled", False)))


def fail_open() -> bool:
    block = _cfg()
    return _env_bool("JAEGER_TIRITH_FAIL_OPEN", bool(getattr(block, "fail_open", True)))


def binary_path() -> str | None:
    configured = str(
        getattr(_cfg(), "path", "") or os.environ.get("JAEGER_TIRITH_PATH", "")
    ).strip()
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which("tirith")


def _timeout() -> int:
    try:
        return max(1, int(getattr(_cfg(), "timeout_s", _DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT


def _unavailable(reason: str) -> ScanResult:
    if fail_open():
        return ScanResult(ALLOW, f"tirith unavailable: {reason}")
    return ScanResult(BLOCK, f"tirith unavailable, failing closed: {reason}")


def scan_command(command: str) -> ScanResult:
    """Scan *command* for content-level threats."""
    global _crash_count

    if not enabled():
        return ScanResult()
    if _circuit_open:
        return ScanResult(ALLOW, "tirith disabled (circuit breaker)")
    if not (command or "").strip():
        return ScanResult()

    exe = binary_path()
    if not exe:
        _warn_once(
            "tirith_missing",
            "tirith is enabled but the binary was not found on PATH (set tirith.path, or install it) — scans are inactive",
        )
        _record_crash()
        return _unavailable("binary not found")

    timeout = _timeout()
    try:
        proc = subprocess.run(
            [exe, "scan", "--json", "-"],
            input=command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _warn_once(f"tirith_timeout:{timeout}", "tirith timed out after %ds", timeout)
        _record_crash()
        return _unavailable(f"timed out after {timeout}s")
    except Exception as exc:  # noqa: BLE001
        _warn_once(f"tirith_spawn:{type(exc).__name__}", "tirith spawn failed: %s", exc)
        _record_crash()
        return _unavailable(str(exc))

    code = proc.returncode
    if code == 0:
        action = ALLOW
        _crash_count = 0
    elif code == 1:
        action = BLOCK
        _crash_count = 0
    elif code == 2:
        action = WARN
        _crash_count = 0
    else:
        logger.warning("tirith returned unexpected exit code %d", code)
        _record_crash()
        return _unavailable(f"unexpected exit code {code}")

    findings: list[dict[str, Any]] = []
    summary = ""
    try:
        data = json.loads(proc.stdout) if (proc.stdout or "").strip() else {}
        if isinstance(data, dict):
            raw = data.get("findings") or []
            if isinstance(raw, list):
                findings = [f for f in raw[:_MAX_FINDINGS] if isinstance(f, dict)]
            summary = str(data.get("summary") or "")[:_MAX_SUMMARY_LEN]
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.debug("tirith: JSON parse failed; using exit code only")
        if action == BLOCK:
            summary = "security issue detected (details unavailable)"
        elif action == WARN:
            summary = "security warning detected (details unavailable)"

    return ScanResult(action, summary, findings)


__all__ = [
    "ALLOW",
    "BLOCK",
    "ScanResult",
    "WARN",
    "binary_path",
    "configure_tirith",
    "enabled",
    "fail_open",
    "reset_state",
    "scan_command",
]
