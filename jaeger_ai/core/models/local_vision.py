"""Local image understanding through Jaeger's VISION-certified model.

The VISION role is certified with a real image probe (``probe``): a generated
picture with a known colour, shape and number must be read back correctly.
``describe`` then answers questions about an image with that model, on this
Mac, through Ollama. Nothing here sends an image to a cloud service; cloud
vision stays a separate, opt-in path.

Chosen 2026-11-15 for the M1 Max 32 GB: ``qwen3-vl:8b-instruct`` (Qwen3-VL 8B
Instruct, Q4_K_M, ~6 GB). The installed ``qwen3-vl:8b`` tag is the thinking
variant: it ignores ``think: false`` and spends ~250 tokens (~6 s) reasoning
before a one-word answer, so the instruct build is the right fit for camera
turns. ``num_ctx`` is pinned at 8192; Ollama's default for this model is the
full 256K window, which allocates ~46 GB and spills half the model to CPU. Override with
``JAEGER_VISION_MODEL`` (an Ollama model name).
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "qwen3.5:9b"
PROBE_NUMBER = "47"


def _ollama_base() -> str:
    try:
        from jaeger_ai.core.models.router import resolve_ollama_base_url
        base = (resolve_ollama_base_url(openai_compat=False) or "").rstrip("/")
    except Exception:  # noqa: BLE001
        base = ""
    base = base or os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _instance_root() -> Path | None:
    try:
        from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
        return InstanceLayout(root=resolve_instance_dir()).root
    except Exception:  # noqa: BLE001
        return None


def certified_model() -> str | None:
    """The local Ollama model that passed VISION, preferring the configured one."""
    root = _instance_root()
    if root is None:
        return None
    try:
        from jaeger_ai.core.instance.provider_certification import load_matrix
        matrix = load_matrix(root)
    except Exception:  # noqa: BLE001
        return None
    wanted = (os.environ.get("JAEGER_VISION_MODEL") or "").strip()
    passing = [r for r in matrix.results
               if r.role == "VISION" and r.passed and r.provider in {"ollama", "ollama-local"}
               and not r.model.endswith("cloud")]
    for row in passing:
        if wanted and row.model == wanted:
            return row.model
    assigned = (matrix.assignments.get("VISION") or {}).get("model")
    if assigned and any(r.model == assigned for r in passing):
        return assigned
    return passing[-1].model if passing else None


def _jpeg(data: bytes, max_edge: int = 1024) -> bytes:
    """Re-encode to a modest JPEG so prefill stays quick; pass through on failure."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_edge, max_edge))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=85)
            return out.getvalue()
    except Exception:  # noqa: BLE001
        return data


def describe(image: bytes, question: str = "", *, model: str | None = None,
             timeout: float = 120.0, max_edge: int = 1024) -> dict[str, Any]:
    """Ask the local vision model about one image. Returns ``{ok, answer, model, elapsed_s}``."""
    model = (
        (model or "").strip()
        or certified_model()
        or (os.environ.get("JAEGER_VISION_MODEL") or "").strip()
        or DEFAULT_MODEL
    )
    q = (question or "").strip() or "Describe this image in two short sentences. Read any visible text."
    opts: dict[str, Any] = {"temperature": 0, "num_predict": 400, "num_ctx": 8192}
    raw_ctx = (os.environ.get("JAEGER_VISION_CTX") or "").strip()
    if raw_ctx.isdigit() and int(raw_ctx) > 0:
        opts["num_ctx"] = int(raw_ctx)
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": q,
                      "images": [base64.b64encode(_jpeg(image, max_edge)).decode("ascii")]}],
        "stream": False,
        "think": False,
        "keep_alive": "15m",
        "options": opts,
    }).encode()
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                _ollama_base() + "/api/chat", body, {"Content-Type": "application/json"}),
                timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"local vision failed: {type(exc).__name__}: {exc}"[:300],
            "model": model,
            "elapsed_s": round(time.perf_counter() - started, 2),
        }
    answer = str(((data or {}).get("message") or {}).get("content") or "").strip()
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
    return {"ok": bool(answer), "answer": answer, "model": model, "local": True,
            "elapsed_s": round(time.perf_counter() - started, 2)}


def probe_image() -> bytes:
    """A 512x512 picture with a red circle, a blue square and the number 47."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 60, 220, 240), fill=(220, 20, 20))
    draw.rectangle((290, 60, 470, 240), fill=(20, 60, 220))
    font = None
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, 150)
            break
        except OSError:
            continue
    draw.text((170, 290), PROBE_NUMBER, fill="black", font=font or ImageFont.load_default())
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def probe(model: str) -> tuple[bool, str]:
    """Real VISION check: the model must read the number and name both shapes' colours."""
    result = describe(probe_image(), "What number is written in this image, what colour is the "
                      "circle, and what colour is the square? Answer in one short line.",
                      model=model, timeout=180)
    if not result.get("ok"):
        return False, str(result.get("error") or "no answer")
    answer = result["answer"].lower()
    ok = PROBE_NUMBER in answer and "red" in answer and "blue" in answer
    return ok, "" if ok else f"probe answer wrong: {result['answer'][:160]}"
