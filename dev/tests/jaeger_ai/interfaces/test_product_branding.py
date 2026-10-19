"""Product-name boundaries for Jaeger AI's application surfaces."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[4]


def test_terminal_and_cli_product_copy_has_no_legacy_heading() -> None:
    paths = [
        "jaeger_ai/interfaces/tui/banner.py",
        "jaeger_ai/interfaces/tui/status.py",
        "jaeger_ai/interfaces/tui/slash_commands.py",
        "jaeger_ai/cli/devtools.py",
        "jaeger_ai/core/instance/setup_wizard.py",
        "jaeger",
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

    path = REPO / "jaeger_ai/interfaces/macos-shell/Resources/Info.plist"
    with path.open("rb") as stream:
        plist = plistlib.load(stream)
    assert plist["CFBundleIdentifier"] == "com.jenkinsrobotics.JaegerAI.uirebuild"
    assert plist["CFBundleIconFile"] == "AppIcon"
    assert plist["LSUIElement"] is True
    assert plist["NSSpeechRecognitionUsageDescription"]
    assert plist["NSMicrophoneUsageDescription"]
