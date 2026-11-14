"""``CliBackendAdapter`` — an installed agent CLI as a Jaeger brain.

The Jaeger loop stays Jaeger: tools, memory, and permissions never
leave this process. The CLI is a completion backend — flatten the
transcript to a prompt, spawn the binary (no ``shell=True``), parse
stdout back to one assistant ``Message``.

Grok and Claude Code receive this turn's Jaeger tools as a native MCP
server (loopback HTTP). Built-in CLI file tools stay disabled. The
Hermes ``<tool_call>`` text catalogue is only a fallback when MCP
cannot start or the backend has no MCP client.

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

from jaeger_agent.loop.interrupt import AgentInterrupted, CallProgress, interruptible_call
from jaeger_agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef

from .base import ProviderAdapter
from .cli_stream import collect_stream, VisibleTextStream

logger = logging.getLogger(__name__)

# --tools "" does not actually disable Grok built-ins (they still appear
# in tool_definitions.json and add ~12k tokens). Deny them by name so
# only Jaeger MCP tools remain. Do not list names that collide with
# Jaeger MCP tools (read_file, web_search): --disallowed-tools matches
# the short name and would hide Jaeger's own tool.
# Grok does not call MCP tools by their MCP name. It looks them up
# with ``search_tool`` and runs them with ``use_tool`` under the
# ``server__tool`` name (e.g. jaeger__list_skill_dir). Those two must
# stay allowed or Jaeger MCP tools are unreachable.
_GROK_BUILTIN_TOOLS = (
    "run_terminal_command", "read_file", "search_replace", "list_dir", "grep",
    "kill_command_or_subagent", "todo_write", "get_command_or_subagent_output",
    "scheduler_create", "scheduler_delete", "scheduler_list", "monitor",
    "workflow", "enter_plan_mode", "exit_plan_mode",
    "ask_user_question", "send_feedback", "image_gen", "image_edit",
    "image_to_video", "reference_to_video", "write",
    # Vendor backend tools (--disable-web-search does not cover these).
    "x_keyword_search", "x_semantic_search", "x_user_search",
    "x_thread_fetch", "x_search", "web_fetch", "code_interpreter",
)

# Wall-clock cap so a vendor-tool spin cannot hang the chat turn.
# "took too long — Retry" is the operator-facing copy.
_CLI_HARD_TURN_TIMEOUT_S = 120.0

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
    *,
    mcp_hint: bool = False,
) -> str:
    """System + transcript → one prompt the CLI can consume."""
    parts: list[str] = []
    if system and system.strip():
        parts.append(f"System:\n{system.strip()}")
    if mcp_hint and not tools:
        parts.append(
            "System:\nUse the Jaeger MCP tools provided in this session for "
            "file, editor, shell, and other work. Jaeger executes them under "
            "the owner's policy. Do not use the CLI's built-in file or editor tools."
        )
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
            # A flattened transcript still needs the structured protocol's
            # call/result correlation, especially after a parallel batch.
            identity = json.dumps({"tool_call_id": msg.get("tool_call_id"),
                                   "name": msg.get("name")}, ensure_ascii=False)
            parts.append(f"Tool result {identity}:\n{text}")
            continue
        if role == "assistant" and msg.get("tool_calls"):
            parts.append(f"Assistant (tool calls):\n{json.dumps(msg.get('tool_calls'), default=str)}")
            if text.strip():
                parts.append(f"Assistant:\n{text}")
            continue
        label = "User" if role == "user" else "Assistant"
        parts.append(f"{label}:\n{text}")
    return "\n\n".join(parts).strip() or "(no input)"



def _extract_pipe_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse Grok's ``<|tool_call|>name\\nkey=value`` text envelopes."""
    import re
    import uuid
    pattern = re.compile(
        r"<\|?tool_call\|?>\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*"
        r"(?:<\|?/tool_call\|?>|</\|?tool_call\|?>|</tool_call>)",
        re.DOTALL,
    )
    calls: list[dict[str, Any]] = []
    for match in pattern.finditer(text or ""):
        name = match.group(1).strip()
        body = (match.group(2) or "").strip()
        args: dict[str, Any] = {}
        if body.startswith("{") or body.startswith("["):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    args = parsed
            except ValueError:
                args = {}
        if not args:
            for line in body.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key:
                    args[key] = value.strip().strip('"').strip("'")
        if name:
            calls.append({"id": f"cli_{uuid.uuid4().hex[:12]}", "name": name, "arguments": args})
    # Anthropic-style XML that Grok also emits.
    invoke = re.compile(
        r'<invoke\s+name="([^"]+)">\s*(.*?)\s*</invoke>',
        re.DOTALL,
    )
    param = re.compile(
        r'<parameter\s+name="([^"]+)">\s*(.*?)\s*</parameter>',
        re.DOTALL,
    )
    for match in invoke.finditer(text or ""):
        name = match.group(1).strip()
        args = {k.strip(): v.strip() for k, v in param.findall(match.group(2) or "") if k.strip()}
        if name:
            calls.append({"id": f"cli_{uuid.uuid4().hex[:12]}", "name": name, "arguments": args})
    return calls


