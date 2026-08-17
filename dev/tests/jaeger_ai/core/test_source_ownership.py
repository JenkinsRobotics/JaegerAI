"""Regression guard for standalone JaegerAI ownership boundaries."""

from pathlib import Path


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


def test_runtime_does_not_read_ares_private_session_state():
    forbidden = (
        "ARES_SESSION_DIR",
        "ARES_CONTROLLER_PORT",
        'Path.home() / ".ares"',
        '"/api/sessions"',
    )
    findings: list[str] = []
    for path in (ROOT / "jaeger_ai").rglob("*.py"):
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for literal in forbidden:
            if literal in source:
                findings.append(f"{path.relative_to(ROOT)}: {literal}")
    assert findings == [], (
        "Jaeger owns transcripts and must not inspect ARES private state:\n"
        + "\n".join(findings)
    )
