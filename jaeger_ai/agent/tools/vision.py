"""Vision skills — local VLM + local image generator.

  • look_at(image_path, question)       — Moondream2 VLM (lazy CPU load)
  • generate_image(prompt, out_path)    — SDXL-Turbo (lazy MPS load)

Both backbones load on first use. Override the default model IDs via
VISION_MODEL_ID / IMAGE_GEN_MODEL_ID env vars.

Ported from pydantic_ai/skills/vision.py. The only Jaeger-specific
adjustment is sandbox: paths must resolve inside <instance>/skills/.
"""

from __future__ import annotations

import os
import threading as _threading
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.core.context import SandboxError, _require_layout, _resolve_under
from jaeger_ai.core.runtime.tool_interrupt import is_interrupted
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
    from jaeger_ai.core.models.lazy_deps import FeatureUnavailable, ensure
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
# look_at — Moondream2 VLM on CPU (Metal-safe)
# ---------------------------------------------------------------------------
_vision_state: dict[str, Any] = {"model": None, "tokenizer": None, "model_id": None}
_vision_lock = _threading.Lock()


def _ensure_vision_model() -> tuple[Any, Any, str]:
    model_id = os.environ.get("VISION_MODEL_ID", "vikhyatk/moondream2")
    with _vision_lock:
        return _ensure_vision_model_locked(model_id)


def _ensure_vision_model_locked(model_id: str) -> tuple[Any, Any, str]:
    if _vision_state["model"] is not None and _vision_state["model_id"] == model_id:
        return _vision_state["model"], _vision_state["tokenizer"], model_id

    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    started = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    # Pin to CPU — small model, and avoids Metal contention with llama-cpp.
    device = "cpu"
    model = AutoModelForCausalLM.from_pretrained(
        model_id, trust_remote_code=True, torch_dtype=torch.float32,
    ).to(device).eval()
    print(f"[vision] {model_id} loaded on {device} in {time.perf_counter() - started:.1f}s", flush=True)
    _vision_state["model"] = model
    _vision_state["tokenizer"] = tok
    _vision_state["model_id"] = model_id
    return model, tok, model_id


def warm_vision() -> dict[str, Any]:
    """Pre-load the Moondream2 VLM so the first ``look_at`` is inference-
    only, not a cold model load. Called by the boot warmup when
    ``warmup.vision`` is enabled. Idempotent — the model is memoized."""
    _, _, model_id = _ensure_vision_model()
    return {"warmed": True, "model": model_id}


def look_at(image_path: str, question: str = "Describe this image in one short sentence.") -> dict[str, Any]:
    """Look at an image file under <instance>/skills/ and answer a question.

    Path is sandbox-resolved under the instance's skills/ dir.
    Default backbone: Moondream2 (~1.9 B Apache-2.0 VLM). Override via
    VISION_MODEL_ID. First call lazy-loads on CPU.
    """
    clean_path = (image_path or "").strip()
    if not clean_path:
        return {"saw": False, "error": "empty image path"}
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, clean_path)
    except SandboxError as exc:
        return {"saw": False, "error": str(exc)}
    if not target.exists():
        return {"saw": False, "error": "image not found", "path": clean_path}

    try:
        from PIL import Image
    except Exception as exc:
        return {"saw": False, "error": f"Pillow missing: {exc}"}

    # The VLM load + inference below are single blocking calls that cannot
    # be interrupted partway. Bail before starting if the turn was already
    # cancelled so we don't kick off a multi-second model load nobody is
    # waiting on.
    if is_interrupted():
        return {"saw": False, "interrupted": True,
                "error": "look_at interrupted by user"}

    try:
        model, tok, model_id = _ensure_vision_model()
    except Exception as exc:
        return {"saw": False, "error": f"vision model load failed: {exc}"}

    try:
        img = Image.open(target).convert("RGB")
    except Exception as exc:
        return {"saw": False, "error": f"could not open image: {exc}"}

    q = (question or "Describe this image in one short sentence.").strip()
    started = time.perf_counter()
    try:
        if hasattr(model, "encode_image") and hasattr(model, "answer_question"):
            enc = model.encode_image(img)
            answer = model.answer_question(enc, q, tok)
        else:
            inputs = tok(q, return_tensors="pt").to(model.device)
            out = model.generate(**inputs, max_new_tokens=128)
            answer = tok.decode(out[0], skip_special_tokens=True)
    except Exception as exc:
        return {"saw": False, "error": f"inference failed: {exc}"}
    elapsed = time.perf_counter() - started

    return {
        "saw": True,
        "answer": str(answer).strip(),
        "model_id": model_id,
        "elapsed_s": round(elapsed, 3),
        "path": clean_path,
    }


# ── Agent-tool wrappers (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="vision_analyze")
def _t_vision_analyze(image_path: str, question: str = "Describe this image in one short sentence.") -> dict:
    """Look at a workspace image and answer a question about it.
    Default backbone: Moondream2 (~1.9B VLM, Apache-2.0). image_path is
    sandbox-resolved under <instance>/skills/. First call lazy-loads
    the VLM on CPU."""
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
