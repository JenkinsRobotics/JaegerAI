"""Regression guard for standalone JaegerAI ownership boundaries."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
APPROVED = {Path("jaeger_ai/core/instance/legacy_state.py")}


def test_runtime_sources_have_no_retired_brand_or_personal_defaults():
    roots = [ROOT / "jaeger_ai", ROOT / "clients", ROOT / "scripts"]
    forbidden = ("jros", ".jaeger_os", "/users/", "minecraft")
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".swift", ".sh", ".toml", ".yaml"} or not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if (
                relative in APPROVED
                or "Tests" in relative.parts
                or any(part.startswith(".") for part in relative.parts)
            ):
                continue
            source = path.read_text(encoding="utf-8").lower()
            for literal in forbidden:
                if literal in source:
                    findings.append(f"{relative}: {literal}")
    assert findings == [], "retired ownership literals must stay behind migration boundaries:\n" + "\n".join(findings)


# The ONE module allowed to resolve ARES's home. Everything else must go
# through it, so there is a single place to audit what crosses the boundary.
_ARES_INTEROP = Path("jaeger_ai/core/ares_interop.py")


def test_runtime_does_not_read_ares_private_session_state():
    """JaegerAI must not inspect ARES's private state.

    Private means session transcripts, the session store, the controller port
    and the HTTP API — the things that would make the two products impossible
    to version or run independently.

    It does NOT mean "never read anything ARES wrote". Cross-agent memory and
    MCP-server sync deliberately read artifacts ARES *publishes* for other
    agents. Those go through jaeger_ai/core/ares_interop.py, which declares
    each one explicitly; an undeclared path raises there rather than being
    resolved inline.

    The home-directory literal used to be banned outright, which made this
    fail on both of those legitimate integrations — and a guard that fails on
    correct code is one people learn to skip.
    """
    forbidden = (
        "ARES_SESSION_DIR",
        "ARES_CONTROLLER_PORT",
        '"/api/sessions"',
    )
    findings: list[str] = []
    for path in (ROOT / "jaeger_ai").rglob("*.py"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8")
        for literal in forbidden:
            if literal in source:
                findings.append(f"{relative}: {literal}")
        # Resolving ARES's home inline is its own violation: it bypasses the
        # declared-artifact list and reintroduces ungoverned crossings.
        if relative != _ARES_INTEROP and 'Path.home() / ".ares"' in source:
            findings.append(
                f"{relative}: resolves ARES home inline — use "
                "jaeger_ai.core.ares_interop.ares_shared_artifact()"
            )
    assert findings == [], (
        "Jaeger owns transcripts and must not inspect ARES private state:\n"
        + "\n".join(findings)
    )


def test_the_audited_crossing_declares_what_it_exposes():
    """ares_interop is only a safe boundary while it stays a closed list."""
    from jaeger_ai.core.ares_interop import ares_shared_artifact

    assert ares_shared_artifact("cross_agent_profile").name == "person.md"
    for private in ("sessions", "session_store", "transcripts", "api"):
        with pytest.raises(KeyError):
            ares_shared_artifact(private)
