from __future__ import annotations

from jaeger_mcp import (
    CachedToolEntry,
    MCPSchemaCache,
    MCPToolPolicy,
    ReconnectPolicy,
    agent_tool_name,
    build_mcp_seatbelt_profile,
    build_roots_payload,
    redact_secrets,
    wrap_stdio_with_seatbelt,
)


def test_policy_fail_closed_and_filtering():
    pol = MCPToolPolicy.from_dict({
        "include": ["get_*", "list_*", "push_*"],
        "exclude": ["push_force*"],
        "read_only": ["get_*", "list_*"],
        "max": 3,
        "gated": True,
    })
    assert pol.filter_tools(["get_a", "list_b", "push_c", "push_force_d", "delete_e"]) == ["get_a", "list_b", "push_c"]
    assert pol.is_read_only("get_a") is True
    assert pol.is_read_only("push_c") is False
    assert pol.is_strictly_read_only_catalog(["get_a", "list_b"]) is True
    assert pol.is_strictly_read_only_catalog(["get_a", "push_c"]) is False
    assert agent_tool_name("my.srv", "read/file") == "mcp__my_srv__read_file"


def test_redact_secrets_scrubs_nested_payloads():
    out = redact_secrets(
        {"text": "failed with ghp_secret12345", "nested": ["ok", ("tok=ghp_secret12345",)]},
        {"ghp_secret12345"},
    )
    assert "ghp_secret12345" not in str(out)
    assert "********" in out["text"]


def test_schema_cache_roundtrip_digest_and_ttl(tmp_path):
    cache = MCPSchemaCache(tmp_path / "cache.json", default_ttl_s=60.0)
    digest = cache.config_digest({"name": "gh", "command": "github-mcp", "args": [], "tools": {"gated": True}})
    cache.put(
        "gh",
        digest,
        [CachedToolEntry("gh", "get_me", "mcp__gh__get_me", "whoami", {"type": "object"}, True)],
        now=1000.0,
    )
    hit = cache.get("gh", expected_digest=digest, now=1010.0)
    assert hit is not None and len(hit) == 1 and hit[0].read_only is True
    assert cache.get("gh", expected_digest="different", now=1010.0) is None
    assert cache.get("gh", expected_digest=digest, now=1200.0) is None
    assert cache.invalidate("gh") is True


def test_seatbelt_profile_denies_sensitive_dirs(tmp_path):
    profile = build_mcp_seatbelt_profile(home_dir=tmp_path, allow_network=False)
    assert "(deny network*)" in profile
    assert f'{tmp_path.resolve()}/.ssh' in profile
    assert f'{tmp_path.resolve()}/.jaeger/secrets.env' in profile
    cmd, args, sandboxed = wrap_stdio_with_seatbelt("/usr/bin/true", ["--v"])
    assert isinstance(cmd, str) and isinstance(args, list) and isinstance(sandboxed, bool)


def test_roots_and_reconnect_policy(tmp_path):
    roots = build_roots_payload([tmp_path, tmp_path])
    assert len(roots) == 1 and roots[0]["uri"].startswith("file://")

    rp = ReconnectPolicy(max_attempts=2, base_delay_s=0.5, max_delay_s=4.0)
    assert rp.can_auto_reconnect("mutating", strictly_read_only=False) is False
    assert rp.can_auto_reconnect("github", strictly_read_only=True) is True
    assert rp.next_delay("github") == 0.5
    assert rp.next_delay("github") == 1.0
    assert rp.can_auto_reconnect("github", strictly_read_only=True) is False
    rp.record_success("github")
    assert rp.can_auto_reconnect("github", strictly_read_only=True) is True
