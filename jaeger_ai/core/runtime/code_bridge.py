"""Programmatic tool calling — a script that can call the agent's tools.

The chain problem: asking the model to read twelve files and summarise
each costs twelve round-trips, and every one of them re-sends the whole
conversation and lands another full tool result in the window. On a
local 8K model that is the difference between a task finishing and a
task compacting itself to death halfway through.

This is the Hermes ``execute_code`` pattern, scoped to what a
local-first agent needs. The model writes ONE Python script. The script
imports ``jaeger_tools`` and calls the agent's real tools from inside a
loop. Tool calls travel over a Unix socket back to this process, get
dispatched through the ordinary registry — same validation, same
permission tiers, same audit trail — and the results go back to the
script. **Only the script's stdout returns to the model.** The twelve
intermediate results never enter the context window at all.

What makes this safe to add rather than a hole in the sandbox:

  * dispatch goes through ``ToolDef.dispatch`` exactly like a normal
    tool call, so a tier-gated tool still prompts and a denied one
    still raises. The bridge grants no authority the model did not
    already have — it changes the number of inference turns, not the
    permission surface;
  * the socket lives in a 0700 directory and is deleted on the way
    out. Only the child, which is handed the path in its environment,
    can reach it;
  * a call ceiling and a wall-clock timeout bound the script. A runaway
    loop hits the ceiling and the script sees a normal exception;
  * interactive tools are refused. There is no model in this loop to
    answer a clarifying question, so a script that calls ``clarify``
    would block until the timeout instead of asking anyone;
  * recursion is refused. A script cannot call the bridge.

Brain-agnostic by construction: nothing here knows or cares what is
answering. A script chaining twelve reads costs the same twelve
dispatches whether the brain is a local GGUF or a cloud endpoint —
what changes is only how many inference turns it saved, which is
exactly the value that scales *up* as the window gets smaller.

Platform: POSIX. Windows has no ``AF_UNIX`` in this form, so the tool
declines there rather than pretending.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# Tools a bridged script may never call.
#
#   * the bridge itself — no recursion;
#   * interactive tools — nobody is listening on the other end of a
#     question asked from inside a script, so the call would hang until
#     the timeout and then read as a tool failure;
#   * delegation — a subagent is a model loop, and starting one from
#     inside a script buries a whole conversation where the operator
#     cannot see or interrupt it.
_BLOCKED_TOOLS = frozenset({
    "execute_with_tools",
    "clarify", "ask_user", "confirm",
    "delegate_task",
})

# Ceiling on tool calls per script. Generous — the whole point is a
# chain longer than the model would spend turns on — but finite, so a
# `while True:` costs one error instead of the timeout.
MAX_BRIDGE_CALLS = 120

# The stub the child imports. Written next to the script, on a
# PYTHONPATH the child alone gets. ``__getattr__`` means the stub does
# not need regenerating when the registry changes, and an unknown name
# fails on the server side with the registry's own error text.
_STUB_SOURCE = '''\
"""Call JaegerAI's tools from inside this script.

Every attribute is a tool. Call it with keyword arguments::

    import jaeger_tools as jt

    notes = jt.list_skill_dir(path="notes")
    for name in notes["entries"]:
        body = jt.file_read(path=f"notes/{name}")
        print(name, len(body.get("content", "")))

Only what you ``print`` comes back to the agent — intermediate results
stay here. Each call raises ``ToolError`` when the tool fails, so
ordinary ``try``/``except`` works.
"""

import json
import os
import socket

__all__ = ["ToolError", "call"]


class ToolError(RuntimeError):
    """A tool call that did not succeed."""


class _Bridge:
    def __init__(self):
        self._path = os.environ["JAEGER_TOOL_SOCKET"]
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._path)
        self._file = self._sock.makefile("rwb")

    def call(self, tool, args):
        payload = json.dumps({"tool": tool, "args": args}) + "\\n"
        self._file.write(payload.encode("utf-8"))
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise ToolError("tool bridge closed")
        reply = json.loads(line.decode("utf-8"))
        if not reply.get("ok"):
            raise ToolError(str(reply.get("error") or "tool failed"))
        return reply.get("result")


_bridge = None


def call(tool, **kwargs):
    """Call ``tool`` by name. ``jt.call("file_read", path=...)``."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
    return _bridge.call(tool, kwargs)


def __getattr__(name):
    if name.startswith("_"):
        raise AttributeError(name)

    def _tool(**kwargs):
        return call(name, **kwargs)

    _tool.__name__ = name
    return _tool
