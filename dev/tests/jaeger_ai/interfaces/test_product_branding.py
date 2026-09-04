"""Product-name boundaries for Jaeger AI's application surfaces."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[4]


def test_native_app_uses_jaeger_ai_as_its_visible_product_name() -> None:
    splash = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerOS/Splash/SplashWindow.swift").read_text()
    onboarding = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerOS/Onboarding/OnboardingWindow.swift").read_text()
    settings = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerOS/MenuCard/SettingsView.swift").read_text()

    assert 'Text("JAEGER AI")' in splash
    assert 'Text("JAEGER AI SETUP")' in onboarding
    assert 'Text("Welcome to JAEGER AI")' in onboarding
    assert 'Text("JAEGER OS")' not in splash + onboarding
    assert "powered by JaegerAgent on JaegerOS" in settings


def test_terminal_and_cli_product_copy_has_no_legacy_heading() -> None:
    paths = [
        "jaeger_ai/interfaces/tui/banner.py",
        "jaeger_ai/interfaces/tui/status.py",
        "jaeger_ai/interfaces/tui/slash_commands.py",
        "jaeger_ai/cli/devtools.py",
        "jaeger_ai/core/instance/setup_wizard.py",
        "run.sh",
    ]
    copy = "\n".join((REPO / path).read_text() for path in paths)
    for legacy in (
        "JAEGER-OS",
        "Jaeger-OS",
        "JROS launcher",
        "Jaeger-OS · slash commands",
    ):
        assert legacy not in copy
    assert "Jaeger AI" in copy
