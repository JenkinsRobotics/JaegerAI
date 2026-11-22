"""A connector denial must survive changing tools or spelling the path differently."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jaeger_ai.core.authority import filesystem
from jaeger_ai.core.frameworks import connectors, discovery
from jaeger_ai.core.frameworks.grants import FrameworkGrants
from jaeger_agent.core import host, workspace


@pytest.fixture
def resources(tmp_path, monkeypatch):
    home = tmp_path / "home"
    memory = home / ".codex/memories/MEMORY.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("PRIVATE_MEMORY_SENTINEL")
    session = home / ".codex/sessions/one.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps({"role": "user", "content": "PRIVATE_SESSION_SENTINEL"}))
    ordinary = home / "project/notes.txt"
    ordinary.parent.mkdir()
    ordinary.write_text("ORDINARY_SENTINEL")
    monkeypatch.setenv("JAEGER_FRAMEWORK_HOME", str(home))
    grant_path = tmp_path / "operator/framework_grants.json"
    monkeypatch.setattr("jaeger_ai.core.frameworks.grants.default_path", lambda: grant_path)
    monkeypatch.setattr(host, "_services", {"filesystem_authority": lambda: filesystem})
    return home, memory, session, ordinary, FrameworkGrants(grant_path)


def test_file_reads_and_aliases_require_the_same_capability(resources):
    home, memory, session, ordinary, grants = resources
    assert workspace._resolve_read(str(ordinary)) == ordinary.resolve()
    alias = home / "ordinary-looking.md"
    alias.symlink_to(memory)
    for path in (memory, alias, memory.parent / ".." / "memories/MEMORY.md"):
        with pytest.raises(workspace.SandboxError, match="not granted read_memory"):
            workspace._resolve_read(str(path))
    grants.set("codex", "read_memory", True, by="owner:test")
    assert workspace._resolve_read(str(alias)) == memory.resolve()
    assert connectors.read_item("codex", "memory", "memories/MEMORY.md")["content"]
    with pytest.raises(workspace.SandboxError, match="not granted read_sessions"):
        workspace._resolve_read(str(session))
    grants.set("codex", "read_memory", False, by="owner:test")
    with pytest.raises(workspace.SandboxError):
        workspace._resolve_read(str(memory))


def test_recursive_search_checks_discovered_resources(resources, monkeypatch):
    from jaeger_agent.tools import files
    home, memory, _, ordinary, _ = resources
    monkeypatch.setattr(files, "_require_layout", lambda: SimpleNamespace(root=home))
    result = files.search_files("SENTINEL", path=str(home))
    assert [row["text"] for row in result["matches"]] == ["ORDINARY_SENTINEL"]
    assert result["skipped_count"] >= 2
    assert "PRIVATE_MEMORY_SENTINEL" not in json.dumps(result)


def test_inventory_does_not_claim_content_reads_and_cannot_follow_parent_symlink(resources):
    home, _, _, _, grants = resources
    grants.set("codex", "read_sessions", True, by="owner:test")
    outside = home / "elsewhere"
    outside.mkdir()
    (outside / "secret.jsonl").write_text('{"role":"user","content":"outside"}')
    (home / ".codex/sessions/link").symlink_to(outside, target_is_directory=True)
    listing = connectors.list_items("codex", "sessions")
    assert listing["observation"] == "file_inventory"
    assert listing["contents_read"] is False
    assert all("link/" not in row["ref"] for row in listing["items"])
    assert not discovery.matching_files(home / ".codex", ("sessions/link/*.jsonl",))


def test_byte_limit_is_reported_even_when_extracted_text_is_short(resources, monkeypatch):
    _, _, session, _, grants = resources
    grants.set("codex", "read_sessions", True, by="owner:test")
    session.write_text(json.dumps({"type": "metadata", "padding": "x" * 1000}) + "\n")
    monkeypatch.setattr(connectors, "MAX_ITEM_BYTES", 100)
    result = connectors.read_item("codex", "sessions", "sessions/one.jsonl")
    assert result["bytes_read"] == 100
    assert result["source_bytes"] > 100
    assert result["source_truncated"] is True
    assert result["truncated"] is True
    assert result["content_truncated"] is False


def test_input_history_formats_are_explicitly_extracted(resources):
    home, _, _, _, grants = resources
    for framework, root, record in (
        ("codex", ".codex", {"session_id": "a", "ts": 1, "text": "build a robot"}),
        ("claude-code", ".claude", {"display": "review the design", "pastedContents": {}}),
    ):
        path = home / root / "history.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record) + '\n{"unknown":true}\n')
        grants.set(framework, "read_sessions", True, by="owner:test")
        result = connectors.read_item(framework, "sessions", "history.jsonl")
        assert "user: " in result["content"]
        assert result["records_seen"] == 2
        assert result["records_extracted"] == 1
        assert result["records_skipped"] == 1


def test_unsupported_sandbox_refuses_instead_of_running_unconfined(resources, monkeypatch):
    monkeypatch.setattr(filesystem.sys, "platform", "unsupported")
    with pytest.raises(PermissionError, match="unconfined process execution is refused"):
        filesystem.confine_command(["/bin/cat", str(resources[1])])


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_os_denial_survives_shell_python_symlinks_and_children(resources):
    home, memory, _, ordinary, grants = resources
    alias = home / "alias"
    alias.symlink_to(memory)
    script = (
        "import pathlib,subprocess,sys\n"
        f"ordinary=pathlib.Path({str(ordinary)!r}); print(ordinary.read_text())\n"
        f"paths=[pathlib.Path({str(memory)!r}),pathlib.Path({str(alias)!r})]\n"
        "for p in paths:\n"
        " try: print(p.read_text())\n"
        " except PermissionError: print('DENIED')\n"
        f"r=subprocess.run(['/bin/cat',{str(memory)!r}],capture_output=True,text=True)\n"
        "print('CHILD_DENIED' if r.returncode else r.stdout)\n"
        f"p=pathlib.Path({str(memory.parent)!r})\n"
        "try: p.rename(p.with_name('moved')); print('MOVED')\n"
        "except PermissionError: print('RENAME_DENIED')\n"
    )
    result = subprocess.run(filesystem.confine_command([sys.executable, "-B", "-c", script]),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["ORDINARY_SENTINEL", "DENIED", "DENIED",
                                          "CHILD_DENIED", "RENAME_DENIED"]
    grants.set("codex", "read_memory", True, by="owner:test")
    result = subprocess.run(filesystem.confine_command(["/bin/cat", str(memory)]),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "PRIVATE_MEMORY_SENTINEL" not in result.stdout
    assert connectors.read_item("codex", "memory", "memories/MEMORY.md")["content"]
    result = subprocess.run(filesystem.confine_command([
        "/bin/sh", "-c", f"printf changed > {shlex.quote(str(memory))}"
    ]), capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert memory.read_text() == "PRIVATE_MEMORY_SENTINEL"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_interruptible_and_pty_processes_inherit_resource_denials(resources):
    from jaeger_agent.util.tool_interrupt import run_interruptible
    from jaeger_agent.tools.pty_exec import PtySession
    import os
    home, memory, _, ordinary, _ = resources
    result = run_interruptible(["/bin/cat", str(memory)], timeout=10)
    assert result.returncode != 0
    assert "PRIVATE_MEMORY_SENTINEL" not in result.stdout
    child = PtySession(f"/bin/cat {shlex.quote(str(memory))}", str(home), dict(os.environ), None)
    try:
        child.proc.wait(timeout=10)
        assert child.proc.returncode != 0
    finally:
        child.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
def test_existing_default_deny_code_sandbox_is_not_widened(resources):
    from jaeger_agent.tools.code import _sandboxed_python_command
    from jaeger_agent.util.tool_interrupt import run_interruptible
    home, memory, _, ordinary, _ = resources
    scratch = home / "scratch"
    scratch.mkdir()
    script = scratch / "probe.py"
    script.write_text(
        f"print(open({str(ordinary)!r}).read())\n"
        f"try: print(open({str(memory)!r}).read())\n"
        "except PermissionError: print('DENIED')\n"
    )
    command, _ = _sandboxed_python_command(str(script), workspace=str(home), scratch=str(scratch))
    confined = filesystem.confine_command(command)
    profile = confined[confined.index("-p") + 1]
    assert "(allow default)" not in profile
    result = run_interruptible(command, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["ORDINARY_SENTINEL", "DENIED"]


def test_owner_grant_records_cannot_be_edited_through_file_tools(resources):
    grants = resources[-1]
    grants.set("codex", "read_memory", True, by="owner:test")
    with pytest.raises(PermissionError, match="owner-managed"):
        filesystem.check_path(grants.path)
