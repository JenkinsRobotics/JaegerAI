"""Raster-only desktop identity checks; no agent or device is started."""

import sys
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from jaeger_ai.interfaces.pyside6 import branding


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_window_and_application_share_the_desktop_icon(app):
    window = QWidget()
    try:
        branding.apply_app_identity(window)
        assert app.applicationName() == "Jaeger AI"
        assert app.applicationDisplayName() == "Jaeger AI"
        assert app.desktopFileName() == branding.BUNDLE_ID
        assert not window.windowIcon().isNull()
        assert window.windowIcon().cacheKey() == app.windowIcon().cacheKey()
        icon = QImage(app.property("jaegerDesktopIcon"))
        assert (icon.width(), icon.height()) == (1024, 1024)
        assert icon.hasAlphaChannel()
        assert icon.pixelColor(0, 0).alpha() == 0
        assert icon.pixelColor(512, 512).alpha() == 255
    finally:
        window.close()


@pytest.mark.parametrize("helper", [False, True])
def test_native_helper_hides_only_its_duplicate_dock_entry(app, monkeypatch, helper):
    calls = []
    native = SimpleNamespace(
        setApplicationIconImage_=lambda icon: calls.append(("icon", icon)),
        setActivationPolicy_=lambda policy: calls.append(("policy", policy)),
    )
    image = SimpleNamespace(initByReferencingFile_=lambda path: path)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: native),
        NSImage=SimpleNamespace(alloc=lambda: image),
    ))
    monkeypatch.setattr(branding.sys, "platform", "darwin")
    monkeypatch.setattr(app, "platformName", lambda: "cocoa")
    monkeypatch.setenv("JAEGER_DESKTOP_HELPER", "1" if helper else "0")
    branding.apply_app_identity()
    assert calls[0][0] == "icon"
    assert (("policy", 1) in calls) is helper


def test_missing_desktop_asset_is_not_silently_a_black_icon(app, monkeypatch):
    monkeypatch.setattr(branding, "asset_path", lambda _: None)
    with pytest.raises(RuntimeError, match="desktop icon is missing"):
        branding.apply_app_identity()


@pytest.mark.parametrize("face", ["chat", "multimodal"])
def test_popup_renders_with_shared_icon_without_models_or_devices(app, monkeypatch, tmp_path, face):
    from jaeger_os.transport import InProcBus
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter

    bus = InProcBus()
    context = SimpleNamespace(bus=bus, agent_name="Jaeger AI", window=None,
                              core=SimpleNamespace(runtime=object()))
    if face == "multimodal":
        from jaeger_ai.interfaces.pyside6.multimodal.window import MultimodalWindow

        monkeypatch.setattr(MultimodalWindow, "_begin_camera_discovery", lambda self: None)
        monkeypatch.setattr(MultimodalWindow, "start_session", lambda self: None)
        monkeypatch.setattr(MultimodalWindow, "_toggle_camera", lambda self, enabled: None)
        window = MultimodalWindow(context, main_surface=True)
    else:
        from jaeger_ai.interfaces.pyside6.rich_tui.window import ChatWindow

        window = ChatWindow(context)
    try:
        window.show()
        app.processEvents()
        image = QImage(window.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            window.render(painter, QPoint())
        finally:
            painter.end()
        assert not image.isNull()
        assert window.windowIcon().cacheKey() == app.windowIcon().cacheKey()
        screenshot = tmp_path / f"{face}-software.png"
        assert image.save(str(screenshot))
        print(f"Software render: {screenshot}")
    finally:
        teardown = getattr(window, "teardown", None)
        if callable(teardown):
            teardown()
        window.close()
        bus.close()
