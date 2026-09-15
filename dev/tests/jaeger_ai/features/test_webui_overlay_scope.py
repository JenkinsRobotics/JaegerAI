"""The WebUI overlay may brand the stock app — never reimplement it.

JaegerAI runs a vendored, unmodified Hermes WebUI and reaches its other
backends through that app's OWN profile configuration plus a loopback adapter.
The overlay (`jaeger_ai/assets/jaeger_webui_branding.js`) exists only for what
stock cannot do: icons, the window title, and hiding Hermes chrome Jaeger does
not back.

It broke that rule once. An AGENTS roster grew in the overlay listing the four
frameworks and switching between them — duplicating the profile switcher the
stock composer already ships. Two controls for one job meant the sidebar, the
composer chip and the turn label could each name a different agent, and the
operator could not tell which one a message would reach.

These tests keep the overlay inside its scope, because every line in it is a
future merge conflict when hermes-webui is pulled.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[4]
OVERLAY = REPO / "jaeger_ai" / "assets" / "jaeger_webui_branding.js"


@pytest.fixture(scope="module")
def overlay() -> str:
    return OVERLAY.read_text(encoding="utf-8")


#: Stock WebUI features the overlay must not rebuild. Each maps to an endpoint
#: or control the vendored app already provides.
FORBIDDEN = {
    "installAgentsSection": "the stock composer has a profile switcher",
    "activateAgent": "POST /api/profile/switch is stock",
    "renderAgents": "the stock sidebar renders the session library",
    "loadAgentsCatalog": "stock owns the agent/profile list",
    "loadSessionCounts": "the stock sidebar already splits WebUI vs CLI sessions",
    "sessionBadge": "session counts are a stock sidebar feature",
    "switchToProfile(": "profile switching belongs to the stock composer chip",
}


@pytest.mark.parametrize(("symbol", "why"), sorted(FORBIDDEN.items()))
def test_overlay_does_not_reimplement_stock(overlay: str, symbol: str, why: str) -> None:
    assert symbol not in overlay, (
        f"{symbol} is back in the WebUI overlay — {why}.\n"
        f"The overlay may only brand the stock app and hide chrome Jaeger does "
        f"not back. Anything that duplicates a stock control makes two sources "
        f"of truth for one decision, and makes upstream pulls conflict."
    )


def test_overlay_never_writes_the_composer_placeholder(overlay: str) -> None:
    """Who you are talking to is the composer's business, not branding's.

    Stock derives the placeholder from the active profile through
    ``assistantDisplayName()`` — the same function that labels the profile
    chip — so the two always agree on their own. The overlay set it to a fixed
    "Message Jaeger…" in two places, one of them a MutationObserver keyed on
    /Hermes/. Because "Hermes Agent" is a real profile name, selecting it made
    the observer rewrite the field continuously: the chip said Hermes Agent and
    the composer said Jaeger.
    """
    code = "\n".join(
        line for line in overlay.splitlines()
        if not line.lstrip().startswith("//")
    )
    assert "placeholder" not in code, (
        "the overlay writes the composer placeholder again. Stock already "
        "derives it from the active profile; setting it here makes the chip "
        "and the placeholder name different agents."
    )


def test_overlay_still_does_its_actual_job(overlay: str) -> None:
    """Guard against over-correcting: branding must survive the diet."""
    for kept in ("installJaegerIcons", "installJaegerSurfaceLabels",
                 "hideTodosSurfaces", "hideHermesDashboardChrome"):
        assert kept in overlay, f"{kept} was removed; that IS the overlay's job"


def test_overlay_stays_small(overlay: str) -> None:
    """A size ceiling is a blunt proxy for scope, and a deliberate one.

    It went to 949 lines while growing a roster. At ~600 it is branding plus
    approvals. If this fails, the question to ask is not "raise the limit" but
    "should stock be doing this instead".
    """
    lines = len(overlay.splitlines())
    assert lines < 700, (
        f"overlay is {lines} lines. It is branding, not an application — "
        f"check what was added and whether the stock WebUI already does it."
    )


def test_the_scope_rule_is_written_where_an_editor_will_see_it(overlay: str) -> None:
    head = overlay[:1600].lower()
    assert "never reimplement a stock feature" in head or "scope rule" in head, (
        "the overlay's header must state its scope rule — it is the only thing "
        "standing between a small branding file and a second WebUI"
    )
