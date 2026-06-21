"""run_python executes in the skills/ workspace.

Regression test for the bug that made the agent unable to do code
tasks: write_file wrote into skills/, but run_python ran in a throwaway
tempdir — so generated code could never see the file it had just
written. "Write a file then run it" was structurally impossible, and
the agent spun 12-16 tool calls hunting for its own file.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent import tools
from jaeger_os.core.instance.instance import InstanceLayout


@pytest.fixture()
def bound_instance(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


def test_run_python_sees_a_file_write_file_created(bound_instance):
    # The exact failing workflow: write a file, then run code that imports it.
    tools.file_write("greeting.py", "MESSAGE = 'hi from the workspace'\n")
    result = tools.run_python("import greeting; print(greeting.MESSAGE)")
    assert result["ok"] is True, result
    assert "hi from the workspace" in result["stdout"]


def test_run_python_can_exec_a_written_script(bound_instance):
    tools.file_write("fib.py", "print(sum([0, 1, 1, 2, 3, 5, 8, 13, 21, 34]))\n")
    result = tools.run_python("exec(open('fib.py').read())")
    assert result["ok"] is True, result
    assert "88" in result["stdout"]


def test_run_python_still_works_with_no_file(bound_instance):
    # The plain "just run this snippet" path must keep working.
    result = tools.run_python("print(2 + 2)")
    assert result["ok"] is True, result
    assert "4" in result["stdout"]
