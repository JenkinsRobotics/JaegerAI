"""AI generation plugin — cloud image + video generation via fal.ai.

Ported from Hermes (``tools/image_generation_tool.py`` +
``plugins/video_gen/fal``). What was kept is the valuable core:

  • the fal queue REST pattern — submit to ``https://queue.fal.run/<model>``,
    poll ``status_url`` until COMPLETED, fetch ``response_url``
  • model selection with a sensible cheap/fast default per modality
    (FLUX schnell for images, Pixverse v6 for video)
  • the friendly "not configured" error instead of a crash

What was dropped as Hermes-specific plumbing: the ``fal_client`` SDK
dependency (plain ``requests`` speaks the queue API directly), the managed
Nous gateway / subscription billing path, the Clarity-upscaler chain, and
config.yaml model persistence (the agent passes ``model=`` per call).

These tools are the PAID CLOUD counterpart to the local
``image_generate`` tool (``jaeger_os/agent/tools/vision.py``, SDXL-Turbo
on-device): higher quality, needs the ``FAL_KEY`` credential, costs cents
per generation. Outputs land under ``<instance>/skills/`` exactly like
the local tool's.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.context import SandboxError, _require_layout, _resolve_under
from jaeger_os.core.runtime.tool_interrupt import is_interrupted
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

FAL_QUEUE_ORIGIN = "https://queue.fal.run"

# Cheap + fast defaults (both well under a cent per generation on fal):
#   images — FLUX.1 [schnell], ~1-2 s
#   video  — Pixverse v6 text-to-video, ~30-90 s
DEFAULT_IMAGE_MODEL = "fal-ai/flux/schnell"
DEFAULT_VIDEO_MODEL = "fal-ai/pixverse/v6/text-to-video"

# Hard walls so a wedged queue job can't hang a turn forever.
IMAGE_TIMEOUT_S = 120.0
VIDEO_TIMEOUT_S = 300.0
POLL_INTERVAL_S = 2.0

# Model ids the agent passes without a vendor prefix ("flux/schnell")
# get "fal-ai/" prepended; ids already carrying a known vendor pass through.
_KNOWN_VENDORS = ("fal-ai/", "bytedance/", "alibaba/")

_SETUP_HELP = (
    "fal.ai is not configured — no FAL_KEY found. To set it up: "
    "get an API key at https://fal.ai/dashboard/keys, then store it with "
    "set_credential('FAL_KEY', '<your-key>') (or export FAL_KEY in the "
    "environment) and retry. For local/offline generation that needs no "
    "key, use the image_generate tool instead."
)


# ── credentials ──────────────────────────────────────────────────────

def _fal_key() -> str:
    """Resolve the fal.ai API key: instance credential store first
    (``FAL_KEY``, then legacy-lowercase ``fal_key``), env fallback of the
    same names. Returns ``""`` when unconfigured — never raises."""
    layout = None
    try:
        from jaeger_os.core.context import get_layout
        layout = get_layout()
    except Exception:  # noqa: BLE001 — no instance bound yet
        layout = None
    from jaeger_os.plugins import plugin_credential
    for name in ("FAL_KEY", "fal_key"):
        try:
            key = plugin_credential(layout, name)
        except Exception:  # noqa: BLE001 — garbled store entry → keep trying
            key = ""
        if key:
            return key
    return ""


# ── HTTP seams (thin, monkeypatchable in tests) ──────────────────────

def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


def _http_post(url: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    import requests
    resp = requests.post(url, json=payload, headers=_headers(key), timeout=30.0)
    _raise_readable(resp)
    return resp.json()


def _http_get(url: str, key: str) -> dict[str, Any]:
    import requests
    resp = requests.get(url, headers=_headers(key), timeout=30.0)
    _raise_readable(resp)
    return resp.json()


def _http_download(url: str, target: Path) -> None:
    """Stream a generated media URL (pre-signed CDN link) to ``target``."""
    import requests
    with requests.get(url, stream=True, timeout=120.0) as resp:
        resp.raise_for_status()
        with open(target, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)


def _raise_readable(resp: Any) -> None:
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"fal.ai rejected the API key (HTTP {resp.status_code}) — "
            f"check the FAL_KEY credential"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"fal.ai HTTP {resp.status_code}: {resp.text[:300]}")


# ── queue + poll core ────────────────────────────────────────────────

def _normalize_model(model: str, default: str) -> str:
    m = (model or "").strip().strip("/")
    if not m:
        return default
    if m.startswith(_KNOWN_VENDORS):
        return m
    return f"fal-ai/{m}"


def _queue_generate(model: str, payload: dict[str, Any], key: str,
                    timeout_s: float) -> dict[str, Any]:
    """Submit to the fal queue and poll until the job completes.

    Raises TimeoutError past ``timeout_s``, RuntimeError on a FAILED
    status, an interrupt, or an HTTP error."""
    submitted = _http_post(f"{FAL_QUEUE_ORIGIN}/{model}", payload, key)
    request_id = submitted.get("request_id", "")
    status_url = submitted.get("status_url") or (
        f"{FAL_QUEUE_ORIGIN}/{model}/requests/{request_id}/status")
    response_url = submitted.get("response_url") or (
        f"{FAL_QUEUE_ORIGIN}/{model}/requests/{request_id}")

    deadline = time.monotonic() + timeout_s
    while True:
        status = _http_get(status_url, key)
        state = str(status.get("status", "")).upper()
        if state == "COMPLETED":
            return _http_get(response_url, key)
        if state in ("FAILED", "ERROR", "CANCELLED"):
            detail = status.get("error") or status.get("detail") or state
            raise RuntimeError(f"fal.ai job {state.lower()}: {detail}")
        if is_interrupted():
            raise RuntimeError("interrupted by the user")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"fal.ai request timed out after {int(timeout_s)}s "
                f"(last status: {state or 'unknown'})"
            )
        time.sleep(POLL_INTERVAL_S)


def _first_image_url(result: dict[str, Any]) -> str:
    imgs = result.get("images")
    if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
        return str(imgs[0].get("url", ""))
    img = result.get("image")
    if isinstance(img, dict):
        return str(img.get("url", ""))
    return ""


def _video_url(result: dict[str, Any]) -> str:
    vid = result.get("video")
    if isinstance(vid, dict):
        return str(vid.get("url", ""))
    vids = result.get("videos")
    if isinstance(vids, list) and vids and isinstance(vids[0], dict):
        return str(vids[0].get("url", ""))
    return ""


# ── shared tool implementation ───────────────────────────────────────

def _generate(kind: str, prompt: str, model: str, output_path: str) -> dict[str, Any]:
    clean = (prompt or "").strip()
    if not clean:
        return {"ok": False, "error": "empty prompt"}

    key = _fal_key()
    if not key:
        return {"ok": False, "error": _SETUP_HELP}

    if kind == "image":
        model_id = _normalize_model(model, DEFAULT_IMAGE_MODEL)
        timeout_s, default_ext = IMAGE_TIMEOUT_S, ".png"
    else:
        model_id = _normalize_model(model, DEFAULT_VIDEO_MODEL)
        timeout_s, default_ext = VIDEO_TIMEOUT_S, ".mp4"

    try:
        layout = _require_layout()
    except Exception as exc:  # noqa: BLE001 — no instance bound
        return {"ok": False, "error": str(exc)}
    name = (output_path or "").strip() or time.strftime(
        f"fal_{kind}_%Y%m%d_%H%M%S{default_ext}")
    try:
        target = _resolve_under(layout.skills_dir, name)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}

    started = time.perf_counter()
    try:
        result = _queue_generate(model_id, {"prompt": clean}, key, timeout_s)
        url = _first_image_url(result) if kind == "image" else _video_url(result)
        if not url:
            return {"ok": False, "model": model_id,
                    "error": f"fal.ai returned no {kind} URL in its response"}
        target.parent.mkdir(parents=True, exist_ok=True)
        _http_download(url, target)
    except Exception as exc:  # noqa: BLE001 — tools return, never raise
        return {"ok": False, "model": model_id,
                "error": f"fal.ai {kind} generation failed: {exc}"}

    return {
        "ok": True,
        "generated": True,
        "path": str(target.relative_to(layout.root)),
        "absolute_path": str(target),
        "model": model_id,
        "url": url,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }


# ── plain callables (importable + unit-testable, like vision.py's) ───

def generate_image_fal(prompt: str, model: str = "flux/schnell",
                       output_path: str = "") -> dict[str, Any]:
    """Implementation behind the ``generate_image_fal`` tool."""
    return _generate("image", prompt, model, output_path)


def generate_video_fal(prompt: str, model: str = "",
                       output_path: str = "") -> dict[str, Any]:
    """Implementation behind the ``generate_video_fal`` tool."""
    return _generate("video", prompt, model, output_path)


# ── agent-tool wrappers ──────────────────────────────────────────────

@register_tool_from_function(name="generate_image_fal")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="ai_gen",
               operation="generate_image_fal",
               summary="generate an image via fal.ai (cloud, paid) into the skills workspace")
def _t_generate_image_fal(prompt: str, model: str = "flux/schnell",
                          output_path: str = "") -> dict:
    """Generate a high-quality image from a text prompt via fal.ai
    (cloud, paid — needs the FAL_KEY credential). Saves a PNG under
    skills/ and returns its path. model examples: "flux/schnell"
    (default — fast + cheap), "flux/dev" (higher quality),
    "flux-pro/v1.1" (best). ~10-60s. For free local/offline generation
    use image_generate instead."""
    return generate_image_fal(prompt=prompt, model=model, output_path=output_path)


@register_tool_from_function(name="generate_video_fal")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="ai_gen",
               operation="generate_video_fal",
               summary="generate a short video via fal.ai (cloud, paid) into the skills workspace")
def _t_generate_video_fal(prompt: str, model: str = "",
                          output_path: str = "") -> dict:
    """Generate a short AI video clip from a text prompt via fal.ai
    (cloud, paid — needs the FAL_KEY credential). Saves an MP4 under
    skills/ and returns its path. model="" uses Pixverse v6 (cheap);
    premium alternates: "veo3.1", "kling-video/v3/4k/text-to-video".
    Expect 1-5 minutes. There is no local video backend — for images
    only, image_generate (local) or generate_image_fal (cloud)."""
    return generate_video_fal(prompt=prompt, model=model, output_path=output_path)


__all__ = [
    "DEFAULT_IMAGE_MODEL",
    "DEFAULT_VIDEO_MODEL",
    "generate_image_fal",
    "generate_video_fal",
]
