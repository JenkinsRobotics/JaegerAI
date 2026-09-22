"""A permission request must say what this particular call will touch.

Before, ``requires_tier`` passed a fixed template, so a phone approval read
"write a file in the skills workspace" whatever path the agent had chosen.
"""
from __future__ import annotations

from jaeger_os.core.safety.permissions import (
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    PolicyMode,
    requires_tier,
    use_policy,
)


class _Recorder:
    def __init__(self) -> None:
        self.seen: list[PermissionRequest] = []

    def confirm(self, request: PermissionRequest) -> bool:
        self.seen.append(request)
        return True


@requires_tier(PermissionTier.WRITE_LOCAL, skill="files", operation="write_file",
               summary="write a file")
def _write(path: str, content: str) -> str:
    return path


def test_call_arguments_reach_the_confirmation_provider():
    recorder = _Recorder()
    with use_policy(PermissionPolicy(mode=PolicyMode.NORMAL, confirmation=recorder)):
        assert _write("workspace/a.txt", content="hi") == "workspace/a.txt"

    [request] = recorder.seen
    assert request.arguments == {"path": "workspace/a.txt", "content": "hi"}
    assert request.summary == "write a file"


def test_introspected_template_carries_no_call_arguments():
    template = _write.__lilith_permission__
    assert template.arguments == {}
