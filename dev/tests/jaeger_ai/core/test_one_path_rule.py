"""One path rule for file and shell tools (capability run 2026-10-09).

The local model alternated between ``workspace/x`` and the absolute path the
prompt gave it: write_file refused the absolute form, run_shell (in a scratch
tempdir) could not see the relative form. Every tool now agrees:

  * run_shell starts in the instance root (or the bound project),
  * write tools accept an absolute path inside a writable root,
  * nothing outside those roots, and no instance control file, is writable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_agent import tools
from jaeger_agent.core import workspace as ws
from jaeger_ai.core.instance.instance import InstanceLayout


@pytest.fixture
def inst(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    before = ws.get_project_root()
    ws.set_project_root(None)
    yield layout
    ws.set_project_root(before)


@pytest.fixture
def allow_shell():
    from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def test_absolute_write_inside_workspace_lands_there(inst):
    target = ws.get_effective_workspace_dir() / "cap" / "out.txt"
    r = tools.file_write(str(target), "hello\n")
    assert r["written"] is True, r
    assert target.read_text() == "hello\n"


def test_absolute_and_relative_name_the_same_file(inst):
    tools.file_write("workspace/cap/a.py", "x = 1\n")
    absolute = ws.get_effective_workspace_dir() / "cap" / "a.py"
    r = tools.edit_file(str(absolute), "x = 1", "x = 2")
    assert r.get("ok", r.get("edited", r.get("written"))) not in (False, None), r
    assert absolute.read_text() == "x = 2\n"


def test_absolute_write_inside_skills_is_allowed(inst):
    target = inst.skills_dir / "s.py"
    assert tools.file_write(str(target), "pass\n")["written"] is True


@pytest.mark.parametrize("name", ["config.yaml", "identity.yaml", "manifest.json", "credentials/key"])
def test_absolute_write_to_instance_control_files_is_refused(inst, name):
    target = inst.root / name
    before = target.read_bytes() if target.exists() else None
    r = tools.file_write(str(target), "pwned\n")
    assert r["written"] is False
    assert (target.read_bytes() if target.exists() else None) == before


def test_absolute_write_outside_roots_is_refused_with_the_roots_named(inst, tmp_path):
    escape = tmp_path / "elsewhere" / "x.txt"
    r = tools.file_write(str(escape), "no\n")
    assert r["written"] is False and not escape.exists()
    assert "writable roots" in r["error"]


def test_symlink_out_of_the_workspace_is_refused(inst, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = ws.get_effective_workspace_dir() / "link"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, link)
    r = tools.file_write(str(link / "x.txt"), "no\n")
    assert r["written"] is False and not (outside / "x.txt").exists()


def test_dotdot_absolute_escape_is_refused(inst, tmp_path):
    sneaky = f"{ws.get_effective_workspace_dir()}/../config.yaml"
    assert tools.file_write(sneaky, "no\n")["written"] is False


def test_shell_and_file_tools_share_relative_paths(inst, allow_shell):
    from jaeger_agent.tools.code import run_shell

    tools.file_write("workspace/cap/report.py", "print('ran')\n")
    r = run_shell("python3 workspace/cap/report.py && pwd")
    assert r["ok"] is True, r
    out = r["stdout"].splitlines()
    assert out[0] == "ran"
    assert Path(out[1]).resolve() == inst.root.resolve()


def test_shell_writes_are_visible_to_file_tools_by_absolute_path(inst, allow_shell):
    from jaeger_agent.tools.code import run_shell

    r = run_shell("mkdir -p workspace/cap && echo 42 > workspace/cap/n.txt && echo $PWD/workspace/cap/n.txt")
    absolute = r["stdout"].strip()
    assert tools.file_read(absolute)["content"].strip() == "42"
    assert tools.edit_file(absolute, "42", "43").get("error") is None
    assert Path(absolute).read_text().strip() == "43"


def test_bound_project_is_the_only_absolute_write_root(inst, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    with ws.project_scope(project):
        assert tools.file_write(str(project / "a.txt"), "ok\n")["written"] is True
        ws_target = ws.get_effective_workspace_dir() / "b.txt"
        assert tools.file_write(str(ws_target), "no\n")["written"] is False
