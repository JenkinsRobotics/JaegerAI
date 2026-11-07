"""Host injection preserves canonical authority and repair implementations."""
import pytest

from jaeger_agent.core import host


def test_missing_service_fails_at_the_feature_boundary():
    with pytest.raises(ImportError, match="not bound"):
        host.service("unbound-test-service")


def test_product_binds_authority_and_repair_without_alternate_implementations():
    from jaeger_ai.core.agent_host import bind_agent_host
    from jaeger_ai.core.entity import authority
    from jaeger_ai.core.runtime import tool_repair

    bind_agent_host()
    assert host.service("authority") is authority
    assert host.service("tool_repair") is tool_repair
    assert host.service("tool_repair").safe_parse_tool_arguments("{'count': 3}") == {"count": 3}
