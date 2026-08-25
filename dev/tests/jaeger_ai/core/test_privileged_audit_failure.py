"""Privileged processes must never launch without their audit record."""

from __future__ import annotations

from unittest.mock import patch


def _allow_privileged():
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        use_policy,
    )

    return use_policy(PermissionPolicy(confirmation=AllowAllProvider()))


def test_run_shell_fails_closed_before_process_launch(bindable_instance_root) -> None:
    from jaeger_agent.tools.code import run_shell
    from jaeger_agent.workspace import DefaultWorkspace, bind

    bind(DefaultWorkspace(bindable_instance_root).create())

    with _allow_privileged():
        with (
            patch("jaeger_agent.tools.code._audit", side_effect=OSError("disk full")),
            patch("jaeger_agent.tools.code.run_interruptible") as launch,
        ):
            result = run_shell("echo should-not-run")

    assert result["ok"] is False
    assert result["error"] == "audit log unavailable"
    launch.assert_not_called()


def test_ssh_exec_fails_closed_before_process_launch(bindable_instance_root) -> None:
    from jaeger_agent.tools.remote import ssh_exec
    from jaeger_agent.workspace import DefaultWorkspace, bind

    bind(DefaultWorkspace(bindable_instance_root).create())

    with _allow_privileged():
        with (
            patch("jaeger_agent.tools.remote._audit", side_effect=OSError("disk full")),
            patch("jaeger_agent.tools.remote.run_interruptible") as launch,
        ):
            result = ssh_exec("example.com", "echo should-not-run")

    assert result["ok"] is False
    assert result["error"] == "audit log unavailable"
    launch.assert_not_called()
