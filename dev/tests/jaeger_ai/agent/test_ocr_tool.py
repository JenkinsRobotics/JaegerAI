"""ocr.py (agent/tools/ocr.py) — 0.9.3 mac-native suite.

No real PyObjC/Vision call: ``_load_vision_modules`` and the CGImage
helpers are monkeypatched with fakes. The "PyObjC not installed" path
is exercised for real (this dev venv has no Vision framework — that IS
the graceful-degradation path 0.9.3 Task 5 cares about).
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent.tools import ocr
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


@pytest.fixture(autouse=True)
def _darwin(monkeypatch):
    monkeypatch.setattr(ocr.platform, "system", lambda: "Darwin")


def test_ocr_file_requires_path():
    result = ocr.ocr_file("")
    assert result["ok"] is False
    assert "empty path" in result["error"]


def test_ocr_file_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(ocr.platform, "system", lambda: "Linux")
    result = ocr.ocr_file("/tmp/x.png")
    assert result["ok"] is False
    assert "macOS" in result["error"]


def test_ocr_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: tmp_path / "missing.png")
    result = ocr.ocr_file(str(tmp_path / "missing.png"))
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_ocr_file_rejects_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: tmp_path)
    result = ocr.ocr_file(str(tmp_path))
    assert result["ok"] is False
    assert "directory" in result["error"]


def test_ocr_file_reports_unavailable_when_pyobjc_missing(monkeypatch, tmp_path):
    """Real path in this dev venv — PyObjC's Vision bridge isn't
    installed, so ensure() genuinely raises FeatureUnavailable. This is
    the dependency-visibility contract: a clean, actionable message,
    never a raw ImportError."""
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: img)

    result = ocr.ocr_file(str(img))
    assert result["ok"] is False
    assert result["available"] is False
    assert "pip install" in result["error"]
    assert "Vision" in result["error"]


def test_ocr_file_image_success(monkeypatch, tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: img)

    fake_vision, fake_quartz, fake_nsurl = object(), object(), object()
    monkeypatch.setattr(ocr, "_load_vision_modules",
                        lambda: (fake_vision, fake_quartz, fake_nsurl))
    monkeypatch.setattr(ocr, "_cg_image_from_image_file",
                        lambda Q, N, path: "fake-cg-image")
    monkeypatch.setattr(ocr, "_recognize_text_in_cg_image",
                        lambda V, cg: ["Hello world", "second line"])

    result = ocr.ocr_file(str(img))
    assert result["ok"] is True
    assert result["page_count"] == 1
    assert result["text"] == "Hello world\nsecond line"


def test_ocr_file_image_open_failure(monkeypatch, tmp_path):
    img = tmp_path / "shot.heic"
    img.write_bytes(b"\x00\x01")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: img)
    monkeypatch.setattr(ocr, "_load_vision_modules", lambda: (object(), object(), object()))
    monkeypatch.setattr(ocr, "_cg_image_from_image_file", lambda Q, N, path: None)

    result = ocr.ocr_file(str(img))
    assert result["ok"] is False
    assert "could not open image" in result["error"]


def test_ocr_file_pdf_multi_page(monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: pdf)
    monkeypatch.setattr(ocr, "_load_vision_modules", lambda: (object(), object(), object()))
    monkeypatch.setattr(ocr, "_cg_images_from_pdf",
                        lambda Q, N, path: ["page1-img", "page2-img"])

    calls = []

    def fake_recognize(V, cg):
        calls.append(cg)
        return [f"text for {cg}"]

    monkeypatch.setattr(ocr, "_recognize_text_in_cg_image", fake_recognize)

    result = ocr.ocr_file(str(pdf))
    assert result["ok"] is True
    assert result["page_count"] == 2
    assert calls == ["page1-img", "page2-img"]
    assert "text for page1-img" in result["text"]
    assert "text for page2-img" in result["text"]


def test_ocr_file_pdf_open_failure(monkeypatch, tmp_path):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"not a pdf")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: pdf)
    monkeypatch.setattr(ocr, "_load_vision_modules", lambda: (object(), object(), object()))
    monkeypatch.setattr(ocr, "_cg_images_from_pdf", lambda Q, N, path: [])

    result = ocr.ocr_file(str(pdf))
    assert result["ok"] is False
    assert "could not open PDF" in result["error"]


def test_ocr_file_recognition_exception_never_raises(monkeypatch, tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(ocr, "_resolve_read", lambda p: img)
    monkeypatch.setattr(ocr, "_load_vision_modules", lambda: (object(), object(), object()))
    monkeypatch.setattr(ocr, "_cg_image_from_image_file", lambda Q, N, path: "cg")

    def boom(V, cg):
        raise RuntimeError("vision request failed")

    monkeypatch.setattr(ocr, "_recognize_text_in_cg_image", boom)
    result = ocr.ocr_file(str(img))
    assert result["ok"] is False
    assert "OCR failed" in result["error"]


def test_ocr_file_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "ocr_file" in tools
    assert get_tier(tools["ocr_file"]) == PermissionTier.READ_ONLY
