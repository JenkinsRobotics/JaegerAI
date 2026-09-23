"""JavaScript IDE client against owned product processes, no live provider."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dev.tests.jaeger_ai.core.test_gateway_owned_process_contract import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_ide_javascript_client_uses_owned_gateway(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for IDE client contract")
    owner = OwnedGateway(tmp_path)
    try:
        owner.start()
        # One real attachment fixture inside the owned instance's workspace
        # (the only place jaeger_ai/core/gateway/server.py::handle_add_attachment
        # accepts a path from), and one deliberately outside it, so the live
        # test can prove both a real upload and the real workspace-boundary
        # rejection — not a mocked stand-in for either.
        workspace = owner.root / "instances/contract/workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        inside = workspace / "ide-attachment.txt"
        inside.write_text("IDE attachment contract fixture", encoding="utf-8")
        outside = tmp_path / "outside-workspace.txt"
        outside.write_text("must be rejected", encoding="utf-8")
        source = Path(__file__).resolve().parents[4]
        result = subprocess.run(
            [node, "--test", str(source / "jaeger_ai/interfaces/ide/tests/client.test.js")],
            env={**os.environ, "JAEGER_IDE_TEST_URL": owner.url,
                 "JAEGER_IDE_TEST_ATTACHMENT_PATH": str(inside),
                 "JAEGER_IDE_TEST_ATTACHMENT_OUTSIDE_PATH": str(outside)},
            cwd=tmp_path, capture_output=True, text=True, timeout=75, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (tmp_path / "instances/contract/workspace/contract-output.txt").exists()
    finally:
        owner.stop()
