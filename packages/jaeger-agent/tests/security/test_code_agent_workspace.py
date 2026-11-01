"""execute_code may write the agent's own workspace folder, and nothing wider (Matthew, 2026-11-01)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_agent.tools import code


def _layout(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "instances" / "jaeger"
    (root / "skills").mkdir(parents=True)
    return SimpleNamespace(root=root, skills_dir=root / "skills", workspace_dir=root / "workspace")


def test_agent_workspace_is_the_instance_workspace_only(tmp_path: Path) -> None:
    lay = _layout(tmp_path)
    assert code._agent_workspace(lay) == os.path.realpath(lay.root / "workspace")


def test_symlinked_or_relocated_workspace_is_refused(tmp_path: Path) -> None:
    lay = _layout(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    (lay.root / "workspace").symlink_to(tmp_path / "elsewhere")
    assert code._agent_workspace(lay) is None
    other = SimpleNamespace(root=lay.root, workspace_dir=tmp_path / "other-agent" / "workspace")
    assert code._agent_workspace(other) is None


def test_linux_binds_only_the_extra_workspace(monkeypatch, tmp_path: Path) -> None:
    ws, scratch, extra = tmp_path / "skills", tmp_path / "scratch", tmp_path / "workspace"
    for d in (ws, scratch, extra):
        d.mkdir()
    monkeypatch.setattr(code.sys, "platform", "linux")
    monkeypatch.setattr(code.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(code, "_probe_linux_bwrap", lambda path: (True, ""))
    cmd, _ = code._sandboxed_python_command(str(ws / "s.py"), workspace=str(ws), scratch=str(scratch),
                                            extra_writable=(str(extra),))
    binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--bind"]
    assert binds == [str(ws), str(scratch), str(extra)]


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.isfile("/usr/bin/sandbox-exec"), reason="macOS seatbelt")
def test_macos_seatbelt_writes_agent_workspace_but_not_tmp_or_siblings(tmp_path: Path) -> None:
    base = Path(os.path.realpath(tmp_path))
    skills, scratch, ws, sibling = base / "skills", base / "scratch", base / "workspace", base / "other-agent"
    for d in (skills, scratch, ws, sibling):
        d.mkdir()
    script = scratch / "s.py"
    script.write_text(
        "import sys\n"
        "def tryw(p):\n"
        "    try:\n        open(p,'w').write('x'); return 'ok'\n"
        "    except OSError as e:\n        return 'denied'\n"
        f"print(tryw({str(ws / 'out.txt')!r}), tryw({str(sibling / 'x.txt')!r}), tryw('/private/tmp/jaeger-j087-probe.txt'))\n",
        encoding="utf-8",
    )
    cmd, backend = code._sandboxed_python_command(str(script), workspace=str(skills), scratch=str(scratch),
                                                  extra_writable=(str(ws),))
    assert backend == "macos-seatbelt"
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.split()
    assert out == ["ok", "denied", "denied"]
    assert (ws / "out.txt").read_text() == "x"


def test_unbound_run_cwd_is_the_instance_root(tmp_path: Path) -> None:
    lay = _layout(tmp_path)
    ws = code._agent_workspace(lay)
    assert code._unbound_run_cwd(lay, ws) == os.path.realpath(lay.root)
    assert code._unbound_run_cwd(lay, None) is None
    assert code._unbound_run_cwd(lay, str(tmp_path / "elsewhere" / "workspace")) is None


def test_linux_chdirs_to_run_cwd(monkeypatch, tmp_path: Path) -> None:
    lay = _layout(tmp_path)
    ws = code._agent_workspace(lay)
    scratch = tmp_path / "scratch"; scratch.mkdir()
    monkeypatch.setattr(code.sys, "platform", "linux")
    monkeypatch.setattr(code.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(code, "_probe_linux_bwrap", lambda path: (True, ""))
    cmd, _ = code._sandboxed_python_command("s.py", workspace=str(lay.skills_dir), scratch=str(scratch),
                                            extra_writable=(ws,), run_cwd=str(lay.root))
    assert cmd[cmd.index("--chdir") + 1] == str(lay.root)


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.isfile("/usr/bin/sandbox-exec"), reason="macOS seatbelt")
def test_macos_relative_workspace_path_lands_in_the_real_workspace(tmp_path: Path) -> None:
    lay = _layout(Path(os.path.realpath(tmp_path)))
    ws = code._agent_workspace(lay)
    root = code._unbound_run_cwd(lay, ws)
    (lay.skills_dir / "workspace").mkdir()  # the old wrong target exists, as it does on the Mac
    scratch = Path(os.path.realpath(tmp_path)) / "scratch"; scratch.mkdir()
    script = scratch / "s.py"
    script.write_text(
        "def tryw(p):\n"
        "    try:\n        open(p,'w').write('x'); return 'ok'\n"
        "    except OSError:\n        return 'denied'\n"
        "print(tryw('workspace/r.txt'), tryw('skills/s.txt'), tryw('bare.txt'))\n", encoding="utf-8")
    cmd, _ = code._sandboxed_python_command(str(script), workspace=str(lay.skills_dir), scratch=str(scratch),
                                            extra_writable=(ws,), run_cwd=root)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=root).stdout.split()
    assert out == ["ok", "ok", "denied"]
    assert (Path(ws) / "r.txt").read_text() == "x"
    assert not (lay.skills_dir / "workspace" / "r.txt").exists()
    assert (lay.skills_dir / "s.txt").exists()
