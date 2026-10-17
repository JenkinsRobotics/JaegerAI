"""Vision skills — Jaeger-native local vision + local image generator.

  • look_at(image_path, question)       — active llama.cpp + mmproj brain
  • generate_image(prompt, out_path)    — SDXL-Turbo (lazy MPS load)

The local vision projector is configured by Jaeger; the image generator can
be overridden with IMAGE_GEN_MODEL_ID.

Ported from pydantic_ai/skills/vision.py. The only Jaeger-specific
adjustment is sandbox: paths must resolve inside <instance>/skills/.
"""

from __future__ import annotations

import os
import threading as _threading
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import SandboxError, _require_layout, _resolve_read, _resolve_under
from jaeger_agent.util.tool_interrupt import is_interrupted
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


# ---------------------------------------------------------------------------
# Image generation (SDXL-Turbo on MPS)
# ---------------------------------------------------------------------------
_imagegen_state: dict[str, Any] = {"pipeline": None, "model_id": None}
# Atomic load/swap for the shared pipeline — multi-instance agents
# (delegate sub-agents, deep think) can dispatch concurrently, and a
# racing reload mid-inference corrupts results silently.
_imagegen_lock = _threading.Lock()


def _ensure_imagegen_pipeline() -> tuple[Any, str]:
    model_id = os.environ.get("IMAGE_GEN_MODEL_ID", "stabilityai/sdxl-turbo")
    with _imagegen_lock:
        return _ensure_imagegen_pipeline_locked(model_id)


def _ensure_imagegen_pipeline_locked(model_id: str) -> tuple[Any, str]:
    if _imagegen_state["pipeline"] is not None and _imagegen_state["model_id"] == model_id:
        return _imagegen_state["pipeline"], model_id

    # Optional backend — ensure() gives a clean, actionable error (and
    # an opt-in auto-install) instead of a raw ImportError.
    from jaeger_agent.util.lazy_deps import FeatureUnavailable, ensure
    try:
        ensure("image.diffusers")
    except FeatureUnavailable as exc:
        raise RuntimeError(exc.remediation) from exc
    from diffusers import AutoPipelineForText2Image
    import torch

    started = time.perf_counter()
    device = "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device != "cpu" else torch.float32
    pipe = AutoPipelineForText2Image.from_pretrained(
        model_id, torch_dtype=dtype, variant="fp16" if dtype == torch.float16 else None
    ).to(device)
    print(f"[image_gen] {model_id} loaded on {device} in {time.perf_counter() - started:.1f}s", flush=True)
    _imagegen_state["pipeline"] = pipe
    _imagegen_state["model_id"] = model_id
    return pipe, model_id


