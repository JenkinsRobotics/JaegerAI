"""Product-name boundaries for Jaeger AI's application surfaces."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[4]


def test_native_app_uses_jaeger_ai_as_its_visible_product_name() -> None:
    splash = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/Splash/SplashWindow.swift").read_text()
    onboarding = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/Onboarding/OnboardingWindow.swift").read_text()
    settings = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/MenuCard/SettingsView.swift").read_text()
    transcript = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/ChatWindow/ChatTranscript.swift").read_text()
    controller = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/ChatWindow/ChatWindowController.swift").read_text()
    avatar = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/Avatar/AvatarWindows.swift").read_text()

    assert 'Text("JAEGER AI")' in splash
    assert 'Text("JENKINS ROBOTICS · OS 1 SETUP")' in onboarding
    assert 'Text("OS 1")' in onboarding
    assert 'Text("JAEGER OS")' not in splash + onboarding
    assert "local multimodal agent application" in transcript
    assert "real-world local agentic agent framework" not in transcript
    assert 'return "Jaeger AI"' in controller
    assert 'return "Jaeger"' not in controller
    assert 'return "Jaeger AI — ' in avatar
    assert 'return "Jaeger — ' not in avatar
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


def test_development_instance_is_product_specific() -> None:
    devtools = (REPO / "jaeger_ai/cli/devtools.py").read_text()
    assert 'INSTANCE_NAME = "jaeger-dev"' in devtools
    assert 'INSTANCE_NAME = "jros-dev"' not in devtools


def test_native_bundle_has_one_desktop_identity_and_device_descriptions():
    import plistlib

    path = REPO / "jaeger_ai/interfaces/swift/Resources/Info.plist"
    with path.open("rb") as stream:
        plist = plistlib.load(stream)
    assert plist["CFBundleIdentifier"] == "com.jenkinsrobotics.JaegerAI"
    assert plist["CFBundleIconFile"] == "AppIcon"
    assert plist["LSUIElement"] is False
    assert plist["NSCameraUsageDescription"]
    assert plist["NSMicrophoneUsageDescription"]
