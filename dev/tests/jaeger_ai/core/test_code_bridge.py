"""Programmatic tool calling — one script, many tools, one inference turn.

The chain this exists for: twelve files read one-per-turn costs twelve
round-trips and puts twelve full results in the window. On a local 8K
model that is the difference between finishing and compacting to death.
A bridged script does the whole chain in one turn and returns only what
it printed.

What is pinned here is mostly the boundary, because that is what makes
the feature safe to have at all: dispatch goes through the ordinary
registry, blocked tools stay blocked, the ceiling and the timeout hold,
and the socket does not outlive the call.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from jaeger_ai.core.runtime.code_bridge import (
    MAX_BRIDGE_CALLS,
    BridgeRefused,
    run_bridged_script,
)

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="the bridge needs Unix domain sockets",
)


@pytest.fixture
def tool_registry():
    """A registry holding only what a test registers.

    The real registry is process-global; snapshot and restore it so a
    bridge test can't leak a fake tool into everything after it.
    """
    from jaeger_os.core.tools import tool_registry as reg

    saved = dict(reg._registry)
    reg._registry.clear()
    try:
        yield reg
    finally:
        reg._registry.clear()
        reg._registry.update(saved)


def _register(reg, name, fn, **kw):
    from jaeger_os.core.tools.tool_registry import register_tool_from_function

    fn.__name__ = name
    return register_tool_from_function(name=name, **kw)(fn)


# ── the chain actually happens ──────────────────────────────────────


def test_a_script_calls_a_real_tool_and_only_stdout_returns(tool_registry):
    seen = []

    def echo(value: str = "") -> dict:
        """Echo a value."""
        seen.append(value)
        return {"ok": True, "echoed": value.upper()}

    _register(tool_registry, "echo", echo)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "print(jt.echo(value='hello')['echoed'])\n",
        timeout_s=30,
    )

    assert result["ok"] is True, result["stderr"]
    assert result["stdout"].strip() == "HELLO"
    assert seen == ["hello"]
    assert result["tool_calls"] == ["echo"]


def test_the_whole_chain_costs_one_call_and_leaks_no_intermediates(tool_registry):
    """Twelve dispatches, one script, and only the summary comes back —
    the intermediate results never enter the model's context."""
    def read_item(index: int = 0) -> dict:
        """Read one item."""
        return {"ok": True, "body": "TODO" if index % 4 == 0 else "clean"}

    _register(tool_registry, "read_item", read_item)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "hits = [i for i in range(12) if 'TODO' in jt.read_item(index=i)['body']]\n"
        "print('flagged:', hits)\n",
        timeout_s=30,
    )

    assert result["ok"] is True, result["stderr"]
    assert result["stdout"].strip() == "flagged: [0, 4, 8]"
    assert result["tool_call_count"] == 12
    # The bodies stayed inside the script.
    assert "clean" not in result["stdout"]


def test_call_by_name_works_for_awkward_tool_names(tool_registry):
    def weird(x: int = 0) -> dict:
        """Doubles."""
        return {"ok": True, "v": x * 2}

    _register(tool_registry, "weird", weird)
    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "print(jt.call('weird', x=21)['v'])\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "42"


# ── failure reaches the script as an exception ──────────────────────


def test_a_failing_tool_raises_in_the_script(tool_registry):
    def explode() -> dict:
        """Always fails."""
        raise ValueError("nope")

    _register(tool_registry, "explode", explode)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "try:\n"
        "    jt.explode()\n"
        "except jt.ToolError as exc:\n"
        "    print('caught:', 'nope' in str(exc))\n",
        timeout_s=30,
    )
    assert result["ok"] is True, result["stderr"]
    assert result["stdout"].strip() == "caught: True"
    assert result["tool_errors"] == ["explode: ValueError"]


def test_one_bad_item_need_not_kill_the_batch(tool_registry):
    def maybe(index: int = 0) -> dict:
        """Fails on 1."""
        if index == 1:
            raise RuntimeError("bad item")
        return {"ok": True, "n": index}

    _register(tool_registry, "maybe", maybe)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "done = []\n"
        "for i in range(4):\n"
        "    try:\n"
        "        done.append(jt.maybe(index=i)['n'])\n"
        "    except jt.ToolError:\n"
        "        pass\n"
        "print(done)\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "[0, 2, 3]"


