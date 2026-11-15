"""Vision skills — Jaeger-native local vision + image generation.

  • look_at(image_path, question)       — active llama.cpp + mmproj brain
  • generate_image(prompt, out_path)    — official Grok Imagine (grok CLI OAuth),
                                          with a local SDXL-Turbo fallback only
                                          when those weights are already cached
  • edit_image(prompt, source_path)     — official Grok image_edit

The local vision projector is configured by Jaeger. Image generation uses the
installed grok CLI under the existing grok.com OAuth; it does not invent API
keys or unofficial routes. Local SDXL-Turbo can be selected with
IMAGE_GEN_MODEL_ID but is never auto-downloaded from here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading as _threading
import time
import uuid
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import SandboxError, _require_layout, _resolve_read, _resolve_under
from jaeger_agent.util.tool_interrupt import is_interrupted
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


# ---------------------------------------------------------------------------
# Image generation (official Grok Imagine, optional local SDXL-Turbo)
# ---------------------------------------------------------------------------
_imagegen_state: dict[str, Any] = {"pipeline": None, "model_id": None}
# Atomic load/swap for the shared pipeline — multi-instance agents
# (delegate sub-agents, deep think) can dispatch concurrently, and a
# racing reload mid-inference corrupts results silently.
_imagegen_lock = _threading.Lock()

_GROK_IMAGE_TIMEOUT_S = 120
_GROK_IMAGE_TURNS = 6
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_SAFE_GROK_ENV = frozenset({
    "COLORTERM", "HOME", "LANG", "LC_ALL", "LOGNAME", "NO_COLOR",
    "PATH", "SHELL", "TERM", "TMPDIR", "USER",
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
})


def _grok_cli_path() -> Path | None:
    for raw in (os.environ.get("JAEGER_GROK_BIN"), os.environ.get("GROK_CLI")):
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    which = shutil.which("grok")
    if which:
        return Path(which)
    default = Path.home() / ".grok" / "bin" / "grok"
    if default.is_file() and os.access(default, os.X_OK):
        return default
    return None


def _grok_oauth_available() -> bool:
    """True when the official grok.com OAuth file exists. Never read it."""
    return (Path.home() / ".grok" / "auth.json").is_file()


def _hf_weights_cached(model_id: str) -> bool:
    cache = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + model_id.replace("/", "--"))
    if not cache.is_dir():
        return False
    try:
        return any(path.name == "model_index.json" for path in cache.rglob("model_index.json"))
    except OSError:
        return False


def _ensure_imagegen_pipeline() -> tuple[Any, str]:
    model_id = os.environ.get("IMAGE_GEN_MODEL_ID", "stabilityai/sdxl-turbo")
    with _imagegen_lock:
        return _ensure_imagegen_pipeline_locked(model_id)


def _ensure_imagegen_pipeline_locked(model_id: str) -> tuple[Any, str]:
    if _imagegen_state["pipeline"] is not None and _imagegen_state["model_id"] == model_id:
        return _imagegen_state["pipeline"], model_id
    if not _hf_weights_cached(model_id):
        raise RuntimeError(
            f"local image model {model_id} is not cached; image_generate will not "
            "download the weights automatically (~6 GB). Use Grok Imagine, or "
            "download the model first."
        )

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
        model_id,
        torch_dtype=dtype,
        variant="fp16" if dtype == torch.float16 else None,
        local_files_only=True,
    ).to(device)
    print(f"[image_gen] {model_id} loaded on {device} in {time.perf_counter() - started:.1f}s", flush=True)
    _imagegen_state["pipeline"] = pipe
    _imagegen_state["model_id"] = model_id
    return pipe, model_id


def _resolve_image_out(out_path: str) -> tuple[Any, Path] | dict[str, Any]:
    layout = _require_layout()
    clean = (out_path or "generated/image.png").strip() or "generated/image.png"
    try:
        target = _resolve_under(layout.workspace_dir, clean)
    except SandboxError:
        try:
            target = _resolve_under(layout.skills_dir, clean)
        except SandboxError as exc:
            return {"generated": False, "error": str(exc)}
    if target.suffix.lower() not in _RASTER_SUFFIXES:
        target = target.with_suffix(".png")
    return layout, target


def _copy_raster(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _sniff_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"GIF87a")
        or head.startswith(b"GIF89a")
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    )


def _image_meta(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"bytes": path.stat().st_size, "filename": path.name}
    try:
        from PIL import Image
        with Image.open(path) as image:
            info["width"], info["height"] = image.size
            fmt = (image.format or path.suffix.lstrip(".")).lower()
            info["format"] = fmt
            info["mime"] = Image.MIME.get(image.format or "", f"image/{fmt}")
    except Exception:
        suffix = path.suffix.lower()
        info["mime"] = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "application/octet-stream")
    return info


def _grok_child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _SAFE_GROK_ENV if key in os.environ}
    # A throwaway session must not attach to Jaeger's grok leader socket.
    for key in list(os.environ):
        upper = key.upper()
        if "GROK" in upper and ("LEADER" in upper or "SOCK" in upper or "SOCKET" in upper):
            env.pop(key, None)
    return env


def _collect_grok_image(cwd: Path, session_id: str, started: float) -> Path | None:
    candidates: list[Path] = []
    for folder in (cwd, cwd / "images"):
        if folder.is_dir():
            candidates.extend(
                path for path in folder.rglob("*")
                if path.is_file() and path.suffix.lower() in _RASTER_SUFFIXES
            )
    sessions_root = Path.home() / ".grok" / "sessions"
    if sessions_root.is_dir():
        for session_dir in sessions_root.glob(f"*/{session_id}"):
            if session_dir.is_dir():
                candidates.extend(
                    path for path in session_dir.rglob("*")
                    if path.is_file() and path.suffix.lower() in _RASTER_SUFFIXES
                )
    fresh = [path for path in candidates if path.stat().st_mtime >= started - 2 and _sniff_image(path)]
    if not fresh:
        return None
    return max(fresh, key=lambda path: path.stat().st_mtime)


def _run_grok_imagine(prompt: str, *, source: Path | None = None) -> dict[str, Any]:
    cli = _grok_cli_path()
    if cli is None:
        return {"generated": False, "error": "grok CLI is not installed"}
    if not _grok_oauth_available():
        return {"generated": False, "error": "grok.com OAuth is not signed in (missing ~/.grok/auth.json)"}

    work = Path(tempfile.mkdtemp(prefix="jaeger-imagine-"))
    session_id = str(uuid.uuid4())
    if source is not None:
        local_source = work / source.name
        shutil.copy2(source, local_source)
        instruction = (
            f"Call the image_edit tool now on the file {local_source.name}. "
            f"Apply this edit, and no other work: {prompt} "
            "After it saves, reply with only the relative file path."
        )
        backend = "grok-imagine-edit"
    else:
        instruction = (
            f"Call the image_gen tool now. Create this image, and no other work: {prompt} "
            "After it saves, reply with only the relative file path."
        )
        backend = "grok-imagine"
    stdout_path = work / "stdout.json"
    stderr_path = work / "stderr.txt"
    argv = [
        str(cli), "--single", instruction,
        "--session-id", session_id,
        "--cwd", str(work),
        "--permission-mode", "bypassPermissions",
        "--always-approve",
        "--max-turns", str(_GROK_IMAGE_TURNS),
        "--disable-web-search",
        "--no-subagents",
        "--no-plan",
        "--output-format", "json",
        "--verbatim",
    ]
    started = time.perf_counter()
    wall_start = time.time()
    try:
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            proc = subprocess.Popen(
                argv,
                cwd=str(work),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=_grok_child_env(),
                start_new_session=True,
            )
            deadline = time.time() + _GROK_IMAGE_TIMEOUT_S
            while True:
                if is_interrupted():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return {"generated": False, "interrupted": True, "error": "image generation interrupted by user"}
                try:
                    proc.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if time.time() >= deadline:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        return {"generated": False, "error": "Grok Imagine timed out"}
        if proc.returncode not in (0, None) and not list(work.rglob("*")):
            return {"generated": False, "error": f"grok CLI exited {proc.returncode}"}
        found = _collect_grok_image(work, session_id, wall_start)
        # Also honour a relative path in the JSON text field, without logging the payload.
        if found is None and stdout_path.is_file():
            try:
                payload = json.loads(stdout_path.read_text(errors="replace") or "{}")
                text = str(payload.get("text") or "").strip().splitlines()[0] if payload.get("text") else ""
                if text:
                    candidate = (work / text).resolve()
                    if candidate.is_file() and candidate.is_relative_to(work) and _sniff_image(candidate):
                        found = candidate
            except (OSError, json.JSONDecodeError, ValueError, IndexError):
                pass
        if found is None:
            return {"generated": False, "error": "Grok Imagine finished without an image file"}
        elapsed = time.perf_counter() - started
        return {
            "generated": True,
            "source_file": str(found),
            "backend": backend,
            "model_id": "grok-imagine",
            "elapsed_s": round(elapsed, 3),
            "prompt": prompt,
        }
    except FileNotFoundError:
        return {"generated": False, "error": "grok CLI is not installed"}
    except Exception as exc:
        return {"generated": False, "error": f"Grok Imagine failed: {type(exc).__name__}"}


def _local_sdxl(prompt: str, *, num_inference_steps: int, guidance_scale: float, seed: int | None) -> dict[str, Any]:
    try:
        pipe, model_id = _ensure_imagegen_pipeline()
    except Exception as exc:
        return {"generated": False, "error": str(exc)}
    try:
        import torch
        gen = torch.Generator(device=pipe.device).manual_seed(seed) if seed is not None else None
        started = time.perf_counter()
        result = pipe(
            prompt=prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=gen,
        )
        image = result.images[0]
        elapsed = time.perf_counter() - started
        return {
            "generated": True,
            "image": image,
            "backend": "local-sdxl-turbo",
            "model_id": model_id,
            "elapsed_s": round(elapsed, 3),
            "prompt": prompt,
            "seed": seed,
        }
    except Exception as exc:
        return {"generated": False, "error": f"inference failed: {exc}"}


def generate_image(
    prompt: str,
    out_path: str = "generated/image.png",
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    seed: int | None = None,
    backend: str = "auto",
) -> dict[str, Any]:
    """Generate an image from a text prompt and save it in the instance workspace.

    Default backend is official Grok Imagine via the grok CLI (grok.com OAuth).
    Local SDXL-Turbo is used only when weights are already cached, or when
    backend="local". First-time SDXL downloads are not started from this tool.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"generated": False, "error": "empty prompt"}
    resolved = _resolve_image_out(out_path)
    if isinstance(resolved, dict):
        return resolved
    layout, target = resolved

    wanted = (backend or "auto").strip().lower()
    errors: list[str] = []

    if wanted in {"auto", "grok", "grok-imagine", "imagine"}:
        grok = _run_grok_imagine(clean_prompt)
        if grok.get("generated"):
            saved = _copy_raster(Path(grok["source_file"]), target)
            meta = _image_meta(saved)
            return {
                "generated": True,
                "path": str(saved.relative_to(layout.root)),
                "absolute_path": str(saved),
                "backend": grok["backend"],
                "model_id": grok["model_id"],
                "elapsed_s": grok["elapsed_s"],
                "prompt": clean_prompt,
                **meta,
            }
        errors.append(str(grok.get("error") or "Grok Imagine unavailable"))
        if grok.get("interrupted"):
            return {"generated": False, "interrupted": True, "error": grok["error"]}
        if wanted != "auto":
            return {"generated": False, "error": errors[-1]}

    if wanted in {"auto", "local", "sdxl", "sdxl-turbo"}:
        local = _local_sdxl(
            clean_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
        )
        if local.get("generated"):
            target.parent.mkdir(parents=True, exist_ok=True)
            local["image"].save(target)
            meta = _image_meta(target)
            return {
                "generated": True,
                "path": str(target.relative_to(layout.root)),
                "absolute_path": str(target),
                "backend": local["backend"],
                "model_id": local["model_id"],
                "elapsed_s": local["elapsed_s"],
                "prompt": clean_prompt,
                "seed": seed,
                **meta,
            }
        errors.append(str(local.get("error") or "local image model unavailable"))
        if wanted != "auto":
            return {"generated": False, "error": errors[-1]}

    return {"generated": False, "error": "; ".join(errors) or "no image backend available"}


def edit_image(prompt: str, source_path: str, out_path: str = "generated/edited.png") -> dict[str, Any]:
    """Edit an existing workspace image with official Grok image_edit."""
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"generated": False, "error": "empty prompt"}
    if not (source_path or "").strip():
        return {"generated": False, "error": "empty source_path"}
    layout = _require_layout()
    try:
        source = _resolve_read(source_path)
    except SandboxError as exc:
        return {"generated": False, "error": str(exc)}
    if not source.is_file() or not _sniff_image(source):
        return {"generated": False, "error": "source_path is not a readable raster image"}
    resolved = _resolve_image_out(out_path)
    if isinstance(resolved, dict):
        return resolved
    _layout, target = resolved
    grok = _run_grok_imagine(clean_prompt, source=source)
    if not grok.get("generated"):
        return grok
    saved = _copy_raster(Path(grok["source_file"]), target)
    meta = _image_meta(saved)
    return {
        "generated": True,
        "path": str(saved.relative_to(layout.root)),
        "absolute_path": str(saved),
        "backend": grok["backend"],
        "model_id": grok["model_id"],
        "elapsed_s": grok["elapsed_s"],
        "prompt": clean_prompt,
        "source_path": source_path,
        **meta,
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
    from jaeger_agent.core.host import service
    _pipeline = service("pipeline")._pipeline

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
               summary="generate an image into the workspace")
def _t_image_generate(
    prompt: str,
    out_path: str = "generated/image.png",
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    seed: int | None = None,
    backend: str = "auto",
) -> dict:
    """Generate an image from a text prompt and save it under the workspace.

    Default: official Grok Imagine via the installed grok CLI (grok.com OAuth).
    Works from any chat brain (Grok, Ollama, Gemini, …). A local SDXL-Turbo
    fallback is used only when those weights are already cached; this tool
    will not start a multi-gigabyte download. For fal.ai FLUX (needs FAL_KEY)
    use generate_image_fal. Use image_edit to revise an existing image.
    """
    return generate_image(
        prompt=prompt, out_path=out_path,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale, seed=seed, backend=backend,
    )


@register_tool_from_function(name="image_edit")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="vision",
               operation="image_edit",
               summary="edit an existing workspace image with Grok Imagine")
def _t_image_edit(
    prompt: str,
    source_path: str,
    out_path: str = "generated/edited.png",
) -> dict:
    """Edit an existing workspace image with official Grok image_edit.
    source_path is sandbox-resolved. Requires the grok CLI and grok.com OAuth."""
    return edit_image(prompt=prompt, source_path=source_path, out_path=out_path)


def view_image(path: str, max_edge: int = 1024) -> dict[str, Any]:
    """Read an image file and return format, size, and a small preview.

    Model-agnostic: this does not call a vision model. The path is
    resolved the same way as ``read_file``. Credential paths are refused.
    A compact JPEG preview (base64) is included when the file can be
    decoded, capped so it does not flood the context.
    """
    import base64
    import hashlib
    import io
    from jaeger_agent.core.workspace import SandboxError, _display_path, _require_layout, _resolve_read
    from jaeger_os.core.safety.file_safety import is_sensitive_path

    raw = (path or "").strip()
    if not raw:
        return {"ok": False, "error": "empty path"}
    try:
        target = _resolve_read(raw)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc), "path": raw}
    if is_sensitive_path(target):
        return {"ok": False, "error": "refused — credential or secret path", "path": raw}
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "not found", "path": raw}
    try:
        data = target.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": raw}
    result: dict[str, Any] = {
        "ok": True,
        "path": _display_path(target, _require_layout()),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "suffix": target.suffix.lower(),
    }
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            result["format"] = (image.format or target.suffix.lstrip(".")).lower()
            result["mime"] = Image.MIME.get(image.format or "", f"image/{result['format']}")
            result["width"], result["height"] = image.size
            result["mode"] = image.mode
            preview = image.convert("RGB") if image.mode != "RGB" else image.copy()
            edge = max(32, min(int(max_edge or 1024), 2048))
            preview.thumbnail((edge, edge))
            buf = io.BytesIO()
            preview.save(buf, format="JPEG", quality=70, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            # Keep the preview modest so a tool row stays usable.
            if len(encoded) <= 64_000:
                result["preview_mime"] = "image/jpeg"
                result["preview_base64"] = encoded
                result["preview_width"], result["preview_height"] = preview.size
            else:
                result["preview"] = "omitted — preview exceeded size cap"
    except Exception as exc:  # noqa: BLE001 — still return metadata
        result["decode_error"] = type(exc).__name__
        result["ok"] = result.get("bytes", 0) > 0
        if "format" not in result:
            result["error"] = "not a decodable image"
            result["ok"] = False
    return result


@register_tool_from_function(name="view_image", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="vision", operation="view_image",
               summary="read an image file's format, size, and a small preview")
def _t_view_image(path: str) -> dict:
    """Read an image (png, jpeg, gif, webp, …) and return its dimensions,
    format, and a small preview. This is a model-agnostic image read —
    it does not require a vision model. Use vision_analyze when you need
    a description of what the picture shows."""
    return view_image(path=path)