def generate_image(
    prompt: str,
    out_path: str = "generated.png",
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate an image from a text prompt and save to <instance>/skills/.

    SDXL-Turbo at 1-step is the default — fast on Apple Silicon.
    First call downloads ~6 GB of weights from HF; subsequent calls are
    ~1–3 s per image. out_path is sandbox-resolved under skills/.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"generated": False, "error": "empty prompt"}
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, out_path)
    except SandboxError as exc:
        return {"generated": False, "error": str(exc)}

    try:
        pipe, model_id = _ensure_imagegen_pipeline()
    except Exception as exc:
        return {"generated": False, "error": str(exc)}

    try:
        import torch
        gen = torch.Generator(device=pipe.device).manual_seed(seed) if seed is not None else None
        started = time.perf_counter()
        result = pipe(
            prompt=clean_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=gen,
        )
        elapsed = time.perf_counter() - started
        image = result.images[0]
    except Exception as exc:
        return {"generated": False, "error": f"inference failed: {exc}"}

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return {
        "generated": True,
        "path": str(target.relative_to(layout.root)),
        "absolute_path": str(target),
        "model_id": model_id,
        "elapsed_s": round(elapsed, 3),
        "prompt": clean_prompt,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# look_at — Jaeger-native llama.cpp + mmproj vision
# ---------------------------------------------------------------------------
_vision_state: dict[str, Any] = {"node": None, "handler": None, "model_path": None}
_vision_lock = _threading.Lock()


def _ensure_native_vision() -> tuple[Any, Any]:
    """Return the active local client and its Jaeger-owned vision handler.

    The agent loop already owns the GGUF.  Vision must use that same model
    and the configured llama.cpp projector; loading a second Transformers
    VLM here was the source of the CPU/MPS failure and split Jaeger's brain.
    """
    from jaeger_ai.main import _pipeline

    client = _pipeline.get("client")
    llm = getattr(client, "llm", None)
    if client is None or llm is None or not hasattr(client, "chat"):
        raise RuntimeError("native Jaeger vision requires an active local llama.cpp brain")

    handler = getattr(llm, "chat_handler", None)
    if handler is not None:
        return client, handler

    config = _pipeline.get("config")
    model_path = getattr(getattr(config, "multimodal", None), "vision_mmproj_path", "")
    if not model_path:
        raise RuntimeError("no vision_mmproj_path is configured")

    with _vision_lock:
        handler = getattr(llm, "chat_handler", None)
        if handler is None:
            node = _vision_state.get("node")
            if node is None or _vision_state.get("model_path") != model_path:
                from jaeger_agent.core.engine import vis_mod
                node = vis_mod.VisionMmproj()
                handler = node.load(True, model_path=model_path)
                if handler is None:
                    raise RuntimeError(f"vision projector unavailable: {model_path}")
                _vision_state.update(node=node, handler=handler, model_path=model_path)
            else:
                handler = _vision_state["handler"]
            llm.chat_handler = handler
        return client, handler


def warm_vision() -> dict[str, Any]:
    """Ensure Jaeger's configured local projector is attached."""
    _, handler = _ensure_native_vision()
    return {"warmed": True, "backend": "llama.cpp", "handler": type(handler).__name__}


def look_at(image_path: str, question: str = "Describe this image in one short sentence.") -> dict[str, Any]:
    """Look at an image file under <instance>/skills/ and answer a question.

    Path is sandbox-resolved under the instance's skills/ dir.
    Uses the active local llama.cpp model and configured Gemma mmproj. The
    completion runs on Jaeger's auxiliary context, keeping the agent turn's
    worker context and KV cache intact.
    """
    clean_path = (image_path or "").strip()
    if not clean_path:
        return {"saw": False, "error": "empty image path"}
    layout = _require_layout()
    try:
        target = _resolve_read(clean_path)
    except SandboxError as exc:
        return {"saw": False, "error": str(exc)}
    if not target.exists():
        return {"saw": False, "error": "image not found", "path": clean_path}

    # The VLM load + inference below are single blocking calls that cannot
    # be interrupted partway. Bail before starting if the turn was already
    # cancelled so we don't kick off a multi-second model load nobody is
    # waiting on.
    if is_interrupted():
        return {"saw": False, "interrupted": True,
                "error": "look_at interrupted by user"}

    q = (question or "Describe this image in one short sentence.").strip()
    try:
        import base64
        import mimetypes
        from jaeger_agent.core.engine import vis_mod

        client, _handler = _ensure_native_vision()
        mime = mimetypes.guess_type(target.name)[0] or "image/png"
        image_uri = f"data:{mime};base64,{base64.b64encode(target.read_bytes()).decode('ascii')}"
        messages = [{
            "role": "user",
            "content": vis_mod.VisionMmproj.content(q, image_uri),
        }]
    except Exception as exc:
        return {"saw": False, "error": f"native vision setup failed: {exc}"}

    started = time.perf_counter()
    try:
        result = client.chat(messages, max_tokens=256, temperature=0.0)
        answer = getattr(result, "text", "") or ""
    except Exception as exc:
        return {"saw": False, "error": f"native vision inference failed: {exc}"}
    elapsed = time.perf_counter() - started

    return {
        "saw": True,
        "answer": str(answer).strip(),
        "backend": "llama.cpp + vision_mmproj",
        "elapsed_s": round(elapsed, 3),
        "path": clean_path,
    }


# ── Agent-tool wrappers (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="vision_analyze")
def _t_vision_analyze(image_path: str, question: str = "Describe this image in one short sentence.") -> dict:
    """Look at a workspace image and answer a question about it.
    Uses Jaeger's active local llama.cpp model plus its configured vision
    projector. image_path is sandbox-resolved under <instance>/skills/."""
    return look_at(image_path=image_path, question=question)


@register_tool_from_function(name="image_generate")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="vision",
               operation="image_generate",
               summary="generate an image into the skills workspace")
def _t_image_generate(
    prompt: str,
    out_path: str = "generated.png",
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    seed: int | None = None,
) -> dict:
    """Generate an image from a text prompt and save under skills/.
    Default backbone: SDXL-Turbo (1-step). First call downloads ~6 GB
    of weights; subsequent calls are 1-3s per image. Local + free +
    offline; for higher quality cloud generation (FLUX, needs FAL_KEY)
    use generate_image_fal instead."""
    return generate_image(
        prompt=prompt, out_path=out_path,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale, seed=seed,
    )
