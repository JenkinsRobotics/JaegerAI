"""``CliBackendAdapter`` — an installed agent CLI as a Jaeger brain.

The Jaeger loop stays Jaeger: tools, memory, and permissions never
leave this process. The CLI is a completion backend — flatten the
transcript to a prompt, spawn the binary (no ``shell=True``), parse
stdout back to one assistant ``Message``.

Delegates (``delegate_task``) remain the "go do this whole job in that
agent" path. This adapter is the opposite: the CLI *is* the model.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import tempfile
import time
from typing import Any

from jaeger_agent.loop.interrupt import AgentInterrupted, interruptible_call
from jaeger_agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef

from .base import ProviderAdapter
from .cli_stream import collect_stream, VisibleTextStream

logger = logging.getLogger(__name__)

_SAFE_ENV = frozenset({
    "COLORTERM",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "NO_COLOR",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
})


def flatten_messages(
    messages: list[Message],
    tools: list[ToolDef],
    system: str,
) -> str:
    """System + transcript → one prompt the CLI can consume."""
    parts: list[str] = []
    if system and system.strip():
        parts.append(f"System:\n{system.strip()}")
    if tools:
        from .hermes_xml import HERMES_TOOL_INSTRUCTIONS
        parts.append(
            "Jaeger owns tools, memory, and permissions. Do not execute tools yourself. "
            "Request the tools below using the Jaeger text protocol; Jaeger will validate "
            "arguments, obtain approvals, execute them, and return their results.\n"
            + HERMES_TOOL_INSTRUCTIONS
            + "\n<tools>\n"
            + json.dumps([tool.to_openai_schema() for tool in tools], ensure_ascii=False)
            + "\n</tools>"
        )
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = msg.get("content")
        text = content if isinstance(content, str) else (
            json.dumps(content, default=str, ensure_ascii=False) if content else ""
        )
        if role == "system":
            if text.strip():
                parts.append(f"System:\n{text.strip()}")
            continue
        if role == "tool":
            parts.append(f"Tool result:\n{text}")
            continue
        if role == "assistant" and msg.get("tool_calls"):
            parts.append(f"Assistant (tool calls):\n{json.dumps(msg.get('tool_calls'), default=str)}")
            if text.strip():
                parts.append(f"Assistant:\n{text}")
            continue
        label = "User" if role == "user" else "Assistant"
        parts.append(f"{label}:\n{text}")
    return "\n\n".join(parts).strip() or "(no input)"


def parse_cli_text(stdout: str, stderr: str = "") -> str:
    """Extract assistant text from CLI stdout. JSON if present, else raw."""
    clean = (stdout or "").strip()
    if not clean:
        err = (stderr or "").strip()
        return err[-100_000:] if err else ""
    extracted = _extract_json_text(clean)
    if extracted:
        return extracted.strip()
    return clean[-100_000:]


def _extract_json_text(text: str) -> str:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
        # Codex --json is NDJSON; prefer the last object that carries text.
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line or line[0] not in "{[":
                continue
            try:
                value = json.loads(line)
                found = _find_text(value)
                if found:
                    return found
            except json.JSONDecodeError:
                continue
        return ""
    return _find_text(value)


def _find_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("result", "final_response", "response", "message", "content", "text"):
            if key in value:
                found = _find_text(value[key])
                if found:
                    return found
        for child in reversed(tuple(value.values())):
            found = _find_text(child)
            if found:
                return found
    if isinstance(value, list):
        for child in reversed(value):
            found = _find_text(child)
            if found:
                return found
    return ""


def _build_argv(spec: Any, executable: str, prompt: str) -> tuple[list[str], bytes | None]:
    """Return ``(argv, stdin_bytes)``. Never goes through a shell."""
    if getattr(spec, "prompt_mode", "stdin") == "stdin":
        return [executable, *list(spec.args)], prompt.encode("utf-8")
    argv = [executable]
    for arg in spec.args:
        argv.append(prompt if arg == "{prompt}" else arg)
    return argv, None


class CliBackendAdapter(ProviderAdapter):
    """Spawn an installed agent CLI for one completion."""

    name = "cli"

    def __init__(
        self,
        backend_id: str,
        *,
        executable: str | None = None,
        timeout_s: float = 600.0,
        spec: Any = None,
    ) -> None:
        self.backend_id = (backend_id or "").strip()
        self.timeout_s = float(timeout_s or 600.0)
        self._spec = spec
        self._executable = executable
        self._proc: subprocess.Popen[bytes] | None = None

    def describe(self) -> str:
        exe = self._executable or self.backend_id
        return f"CliBackendAdapter({self.backend_id} @ {exe})"

    def _load_spec(self) -> Any:
        if self._spec is not None:
            return self._spec
        from jaeger_agent.core.host import service
        discovery = service("cli_backends")
        get_spec, probe_backend = discovery.get_spec, discovery.probe_backend

        spec = get_spec(self.backend_id)
        if not self._executable:
            found = probe_backend(spec)
            if not found:
                names = ", ".join(spec.executables)
                raise RuntimeError(
                    f"CLI backend {self.backend_id!r} is not installed on PATH "
                    f"(looked for {names})"
                )
            self._executable = found
        self._spec = spec
        return spec

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, str]:
        return {"prompt": flatten_messages(messages, tools, system)}

    def call(
        self,
        formatted: Any,
        interrupt_event: threading.Event,
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = formatted if isinstance(formatted, str) else str(
            (formatted or {}).get("prompt") or ""
        )
        spec = self._load_spec()
        executable = self._executable or ""
        argv, stdin_bytes = _build_argv(spec, executable, prompt)

        on_delta = kwargs.get("on_delta") if self.backend_id == "grok" else None
        if callable(on_delta):
            visible_stream = VisibleTextStream(on_delta)
            on_delta = visible_stream.feed
            # Grok emits actual token deltas in this mode; the result record still
            # owns the final persisted response. Never re-stream that full record.
            if "--output-format" in argv:
                argv[argv.index("--output-format") + 1] = "streaming-messages-json"
            else:
                argv.extend(["--output-format", "streaming-messages-json"])
            argv.append("--include-partial-messages")
        else:
            on_delta = None
            visible_stream = None

        def _run() -> dict[str, Any]:
            if self.backend_id == "grok" and "--single" in argv:
                # Full schemas and history exceed macOS argv limits. Keep the
                # prompt private and out of process listings; delete on exit.
                with tempfile.TemporaryDirectory(prefix="jaeger-completion-") as folder:
                    path = os.path.join(folder, "prompt.txt")
                    with open(path, "w", encoding="utf-8") as handle:
                        os.chmod(path, 0o600)
                        handle.write(prompt)
                    child_argv = list(argv)
                    index = child_argv.index("--single")
                    child_argv[index:index + 2] = ["--prompt-file", path]
                    child_argv.extend(["--cwd", folder])
                    return self._spawn(child_argv, stdin_bytes, spec, on_delta=on_delta)
            return self._spawn(argv, stdin_bytes, spec, on_delta=on_delta)

        def _abandon() -> None:
            self._kill()

        raw = interruptible_call(
            _run,
            interrupt_event,
            on_abandon=_abandon,
            join_on_abandon=3.0,
        )
        if interrupt_event.is_set():
            raise AgentInterrupted("CLI backend was interrupted")
        if visible_stream is not None:
            visible_stream.finish()
        return raw

    def _spawn(
        self,
        argv: list[str],
        stdin_bytes: bytes | None,
        spec: Any,
        on_delta: Any = None,
    ) -> dict[str, Any]:
        env = self._environment(spec)
        popen_kwargs: dict[str, Any] = {
            "args": argv,
            "stdin": subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
            "shell": False,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        logger.debug("cli backend spawn: %s", self.backend_id)
        self._proc = subprocess.Popen(**popen_kwargs)
        try:
            if on_delta is not None:
                stdout, stderr = collect_stream(self._proc, stdin_bytes, self.timeout_s, on_delta)
            else:
                stdout, stderr = self._proc.communicate(
                    input=stdin_bytes, timeout=self.timeout_s,
                )
        except subprocess.TimeoutExpired:
            self._kill()
            if on_delta is None:
                self._proc.communicate()
            raise TimeoutError(
                f"CLI backend {self.backend_id!r} timed out after {self.timeout_s:.0f}s"
            ) from None
        except BaseException:
            self._kill()
            raise
        if self._proc.returncode:
            raise RuntimeError(f"CLI backend {self.backend_id!r} exited with status {self._proc.returncode}: "
                               + stderr.decode("utf-8", errors="replace")[-2000:])
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": self._proc.returncode,
        }

    def _kill(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name != "nt" and proc.pid:
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                if os.name != "nt" and proc.pid:
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except (OSError, ProcessLookupError):
                pass

    def _environment(self, spec: Any) -> dict[str, str]:
        allowed = set(_SAFE_ENV)
        allowed.update(getattr(spec, "credential_env", ()) or ())
        return {key: value for key, value in os.environ.items() if key in allowed}

    def parse_response(self, raw: Any) -> Message:
        if isinstance(raw, str):
            text = parse_cli_text(raw)
        elif isinstance(raw, dict) and "stdout" not in raw and raw.get("role") == "assistant":
            return raw  # already an internal Message
        else:
            payload = raw or {}
            text = parse_cli_text(
                str(payload.get("stdout") or ""),
                str(payload.get("stderr") or ""),
            )
        return Message(role="assistant", content=text, finish_reason="stop")

    def supports(self, feature: str) -> bool:
        return self.backend_id == "grok" and feature == "streaming"

    def health_check(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            spec = self._load_spec()
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "detail": str(exc),
                "latency_s": 0.0,
            }
        executable = self._executable or ""
        probe = list(getattr(spec, "probe_args", ("--version",)) or ("--version",))
        try:
            completed = subprocess.run(  # noqa: S603 — argv list, no shell
                [executable, *probe],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=self._environment(spec),
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "detail": f"probe failed: {type(exc).__name__}: {exc}",
                "latency_s": round(time.perf_counter() - started, 2),
            }
        detail = (completed.stdout or completed.stderr or "").strip().splitlines()
        line = detail[0][:240] if detail else f"exit {completed.returncode}"
        return {
            "ok": completed.returncode == 0,
            "detail": line,
            "latency_s": round(time.perf_counter() - started, 2),
        }