def _strip_pipe_tool_calls(text: str) -> str:
    import re
    pattern = re.compile(
        r"<\|?tool_call\|?>\s*[A-Za-z_][A-Za-z0-9_]*\s*.*?\s*"
        r"(?:<\|?/tool_call\|?>|</\|?tool_call\|?>|</tool_call>)",
        re.DOTALL,
    )
    out = pattern.sub("", text or "")
    out = re.sub(r"<function_calls>\s*.*?\s*</function_calls>", "", out, flags=re.DOTALL)
    out = re.sub(r'<invoke\s+name="[^"]+">\s*.*?\s*</invoke>', '', out, flags=re.DOTALL)
    return out


def parse_cli_stream(stdout: str, stderr: str = "") -> dict[str, Any]:
    """Walk every NDJSON line and keep text plus tool_use / tool_result blocks.

    Grok's streaming-messages-json emits many records. The last text line is
    often an intermediate "I'll look that up" message, not the final answer.
    Prefer the terminal ``type=result`` record. Tool calls that Grok already
    executed (``use_tool`` / MCP) are recorded but marked executed so the
    Jaeger loop does not run them a second time.
    """
    clean = (stdout or "").strip()
    if not clean:
        err = (stderr or "").strip()
        return {
            "text": (err[-100_000:] if err else ""),
            "tool_uses": [],
            "tool_results": [],
            "already_executed": False,
        }

    records: list[Any] = []
    for line in clean.splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append(value)

    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    result_text = ""
    assistant_texts: list[str] = []

    def _collect_blocks(value: Any) -> None:
        if isinstance(value, dict):
            typ = value.get("type")
            if typ == "tool_use" and value.get("name"):
                tool_uses.append(value)
            elif typ == "tool_result":
                tool_results.append(value)
            else:
                for child in value.values():
                    _collect_blocks(child)
        elif isinstance(value, list):
            for child in value:
                _collect_blocks(child)

    def _assistant_text(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        message = value.get("message") if isinstance(value.get("message"), dict) else value
        content = message.get("content")
        parts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
        elif isinstance(content, str) and content.strip():
            parts.append(content)
        return "\n".join(parts).strip()

    for value in records:
        if not isinstance(value, dict):
            continue
        _collect_blocks(value)
        if value.get("type") == "result":
            raw_result = value.get("result")
            if isinstance(raw_result, str) and raw_result.strip():
                result_text = raw_result
            elif raw_result is not None:
                found = _find_text(raw_result)
                if found:
                    result_text = found
        if value.get("type") == "assistant":
            found = _assistant_text(value)
            if found:
                assistant_texts.append(found)

    if result_text:
        text = result_text
    elif assistant_texts:
        text = assistant_texts[-1]
    else:
        extracted = ""
        if len(records) == 1:
            extracted = _find_text(records[0])
        else:
            for value in reversed(records):
                extracted = _find_text(value)
                if extracted:
                    break
        text = extracted or clean[-100_000:]

    already = False
    for block in tool_uses:
        name = str(block.get("name") or "")
        raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        tool_name = str(raw_input.get("tool_name") or "")
        if name == "use_tool" or tool_name.startswith("jaeger__") or name.startswith("jaeger__"):
            already = True
            break
    if not already and tool_results:
        already = True

    return {
        "text": (text or "").strip(),
        "tool_uses": tool_uses,
        "tool_results": tool_results,
        "already_executed": already,
    }


def parse_cli_text(stdout: str, stderr: str = "") -> str:
    """Extract assistant text from CLI stdout. JSON if present, else raw."""
    return str(parse_cli_stream(stdout, stderr).get("text") or "")


def _extract_json_text(text: str) -> str:
    """Kept for callers; prefer ``parse_cli_stream`` for NDJSON."""
    return parse_cli_text(text)


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


def cli_usage(stdout: str) -> dict[str, Any]:
    """Usage, cost and model from an agent CLI's JSON result record.

    ``grok`` and ``claude`` both end ``--output-format json`` /
    ``streaming-messages-json`` with a ``{"type": "result", "usage": {...},
    "total_cost_usd": N, "modelUsage": {model: ...}}`` record (the Claude
    Agent SDK result shape). Returns ``{}`` when there is none (plain text CLIs).
    """
    best: dict[str, Any] = {}
    for line in reversed((stdout or "").strip().splitlines()[-400:]):
        line = line.strip()
        if not line.startswith("{") or '"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else message.get("usage")
        if not isinstance(usage, dict):
            continue
        out: dict[str, Any] = {"usage": {k: int(v) for k, v in usage.items()
                                         if isinstance(v, (int, float)) and not isinstance(v, bool)}}
        cost = record.get("total_cost_usd", record.get("cost_usd"))
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            out["cost_usd"] = float(cost)
        models = record.get("modelUsage")
        model = next(iter(models), None) if isinstance(models, dict) and models else message.get("model")
        if isinstance(model, str) and model:
            out["model"] = model
        if record.get("type") == "result":
            return out
        best = best or out
    return best


# Agent CLIs boot a runtime, load config and often reason before the first
# streamed byte. Never declare "no first progress" earlier than this.
CLI_FIRST_PROGRESS_FLOOR_S = 300.0


def _first_progress_limit(requested: Any, stale: Any, streams: bool) -> float | None:
    """Silence limit before the CLI's first output (``None`` = no limit)."""
    if not streams:
        return None
    values = [float(v) for v in (requested, stale) if isinstance(v, (int, float)) and v > 0]
    if not values:
        return None
    return max(CLI_FIRST_PROGRESS_FLOOR_S, *values)


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
        reasoning_effort: str | None = None,
    ) -> None:
        self.backend_id = (backend_id or "").strip()
        self.timeout_s = float(timeout_s or 600.0)
        self._spec = spec
        self.reasoning_effort = reasoning_effort
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
        self._pending_messages = messages
        self._pending_tools = list(tools or [])
        self._pending_system = system
        from .cli_turn_mcp import MCP_BACKENDS
        mcp_capable = self.backend_id in MCP_BACKENDS
        return {"prompt": flatten_messages(
            messages,
            tools if not mcp_capable else [],
            system,
            mcp_hint=mcp_capable and bool(tools),
        )}

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
        if self.reasoning_effort:
            if self.backend_id == "grok":
                argv.extend(["--reasoning-effort", self.reasoning_effort])
            elif self.backend_id == "claude":
                argv.extend(["--effort", self.reasoning_effort])
            elif self.backend_id == "codex":
                argv.extend(["-c", 'model_reasoning_effort="' + self.reasoning_effort + '"'])
            else:
                raise ValueError(f"Explicit reasoning effort is not supported by the {self.backend_id} CLI adapter")

        on_delta = kwargs.get("on_delta") if self.backend_id == "grok" else None
        on_reasoning = kwargs.get("on_reasoning") if self.backend_id == "grok" else None
        progress = CallProgress()
        # Root cause of the 120s ``StaleCallTimeout`` on grok turns (helpers
        # and any caller without a delta sink): the non-streaming path used
        # ``communicate()``, which never touches the progress beacon, so the
        # stale detector measured TOTAL elapsed time and killed every healthy
        # CLI completion that took longer than 120s. Grok can always report
        # progress, so stream it even when nobody renders the deltas.
        if self.backend_id == "grok" and not callable(on_delta):
            on_delta = lambda _text: None  # noqa: E731 — progress-only sink
        if callable(on_delta) or callable(on_reasoning):
            on_delta = on_delta or (lambda _: None)
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
            from .cli_turn_mcp import MCP_BACKENDS, attach_cli_mcp

            tools = list(getattr(self, "_pending_tools", []) or [])
            execute = kwargs.get("execute_tool")
            use_workdir = (
                (self.backend_id == "grok" and "--single" in argv)
                or (self.backend_id in MCP_BACKENDS and tools and callable(execute))
            )
            if not use_workdir:
                return self._spawn(argv, stdin_bytes, spec, on_delta=on_delta, on_reasoning=on_reasoning, on_progress=progress.touch)

            # Full schemas and history exceed macOS argv limits. Keep the
            # prompt private and out of process listings; delete on exit.
            # The same workdir holds the per-turn Jaeger MCP config.
            from .cli_turn_mcp import stable_cli_workdir
            folder = stable_cli_workdir(self.backend_id)
            live_prompt = prompt
            child_argv = list(argv)
            spawn_stdin = stdin_bytes
            prompt_file = None
            if self.backend_id == "grok" and "--single" in child_argv:
                prompt_file = os.path.join(folder, "prompt.txt")
                index = child_argv.index("--single")
                child_argv[index:index + 2] = ["--prompt-file", prompt_file]
                child_argv.extend(["--cwd", folder])
            child_argv, extra_env, mcp, text_fallback = attach_cli_mcp(
                self.backend_id, child_argv, folder, tools, execute if callable(execute) else None,
            )
            if text_fallback and tools:
                live_prompt = flatten_messages(
                    getattr(self, "_pending_messages", []) or [],
                    tools,
                    getattr(self, "_pending_system", "") or "",
                )
                if spawn_stdin is not None:
                    spawn_stdin = live_prompt.encode("utf-8")
            if prompt_file:
                with open(prompt_file, "w", encoding="utf-8") as handle:
                    os.chmod(prompt_file, 0o600)
                    handle.write(live_prompt)
            if self.backend_id == "grok":
                # --tools "" hid Jaeger MCP tools from the model request.
                while "--tools" in child_argv:
                    index = child_argv.index("--tools")
                    del child_argv[index:index + 2]
                import uuid
                # Jaeger already sends the conversation. A reused Grok
                # session in the stable cwd stacked prior turns into a
                # 20k–80k prompt. Start a fresh session every turn.
                child_argv.extend(["--session-id", str(uuid.uuid4())])
                tool_names = ", ".join(
                    str(getattr(tool, "name", "") or "")
                    for tool in tools
                    if getattr(tool, "name", "")
                )
                override = (
                    "You are Jaeger's language model. Follow the System "
                    "section and the current request. Jaeger MCP tools are "
                    "named jaeger__<tool> (for example jaeger__list_skill_dir, "
                    "jaeger__read_file, jaeger__terminal). Available short "
                    "names: " + (tool_names or "list_skill_dir, read_file, terminal")
                    + ". Look a tool up with search_tool if needed, then call "
                    "it with use_tool using the jaeger__ name. To list the "
                    "current workspace, use_tool tool_name=jaeger__list_skill_dir "
                    "with path '.'. Do not use built-in file, editor, X search, "
                    "or web tools. The CLI cache directory is not the workspace."
                )
                child_argv.extend(["--system-prompt-override", override])
                child_argv.extend(["--disallowed-tools", ",".join(_GROK_BUILTIN_TOOLS)])
                if "--no-plan" not in child_argv:
                    child_argv.append("--no-plan")
            # Keep the process-global MCP server running between turns.
            return self._spawn(
                child_argv, spawn_stdin, spec,
                on_delta=on_delta, on_reasoning=on_reasoning,
                on_progress=progress.touch,
                cwd=folder,
                extra_env=extra_env,
            )

        def _abandon() -> None:
            self._kill()

        # A CLI that cannot stream gives the detector nothing to observe; a
        # silence limit would just be a wall clock. Fall back to the CLI's
        # own process timeout (``self.timeout_s``) instead of a false stall.
        streams = on_delta is not None
        raw = interruptible_call(
            _run,
            interrupt_event,
            stale_timeout=kwargs.get("stale_timeout") if streams else None,
            first_progress_timeout_s=_first_progress_limit(
                kwargs.get("first_progress_timeout_s"), kwargs.get("stale_timeout"), streams),
            on_heartbeat=kwargs.get("on_heartbeat"),
            progress=progress,
            on_abandon=_abandon,
            join_on_abandon=3.0,
        )
        if interrupt_event.is_set():
            raise AgentInterrupted("CLI backend was interrupted")
        if visible_stream is not None:
            visible_stream.finish()
        return raw


    def warmup(self) -> None:
        """Pre-start the loopback MCP server and the Grok leader, if installed."""
        from .cli_turn_mcp import (
            GROK_LEADER_SOCKET, grok_leader_argv, stable_cli_workdir,
        )
        spec = self._load_spec()
        folder = stable_cli_workdir(self.backend_id)

        # Do not start the MCP server with an empty catalog. A reused
        # empty server left Grok with no Jaeger tools. The first real
        # turn starts MCP with the scoped tool set.
        if self.backend_id != "grok":
            return
        executable = self._executable or ""
        if not executable:
            return
        argv = [executable, *grok_leader_argv(), "--cwd", folder, "doctor"]
        env = os.environ.copy()
        env["GROK_LEADER_SOCKET"] = str(GROK_LEADER_SOCKET)
        env["GROK_FOLDER_TRUST"] = "0"
        try:
            subprocess.run(
                argv,
                cwd=folder,
                env=env,
                timeout=20,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            pass

    def _spawn(
        self,
        argv: list[str],
        stdin_bytes: bytes | None,
        spec: Any,
        on_delta: Any = None,
        on_reasoning: Any = None,
        on_progress: Any = None,
        cwd: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        env = self._environment(spec, extra_env)
        try:
            hard = float(os.environ.get("JAEGER_CLI_TURN_TIMEOUT_S") or _CLI_HARD_TURN_TIMEOUT_S)
        except (TypeError, ValueError):
            hard = _CLI_HARD_TURN_TIMEOUT_S
        if hard > 0:
            self.timeout_s = min(self.timeout_s or hard, hard)
        popen_kwargs: dict[str, Any] = {
            "args": argv,
            "stdin": subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
            "shell": False,
        }
        if cwd:
            popen_kwargs["cwd"] = cwd
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        logger.debug("cli backend spawn: %s", self.backend_id)
        self._proc = subprocess.Popen(**popen_kwargs)
        try:
            if on_delta is not None:
                stdout, stderr = collect_stream(self._proc, stdin_bytes, self.timeout_s, on_delta, on_reasoning, on_progress)
            else:
                stdout, stderr = self._proc.communicate(
                    input=stdin_bytes, timeout=self.timeout_s,
                )
        except subprocess.TimeoutExpired:
            self._kill()
            if on_delta is None:
                try:
                    self._proc.communicate()
                except Exception:
                    pass
            from jaeger_ai.core.models.request_policy import ModelPolicyError
            raise ModelPolicyError("took too long — Retry") from None
        except BaseException:
            self._kill()
            raise
        if self._proc.returncode:
            err = stderr.decode("utf-8", errors="replace")
            try:
                from jaeger_ai.core.models.discovery import parse_cli_usage_limit
                limit = parse_cli_usage_limit(err)
            except Exception:  # noqa: BLE001
                limit = None
            if limit:
                from jaeger_ai.core.models.request_policy import ModelPolicyError
                raise ModelPolicyError(limit)
            if self.backend_id == "gemini" and (
                "IneligibleTierError" in err or "no longer supported for Gemini" in err
            ):
                from jaeger_ai.core.models.request_policy import ModelPolicyError
                raise ModelPolicyError(
                    "The Gemini CLI is no longer supported for individual Gemini Code Assist "
                    "accounts. Google asks you to use Antigravity instead (https://antigravity.google)."
                )
            if "max turns reached" in err.lower() or "timed out" in err.lower():
                from jaeger_ai.core.models.request_policy import ModelPolicyError
                raise ModelPolicyError("took too long — Retry")
            raise RuntimeError(f"CLI backend {self.backend_id!r} exited with status {self._proc.returncode}: "
                               + err[-2000:])
        text = stdout.decode("utf-8", errors="replace")
        return {
            "stdout": text,
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": self._proc.returncode,
            # usage / cost_usd / model when the CLI reports them (read by the loop).
            **cli_usage(text),
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

    def _environment(self, spec: Any, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        allowed = set(_SAFE_ENV)
        allowed.update(getattr(spec, "credential_env", ()) or ())
        env = {key: value for key, value in os.environ.items() if key in allowed}
        if extra_env:
            env.update({key: value for key, value in extra_env.items() if value is not None})
        if self.backend_id == "gemini":
            env.setdefault("GEMINI_CLI_TRUST_WORKSPACE", "true")
        return env

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
        # Prefer a full NDJSON walk so tool_use / tool_result blocks are
        # not dropped in favour of the last text fragment.
        stream = parse_cli_stream(raw if isinstance(raw, str) else str((raw or {}).get("stdout") or ""),
                                  "" if isinstance(raw, str) else str((raw or {}).get("stderr") or ""))
        text = str(stream.get("text") or text or "")
        if stream.get("already_executed"):
            # Grok already ran Jaeger MCP via use_tool; the loopback
            # executor emitted the tool row. Do not enqueue a second call.
            return Message(role="assistant", content=_strip_pipe_tool_calls(text).strip() or text, finish_reason="stop")
        from jaeger_agent.dialects import extract_tool_calls
        tool_calls = list(extract_tool_calls(text) or [])
        if not tool_calls:
            tool_calls = _extract_pipe_tool_calls(text)
        if tool_calls:
            text = _strip_pipe_tool_calls(text).strip()
            message: dict[str, Any] = {"role": "assistant", "content": text or None}
            message["tool_calls"] = tool_calls
            return message  # type: ignore[return-value]
        return Message(role="assistant", content=text, finish_reason="stop")

    def supports(self, feature: str) -> bool:
        if feature == "streaming":
            return self.backend_id == "grok"
        if feature == "mcp_tools":
            from .cli_turn_mcp import MCP_BACKENDS
            return self.backend_id in MCP_BACKENDS
        return False

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