def test_unknown_tool_is_named_not_silently_skipped(tool_registry):
    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "try:\n"
        "    jt.no_such_tool()\n"
        "except jt.ToolError as exc:\n"
        "    print('err:', 'no_such_tool' in str(exc))\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "err: True"


# ── the boundary ────────────────────────────────────────────────────


@pytest.mark.parametrize("blocked", [
    "execute_with_tools", "clarify", "ask_user", "delegate_task",
])
def test_blocked_tools_are_refused(tool_registry, blocked):
    """No recursion, and nothing that needs a person to answer — a
    question asked from inside a script reaches nobody."""
    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "try:\n"
        f"    jt.{blocked}()\n"
        "except jt.ToolError as exc:\n"
        "    print('refused')\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "refused"


def test_an_interactive_tool_is_refused_rather_than_hanging(tool_registry):
    def needs_a_person(q: str = "") -> dict:
        """Would block."""
        return {"ok": True}

    _register(tool_registry, "needs_a_person", needs_a_person, interactive=True)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "try:\n"
        "    jt.needs_a_person(q='?')\n"
        "except jt.ToolError as exc:\n"
        "    print('refused:', 'nobody is watching' in str(exc))\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "refused: True"


def test_the_call_ceiling_stops_a_runaway_loop(tool_registry):
    """A `while True:` costs one error, not the whole timeout."""
    def tick() -> dict:
        """Cheap."""
        return {"ok": True}

    _register(tool_registry, "tick", tick)

    result = run_bridged_script(
        "import jaeger_tools as jt\n"
        "n = 0\n"
        "try:\n"
        "    while True:\n"
        "        jt.tick()\n"
        "        n += 1\n"
        "except jt.ToolError as exc:\n"
        "    print('stopped at', n, 'ceiling' in str(exc))\n",
        timeout_s=60,
        max_calls=8,
    )
    assert result["stdout"].strip() == "stopped at 8 True"
    assert result["tool_call_count"] == 8


def test_a_hanging_script_times_out(tool_registry):
    result = run_bridged_script(
        "import time\ntime.sleep(30)\n", timeout_s=1.0,
    )
    assert result["ok"] is False
    assert result["timed_out"] is True


def test_a_script_that_raises_is_not_ok_and_keeps_its_traceback():
    result = run_bridged_script("raise SystemExit(3)\n", timeout_s=30)
    assert result["ok"] is False
    assert result["returncode"] == 3


def test_empty_code_is_refused():
    with pytest.raises(BridgeRefused):
        run_bridged_script("   \n")


# ── hygiene ─────────────────────────────────────────────────────────


def test_the_socket_does_not_outlive_the_call(tool_registry):
    """The bridge dir is removed with the call — a socket left behind
    would be a live tool-dispatch endpoint on disk."""
    result = run_bridged_script(
        "import os\nprint(os.environ['JAEGER_TOOL_SOCKET'])\n",
        timeout_s=30,
    )
    path = Path(result["stdout"].strip())
    assert not path.exists()
    assert not path.parent.exists()


def test_output_is_capped(tool_registry):
    result = run_bridged_script(
        "print('x' * 50000)\n", timeout_s=30, max_output_chars=1000,
    )
    assert len(result["stdout"]) <= 1000


def test_the_ceiling_default_is_generous_but_finite():
    assert 20 < MAX_BRIDGE_CALLS < 1000


def test_the_tool_is_registered_and_gated():
    """Registered on import, and carrying the same tier ``execute_code``
    does — the bridge grants no authority the model lacked."""
    from jaeger_os.core.tools.tool_registry import get_tool, has_tool

    import jaeger_ai.core.runtime.code_bridge_tool  # noqa: F401

    assert has_tool("execute_with_tools")
    tool = get_tool("execute_with_tools")
    assert "jaeger_tools" in (tool.description or "")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
def test_bridge_dir_is_private(tool_registry):
    result = run_bridged_script(
        "import os, stat\n"
        "d = os.path.dirname(os.environ['JAEGER_TOOL_SOCKET'])\n"
        "print(oct(stat.S_IMODE(os.stat(d).st_mode)))\n",
        timeout_s=30,
    )
    assert result["stdout"].strip() == "0o700"
