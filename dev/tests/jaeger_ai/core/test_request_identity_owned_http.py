"""Session-bound replay through authenticated HTTP and an owned Gateway child."""

import json
from urllib.error import HTTPError

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from jaeger_ai.core.instance.schemas import Config, SkillsConfig, load_yaml

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_owned_http_replay_cannot_create_or_activate_foreign_session(tmp_path):
    gateway = OwnedGateway(tmp_path)
    try:
        gateway.start()
        # Explicit synthetic-fixture boundary, not a change to production defaults.
        config = load_yaml(tmp_path / "instances" / "contract" / "config.yaml", Config)
        assert config.skills.run_smoke_tests is False
        assert SkillsConfig().run_smoke_tests is True
        gateway.request("/v1/sessions", {"session_id": "original", "profile": "jaeger"})
        body = {"text": "Say CONTRACT-ANSWER", "request_id": "session-bound-http"}
        gateway.request("/v1/sessions/original/turns", body)
        assert (
            gateway.wait_for_terminal("original", body["request_id"])["status"]
            == "completed"
        )
        status, replay = gateway.request("/v1/sessions/original/turns", body)
        assert (
            status == 200
            and replay["replayed"]
            and replay["output"] == "CONTRACT-ANSWER"
        )
        # Store reads below are HTTP requests against this owned process only.
        _, before = gateway.request("/v1/operator/session-state")
        for caller, destination in [("cli", "foreign"), ("mcp", "mcp:foreign")]:
            with pytest.raises(HTTPError) as denied:
                gateway.request(
                    f"/v1/sessions/{destination}/turns", body, caller=caller
                )
            assert denied.value.code == 409
            payload = json.load(denied.value)
            assert "original" not in str(payload) and "CONTRACT-ANSWER" not in str(
                payload
            )
            with pytest.raises(HTTPError) as missing:
                gateway.request(f"/v1/sessions/{destination}")
            assert missing.value.code == 404
            assert gateway.request("/v1/operator/session-state")[1] == before
    finally:
        gateway.stop()
