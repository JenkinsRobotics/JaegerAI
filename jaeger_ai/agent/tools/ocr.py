"""OCR — one tool, ``ocr_file``, over the macOS Vision framework
(``VNRecognizeTextRequest``) via PyObjC. READ_ONLY.

Images: OCR'd directly. PDFs: each page is rendered to a bitmap via
Quartz (``CGPDFDocument``) then OCR'd the same way, joined with a page
marker.

Graceful when PyObjC isn't installed (dependency-visibility, 0.9.3
Task 5 machinery): returns ``{ok: False, available: False, error:
<remediation>}`` instead of an ImportError leaking up through the tool
dispatcher — same posture as ``vision.py``'s diffusers lazy dep.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.core.context import SandboxError, _resolve_read
from jaeger_ai.core.models.lazy_deps import FeatureUnavailable, ensure
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_RECOGNITION_LEVEL_ACCURATE = 1
_PDF_RENDER_SCALE = 2.0  # ~144 DPI (Quartz page space defaults to 72 DPI)


def _load_vision_modules():
    """Import the PyObjC Vision/Quartz/Foundation bridges, raising a
    clean RuntimeError with remediation if PyObjC isn't installed."""
    try:
        ensure("vision.ocr")
    except FeatureUnavailable as exc:
        raise RuntimeError(exc.remediation) from exc
    import Vision
    import Quartz
    from Foundation import NSURL
    return Vision, Quartz, NSURL


def _recognize_text_in_cg_image(Vision: Any, cg_image: Any) -> list[str]:
    """Run VNRecognizeTextRequest against one CGImage; return the
    top-candidate string per detected text observation."""
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(_RECOGNITION_LEVEL_ACCURATE)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision request failed: {error}")
    lines: list[str] = []
    for observation in (request.results() or []):
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()))
    return lines


def _cg_image_from_image_file(Quartz: Any, NSURL: Any, path: Path) -> Any:
    url = NSURL.fileURLWithPath_(str(path))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        return None
    return Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)


def _cg_images_from_pdf(Quartz: Any, NSURL: Any, path: Path) -> list[Any]:
    """Render every page of a PDF to a CGImage at _PDF_RENDER_SCALE."""
    url = NSURL.fileURLWithPath_(str(path))
    pdf_doc = Quartz.CGPDFDocumentCreateWithURL(url)
    if pdf_doc is None:
        return []
    page_count = Quartz.CGPDFDocumentGetNumberOfPages(pdf_doc)
    images = []
    for page_index in range(1, page_count + 1):
        page = Quartz.CGPDFDocumentGetPage(pdf_doc, page_index)
        if page is None:
            continue
        media_box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        width = max(1, int(media_box.size.width * _PDF_RENDER_SCALE))
        height = max(1, int(media_box.size.height * _PDF_RENDER_SCALE))
        color_space = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(
            None, width, height, 8, 0, color_space,
            Quartz.kCGImageAlphaPremultipliedLast,
        )
        if ctx is None:
            continue
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))
        Quartz.CGContextScaleCTM(ctx, _PDF_RENDER_SCALE, _PDF_RENDER_SCALE)
        Quartz.CGContextDrawPDFPage(ctx, page)
        cg_image = Quartz.CGBitmapContextCreateImage(ctx)
        if cg_image is not None:
            images.append(cg_image)
    return images


def ocr_file(path: str) -> dict[str, Any]:
    """Extract text from an image or PDF via the macOS Vision
    framework. `path` is read from ANYWHERE readable (same policy as
    read_file) — not sandboxed to skills/, since OCR targets are
    typically outside it (a spotlight_search hit, a Desktop
    screenshot). Returns {ok: True, text, pages: [str, ...], page_count}
    (one entry per PDF page, or a single entry for an image) or
    {ok: False, available: False, error} when PyObjC's Vision bridge
    isn't installed, {ok: False, error} for any other failure.
    """
    clean_path = (path or "").strip()
    if not clean_path:
        return {"ok": False, "error": "empty path"}
    if platform.system() != "Darwin":
        return {"ok": False,
                 "error": f"ocr_file is only available on macOS (got {platform.system()})"}
    try:
        target = _resolve_read(clean_path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.exists():
        return {"ok": False, "error": "file not found", "path": clean_path}
    if target.is_dir():
        return {"ok": False, "error": "is a directory", "path": clean_path}

    try:
        Vision, Quartz, NSURL = _load_vision_modules()
    except RuntimeError as exc:
        return {"ok": False, "available": False, "error": str(exc)}

    suffix = target.suffix.lower()
    try:
        if suffix == ".pdf":
            cg_images = _cg_images_from_pdf(Quartz, NSURL, target)
            if not cg_images:
                return {"ok": False, "error": "could not open PDF (corrupt or 0 pages)",
                         "path": clean_path}
            pages = [
                "\n".join(_recognize_text_in_cg_image(Vision, img))
                for img in cg_images
            ]
        else:
            cg_image = _cg_image_from_image_file(Quartz, NSURL, target)
            if cg_image is None:
                return {"ok": False, "error": "could not open image (unsupported format?)",
                         "path": clean_path}
            pages = ["\n".join(_recognize_text_in_cg_image(Vision, cg_image))]
    except Exception as exc:  # noqa: BLE001 — OCR must never crash the turn
        return {"ok": False, "error": f"OCR failed: {type(exc).__name__}: {exc}",
                 "path": clean_path}

    full_text = "\n\n".join(p for p in pages if p)
    return {"ok": True, "path": clean_path, "pages": pages, "page_count": len(pages),
             "text": full_text}


# ── Agent-facing tool wrapper ────────────────────────────────────────


@register_tool_from_function(name="ocr_file", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="ocr", operation="ocr_file",
               summary="extract text from an image or PDF")
def _t_ocr_file(path: str) -> dict:
    """Extract text from an image or PDF via the on-device Vision
    framework — the tool for "what does this screenshot say" / "read
    the text in this PDF" / "OCR this". `path` can be anywhere readable
    (pair with spotlight_search: find it, then OCR it). If PyObjC's
    Vision bridge isn't installed, this returns {available: False,
    error} with the pip install command — say so plainly rather than
    pretending you read the text. Returns {ok: True, text, pages,
    page_count} or {ok: False, error}."""
    return ocr_file(path=path)


__all__ = ["ocr_file"]
