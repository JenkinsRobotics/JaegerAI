"""geminidesktop is a dedicated local MCP client caller, scoped like the other apps."""
from jaeger_ai.core.gateway.caller_auth import APP_CALLER_SCOPES, APP_CALLERS, CALLERS
from jaeger_ai.interfaces.mcp_server import MCP_INBOUND_CALLERS


def test_geminidesktop_is_app_caller():
    assert "geminidesktop" in APP_CALLERS
    spec = CALLERS["geminidesktop"]
    assert spec.actor == "mcp:geminidesktop"
    assert spec.session_prefix == "geminidesktop:"
    assert spec.scopes == APP_CALLER_SCOPES == CALLERS["gemini"].scopes


def test_geminidesktop_distinct_from_gemini_and_inbound():
    assert CALLERS["geminidesktop"] is not CALLERS["gemini"]
    assert "geminidesktop" in MCP_INBOUND_CALLERS
    assert not {"approve", "delegate", "stop", "admin"} & CALLERS["geminidesktop"].scopes