'''


class BridgeRefused(RuntimeError):
    """The bridge declined to run — platform, or nothing to run."""


def _dispatch(name: str) -> Any:
    """Dispatch one tool by name through the ordinary registry.

    Deliberately re-resolved per call rather than snapshotted: a script
    that calls ``reload_skills`` should see the tools it just
    registered, the same way the agent loop refreshes its catalogue
    mid-turn.
    """
    from jaeger_os.core.tools.tool_registry import get_tool, has_tool

    if not has_tool(name):
        raise KeyError(f"unknown tool {name!r}")
    return get_tool(name)


class _BridgeServer:
    """Accepts child connections and dispatches their tool calls.

    One thread per connection; scripts are expected to use one, but a
    script that spawns threads of its own gets correct behaviour rather
    than a deadlock.
    """

    def __init__(self, socket_path: Path, *, max_calls: int = MAX_BRIDGE_CALLS):
        self.socket_path = socket_path
        self.max_calls = max_calls
        self.calls: list[str] = []
        self.errors: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(socket_path))
        self._server.listen(4)
        self._server.settimeout(0.25)
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="tool-bridge", daemon=True,
        )

    # -- lifecycle --------------------------------------------------

    def start(self) -> None:
        self._accept_thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        for thread in list(self._threads):
            thread.join(timeout=1.0)
        try:
            self.socket_path.unlink()
        except OSError:
            pass

    # -- serving ----------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=self._serve, args=(conn,),
                name="tool-bridge-conn", daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def _serve(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rwb") as stream:
            while not self._stop.is_set():
                line = stream.readline()
                if not line:
                    return
                reply = self._handle(line)
                try:
                    stream.write((json.dumps(reply, default=str) + "\n").encode())
                    stream.flush()
                except OSError:
                    return

    def _handle(self, line: bytes) -> dict[str, Any]:
        try:
            request = json.loads(line.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"bad request: {exc}"}

        name = str(request.get("tool") or "")
        args = request.get("args")
        if not isinstance(args, dict):
            args = {}

        if name in _BLOCKED_TOOLS:
            return {
                "ok": False,
                "error": (
                    f"{name!r} cannot be called from a script — "
                    "call it as a normal tool instead"
                ),
            }

        with self._lock:
            if len(self.calls) >= self.max_calls:
                return {
                    "ok": False,
                    "error": (
                        f"tool-call ceiling reached ({self.max_calls}) — "
                        "the script is looping; narrow the work"
                    ),
                }
            self.calls.append(name)

        try:
            tool_def = _dispatch(name)
        except KeyError as exc:
            with self._lock:
                self.errors.append(f"{name}: unknown")
            return {"ok": False, "error": str(exc)}

        if getattr(tool_def, "interactive", False):
            return {
                "ok": False,
                "error": (
                    f"{name!r} needs a person to answer and nobody is "
                    "watching a script — ask before running the script"
                ),
            }

        try:
            result = tool_def.dispatch(args)
        except Exception as exc:  # noqa: BLE001 — becomes ToolError in the child
            with self._lock:
                self.errors.append(f"{name}: {type(exc).__name__}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "result": result}


def run_bridged_script(
    code: str,
    *,
    timeout_s: float = 60.0,
    workspace: Path | None = None,
    max_output_chars: int = 200_000,
    max_calls: int = MAX_BRIDGE_CALLS,
) -> dict[str, Any]:
    """Run ``code`` in a subprocess that can call the agent's tools.

    Returns the same shape the other code tools return, plus the tool
    calls the script actually made — the operator and the audit log
    should be able to see what a script did, not just what it printed.
    """
    if not str(code or "").strip():
        raise BridgeRefused("no code given")
    if not hasattr(socket, "AF_UNIX"):
        raise BridgeRefused(
            "programmatic tool calling needs Unix domain sockets; "
            "use run_python and the ordinary tools on this platform"
        )

    cwd = Path(workspace) if workspace is not None else Path.cwd()

    # 0700 so the socket is reachable only by this user, and torn down
    # with the directory when the call ends.
    with tempfile.TemporaryDirectory(prefix="jaeger-bridge-") as tmp:
        tmpdir = Path(tmp)
        os.chmod(tmpdir, 0o700)
        socket_path = tmpdir / "tools.sock"
        (tmpdir / "jaeger_tools.py").write_text(_STUB_SOURCE, encoding="utf-8")
        script_path = tmpdir / "script.py"
        script_path.write_text(code, encoding="utf-8")

        server = _BridgeServer(socket_path, max_calls=max_calls)
        server.start()

        env = dict(os.environ)
        env["JAEGER_TOOL_SOCKET"] = str(socket_path)
        # The child needs the stub importable and the workspace usable.
        # ``-s`` keeps user site-packages out; PYTHONPATH carries only
        # the bridge dir, so the stub cannot be shadowed.
        env["PYTHONPATH"] = str(tmpdir)
        env["PYTHONUNBUFFERED"] = "1"

        started = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(  # noqa: S603 — argv is fixed
                [sys.executable, "-s", str(script_path)],
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_s)),
            )
            stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + (
                f"\n[timed out after {timeout_s}s]"
            )
            returncode = -1
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
        finally:
            server.stop()

        elapsed = time.perf_counter() - started

    return {
        "ok": (returncode == 0) and not timed_out,
        "stdout": stdout[:max_output_chars],
        "stderr": stderr[:max_output_chars],
        "returncode": returncode,
        "timed_out": timed_out,
        "tool_calls": list(server.calls),
        "tool_call_count": len(server.calls),
        "tool_errors": list(server.errors),
        "elapsed_s": round(elapsed, 3),
    }


__all__ = [
    "MAX_BRIDGE_CALLS",
    "BridgeRefused",
    "run_bridged_script",
]
