from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jaeger_os.core.modules import load_module

from jaeger_agent import AgentBridge, ChatMessage, ChatReply, MindNode, TurnResult
from jaeger_agent.messages import AgentActivity, AgentState, ToolEvent


class FakeBus:
    def __init__(self) -> None:
        self.subscribers: dict[str, list[Any]] = {}
        self.published: list[Any] = []

    def subscribe(self, topic: str, callback: Any) -> None:
        self.subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Any) -> None:
        self.subscribers.get(topic, []).remove(callback)

    def publish(self, message: Any) -> None:
        self.published.append(message)
        for callback in list(self.subscribers.get(message.topic, ())):
            callback(message)


class FakeRuntime:
    def __init__(self) -> None:
        self.events: Any = None
        self.closed = False
        self.turns: list[tuple[str, str]] = []

    def start(self, *, events: Any, bus: Any) -> None:
        self.events = events

    def run_turn(self, text: str, *, session_key: str) -> TurnResult:
        self.turns.append((text, session_key))
        self.events.activity("thinking", "working")
        self.events.tool("test_tool", "done", elapsed_s=0.1)
        return TurnResult(text=f"reply: {text}")

    def context_detail(self, session: str) -> str:
        return "ctx 10%"

    def close(self) -> None:
        self.closed = True


def wait_for(predicate: Any, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_module_manifest_is_valid() -> None:
    package_dir = Path(__file__).parents[1] / "jaeger_agent"
    spec = load_module(package_dir)
    assert spec.module == "jaeger_agent"
    assert spec.slot == "mind"
    assert spec.factory == "jaeger_agent:make_mind_node"


def test_bridge_runs_a_headless_turn_and_publishes_events() -> None:
    bus = FakeBus()
    runtime = FakeRuntime()
    bridge = AgentBridge(bus=bus, runtime=runtime)
    bridge.start()

    bus.publish(ChatMessage(text="hello", session="chat-1"))
    wait_for(lambda: any(isinstance(message, ChatReply) for message in bus.published))
    bridge.close()

    assert runtime.turns == [("hello", "chat-1")]
    assert runtime.closed is True
    assert any(isinstance(message, AgentActivity) for message in bus.published)
    assert any(isinstance(message, ToolEvent) for message in bus.published)
    assert any(
        isinstance(message, AgentState) and message.detail == "ctx 10%"
        for message in bus.published
    )
    reply = next(message for message in bus.published if isinstance(message, ChatReply))
    assert reply.text == "reply: hello"
    assert reply.session == "chat-1"


def test_mind_node_accepts_an_injected_runtime() -> None:
    bus = FakeBus()
    runtime = FakeRuntime()
    node = MindNode(bus=bus, runtime=runtime)
    node.setup()
    node.teardown()
    assert runtime.closed is True


def test_reusable_package_never_imports_jaeger_ai_at_module_scope() -> None:
    """The rule that actually matters: this package must IMPORT with no
    host installed.

    Until 0.11 the rule was "the string jaeger_ai appears nowhere",
    which held while the package was only the loop. The move brought the
    whole agent surface across — tools, skills, prompts, the skill
    registry — and a handful of those still reach back for a memory
    backend, a credential store, a venv manager. Those are listed in
    ``jaeger_agent/host.py`` and bound lazily, so a missing host costs
    one tool rather than the package.

    What must never come back is a MODULE-SCOPE import: one of those
    turns ``import jaeger_agent`` into an ImportError on a robot that
    never installed JaegerAI, and then nothing works at all.
    """
    import re

    package_dir = Path(__file__).parents[1] / "jaeger_agent"
    offenders: list[str] = []
    for path in package_dir.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Column 0 == module scope. Indented ones sit inside a
            # function or a try/except guard and only run when called.
            if re.match(r"^(from|import)\s+jaeger_ai\b", line):
                offenders.append(
                    f"{path.relative_to(package_dir)}:{number}: {line.strip()}"
                )
    assert offenders == [], (
        "module-scope host imports break a standalone install:\n" + "\n".join(offenders)
    )


def test_the_package_imports_and_arms_itself_with_no_host_installed() -> None:
    """The same rule, enforced by doing it rather than by reading source.

    Also pins the payload: a bare install is not an empty loop, it is a
    working agent with its whole tool surface registered.
    """
    import subprocess
    import sys

    script = (
        "import sys\n"
        "class B:\n"
        "    def find_module(self, n, p=None):\n"
        "        if n == 'jaeger_ai' or n.startswith('jaeger_ai.'):\n"
        "            raise ImportError('no host installed')\n"
        "sys.meta_path.insert(0, B())\n"
        "import jaeger_agent, jaeger_agent.tools\n"
        "n = len(jaeger_agent.get_tools())\n"
        "assert n > 50, f'bare install registered only {n} tools'\n"
        "print('OK', n)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout
