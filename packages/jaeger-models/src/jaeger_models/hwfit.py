"""Multi-modality local model Hardware-Fit Cookbook & benchmark helper.

Inspired by ``llmfit`` (MIT) hardware-fit scoring and expanded across all local
modalities (LLM, Vision/VLM, Image Gen, STT, TTS, Embeddings) for Apple Silicon
unified memory and desktop GPUs. Pure stdlib, zero external daemons.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import platform
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

from jaeger_contracts import ModelPort

from .local_budget import host_total_memory_gb, safe_local_context_window

SUPPORTED_MODALITIES: tuple[str, ...] = (
    "llm",
    "vision",
    "image_gen",
    "stt",
    "tts",
    "embedding",
)


@dataclass(frozen=True)
class HardwareProfile:
    platform_name: str
    arch: str
    chip: str
    total_ram_gb: float
    usable_ram_gb: float
    unified_memory: bool
    simulated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelRecipe:
    recipe_id: str
    name: str
    modality: str
    runtime: str
    pull_ref: str
    quantization: str
    weights_gb: float
    kv_per_8k_gb: float
    default_ctx: int
    tags: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FitEvaluation:
    recipe: ModelRecipe
    fit: str  # "ideal" | "comfortable" | "tight" | "wont_fit"
    estimated_ram_gb: float
    headroom_gb: float
    utilization_pct: float
    recommended_ctx: int
    installed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recipe"] = self.recipe.to_dict()
        return d


BUILTIN_COOKBOOK: tuple[ModelRecipe, ...] = (
    # --- Local LLMs ---
    ModelRecipe(
        recipe_id="ollama/qwen3-8b",
        name="Qwen 3 8B (Q4_K_M)",
        modality="llm",
        runtime="ollama",
        pull_ref="qwen3:8b",
        quantization="Q4_K_M",
        weights_gb=5.2,
        kv_per_8k_gb=0.6,
        default_ctx=32_768,
        tags=("fast", "tools", "reasoning"),
        notes="Snappy daily companion and tool-caller; leaves plenty of unified RAM free.",
    ),
    ModelRecipe(
        recipe_id="ollama/qwen2.5-coder-14b",
        name="Qwen 2.5 Coder 14B (Q4_K_M)",
        modality="llm",
        runtime="ollama",
        pull_ref="qwen2.5-coder:14b",
        quantization="Q4_K_M",
        weights_gb=9.0,
        kv_per_8k_gb=0.9,
        default_ctx=32_768,
        tags=("coding", "tools", "local"),
        notes="Sweet-spot local coding & CAD-scripting model on 32 GB Apple Silicon.",
    ),
    ModelRecipe(
        recipe_id="ollama/qwen3-14b",
        name="Qwen 3 14B (Q4_K_M)",
        modality="llm",
        runtime="ollama",
        pull_ref="qwen3:14b",
        quantization="Q4_K_M",
        weights_gb=9.3,
        kv_per_8k_gb=0.9,
        default_ctx=40_960,
        tags=("general", "reasoning", "tools"),
        notes="Balanced reasoning + tool calling within a 32 GB memory budget.",
    ),
    ModelRecipe(
        recipe_id="ollama/qwen2.5-coder-32b",
        name="Qwen 2.5 Coder 32B (Q4_K_M)",
        modality="llm",
        runtime="ollama",
        pull_ref="qwen2.5-coder:32b",
        quantization="Q4_K_M",
        weights_gb=19.8,
        kv_per_8k_gb=1.4,
        default_ctx=32_768,
        tags=("coding", "heavy"),
        notes="High-accuracy local coding; runs as sole heavy resident on 32 GB Macs.",
    ),
    ModelRecipe(
        recipe_id="mlx/qwen3-32b-4bit",
        name="Qwen 3 32B (MLX 4-bit)",
        modality="llm",
        runtime="mlx",
        pull_ref="mlx-community/Qwen3-32B-4bit",
        quantization="4bit",
        weights_gb=18.6,
        kv_per_8k_gb=1.3,
        default_ctx=32_768,
        tags=("mlx", "reasoning", "heavy"),
        notes="Native Apple Silicon Metal inference via MLX; max 1 heavy model resident.",
    ),
    ModelRecipe(
        recipe_id="ollama/llama3.3-70b",
        name="Llama 3.3 70B (Q4_K_M)",
        modality="llm",
        runtime="ollama",
        pull_ref="llama3.3:70b",
        quantization="Q4_K_M",
        weights_gb=42.5,
        kv_per_8k_gb=2.2,
        default_ctx=32_768,
        tags=("heavy", "64gb+"),
        notes="Requires 64 GB+ unified RAM or dual-GPU server.",
    ),
    # --- Local Vision / VLMs ---
    ModelRecipe(
        recipe_id="ollama/qwen2.5vl-7b",
        name="Qwen 2.5 VL 7B (Q4_K_M)",
        modality="vision",
        runtime="ollama",
        pull_ref="qwen2.5vl:7b",
        quantization="Q4_K_M",
        weights_gb=6.0,
        kv_per_8k_gb=0.7,
        default_ctx=16_384,
        tags=("vision", "cad-inspect", "camera"),
        notes="Great for inspecting Aether-CAD renders, screenshots, and Droid camera frames.",
    ),
    ModelRecipe(
        recipe_id="ollama/gemma3-12b",
        name="Gemma 3 12B Multimodal (Q4_K_M)",
        modality="vision",
        runtime="ollama",
        pull_ref="gemma3:12b",
        quantization="Q4_K_M",
        weights_gb=8.1,
        kv_per_8k_gb=0.8,
        default_ctx=32_768,
        tags=("vision", "general"),
        notes="Strong combined vision + text model for 24-32 GB Apple Silicon.",
    ),
    # --- Local Image Generation ---
    ModelRecipe(
        recipe_id="mlx/flux-schnell-4bit",
        name="FLUX.1 Schnell (MLX 4-bit)",
        modality="image_gen",
        runtime="mlx",
        pull_ref="dhairyashil/FLUX.1-schnell-mflux-4bit",
        quantization="4bit",
        weights_gb=8.5,
        kv_per_8k_gb=0.0,
        default_ctx=0,
        tags=("image", "fast", "mlx"),
        notes="4-step fast local image generation on Apple Silicon Metal.",
    ),
    ModelRecipe(
        recipe_id="mlx/flux-dev-4bit",
        name="FLUX.1 Dev (MLX 4-bit)",
        modality="image_gen",
        runtime="mlx",
        pull_ref="dhairyashil/FLUX.1-dev-mflux-4bit",
        quantization="4bit",
        weights_gb=9.2,
        kv_per_8k_gb=0.0,
        default_ctx=0,
        tags=("image", "quality", "mlx"),
        notes="Higher-detail local image synthesis; keep LLM unloaded during generation on 32 GB.",
    ),
    # --- Local Speech-to-Text (STT) ---
    ModelRecipe(
        recipe_id="mlx/whisper-large-v3-turbo",
        name="Whisper Large v3 Turbo (MLX)",
        modality="stt",
        runtime="mlx",
        pull_ref="mlx-community/whisper-large-v3-turbo",
        quantization="fp16",
        weights_gb=1.6,
        kv_per_8k_gb=0.0,
        default_ctx=0,
        tags=("stt", "realtime", "voice"),
        notes="Fast Apple Silicon local STT; easily co-resident with an active LLM.",
    ),
    ModelRecipe(
        recipe_id="onnx/sensevoice-small",
        name="SenseVoice Small (Sherpa-ONNX int8)",
        modality="stt",
        runtime="onnx",
        pull_ref="sherpa-onnx-sense-voice-int8",
        quantization="int8",
        weights_gb=0.35,
        kv_per_8k_gb=0.0,
        default_ctx=0,
        tags=("stt", "ultra-light", "coreml"),
        notes="Ultra-lightweight multilingual STT + emotion cues (~350 MB).",
    ),
    # --- Local Text-to-Speech (TTS) ---
    ModelRecipe(
        recipe_id="mlx/kokoro-82m",
        name="Kokoro-82M TTS",
        modality="tts",
        runtime="mlx",
        pull_ref="mlx-community/Kokoro-82M-bf16",
        quantization="bf16",
        weights_gb=0.45,
        kv_per_8k_gb=0.0,
        default_ctx=0,
        tags=("tts", "realtime", "voice"),
        notes="JaegerAI's built-in low-latency expressive voice engine (~450 MB).",
    ),
    # --- Local Embeddings ---
    ModelRecipe(
        recipe_id="ollama/nomic-embed-text",
        name="Nomic Embed Text v1.5",
        modality="embedding",
        runtime="ollama",
        pull_ref="nomic-embed-text",
        quantization="F16",
        weights_gb=0.3,
        kv_per_8k_gb=0.0,
        default_ctx=8_192,
        tags=("embedding", "memory", "rag"),
        notes="Tiny high-quality local embeddings for memory & wiki search.",
    ),
)


def probe_hardware(*, host_ram_gb: float | None = None) -> HardwareProfile:
    """Inspect local CPU/RAM hardware or simulate a target memory size."""
    simulated = host_ram_gb is not None
    total = float(host_ram_gb) if host_ram_gb is not None else float(host_total_memory_gb() or 16.0)
    total = max(4.0, round(total, 2))
    os_name = platform.system()
    arch = platform.machine()
    chip = platform.processor() or arch
    unified = False
    if os_name == "Darwin":
        try:
            brand = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                timeout=1.5,
            ).strip()
            if brand:
                chip = brand
        except Exception:  # noqa: BLE001
            pass
        unified = arch in ("arm64", "aarch64") or "apple" in chip.lower()
    # Reserve OS + Desktop + WebUI headroom so we never push macOS into swap thrashing.
    reserve = min(6.5, max(2.5, round(total * 0.22, 2)))
    usable = max(2.0, round(total - reserve, 2))
    return HardwareProfile(
        platform_name=os_name,
        arch=arch,
        chip=chip,
        total_ram_gb=total,
        usable_ram_gb=usable,
        unified_memory=unified,
        simulated=simulated,
    )


def evaluate_recipe_fit(
    recipe: ModelRecipe,
    hardware: HardwareProfile,
    *,
    installed_names: Iterable[str] = (),
    target_ctx: int | None = None,
) -> FitEvaluation:
    """Score how comfortably ``recipe`` fits on ``hardware``."""
    installed_set = {str(n).strip().lower() for n in installed_names if str(n).strip()}
    is_installed = (
        recipe.pull_ref.lower() in installed_set
        or recipe.recipe_id.lower() in installed_set
        or recipe.pull_ref.split(":")[0].lower() in {n.split(":")[0] for n in installed_set}
    )

    if recipe.default_ctx > 0:
        req_ctx = int(target_ctx) if target_ctx else recipe.default_ctx
        rec_ctx = safe_local_context_window(req_ctx, host_ram_gb=hardware.total_ram_gb)
        kv_gb = round(recipe.kv_per_8k_gb * (rec_ctx / 8192.0), 2)
    else:
        rec_ctx = 0
        kv_gb = 0.0

    est_ram = round(recipe.weights_gb + kv_gb, 2)
    headroom = round(hardware.usable_ram_gb - est_ram, 2)
    util = round((est_ram / max(0.5, hardware.usable_ram_gb)) * 100.0, 1)

    if util <= 55.0:
        fit = "ideal"
    elif util <= 78.0:
        fit = "comfortable"
    elif util <= 96.0:
        fit = "tight"
    else:
        fit = "wont_fit"

    return FitEvaluation(
        recipe=recipe,
        fit=fit,
        estimated_ram_gb=est_ram,
        headroom_gb=headroom,
        utilization_pct=util,
        recommended_ctx=rec_ctx,
        installed=is_installed,
    )


def recommend_models(
    *,
    modality: str | None = None,
    host_ram_gb: float | None = None,
    installed_names: Iterable[str] = (),
    include_unfit: bool = True,
    recipes: Sequence[ModelRecipe] = BUILTIN_COOKBOOK,
) -> dict[str, Any]:
    """Build a complete Hardware-Fit Cookbook report for the current (or simulated) machine."""
    hw = probe_hardware(host_ram_gb=host_ram_gb)
    mod_filter = (modality or "").strip().lower()
    if mod_filter and mod_filter != "all" and mod_filter not in SUPPORTED_MODALITIES:
        raise ValueError(f"unsupported modality {modality!r}; expected one of {SUPPORTED_MODALITIES}")

    rank_order = {"ideal": 0, "comfortable": 1, "tight": 2, "wont_fit": 3}
    evals: list[FitEvaluation] = []
    for rec in recipes:
        if mod_filter and mod_filter != "all" and rec.modality != mod_filter:
            continue
        ev = evaluate_recipe_fit(rec, hw, installed_names=installed_names)
        if not include_unfit and ev.fit == "wont_fit":
            continue
        evals.append(ev)

    evals.sort(key=lambda e: (rank_order.get(e.fit, 9), e.recipe.modality, e.estimated_ram_gb))
    return {
        "ok": True,
        "hardware": hw.to_dict(),
        "modality_filter": mod_filter or "all",
        "modalities": list(SUPPORTED_MODALITIES),
        "count": len(evals),
        "recommendations": [e.to_dict() for e in evals],
    }


def benchmark_model(
    model: ModelPort,
    *,
    prompt: str = "Reply with exactly five words confirming you are ready.",
    max_tokens: int = 128,
) -> dict[str, Any]:
    """Run a quick, bounded latency & throughput probe against any ModelPort."""
    t0 = time.monotonic()
    try:
        res = model.complete([{"role": "user", "content": prompt}], max_tokens=max_tokens)
        elapsed_s = max(1e-4, time.monotonic() - t0)
        text = str(res.get("content") or "")
        est_tokens = max(1, len(text) // 4) if text else 0
        return {
            "ok": True,
            "model": getattr(model, "name", "unknown"),
            "latency_ms": int(elapsed_s * 1000),
            "output_chars": len(text),
            "est_tokens_per_sec": round(est_tokens / elapsed_s, 1),
            "preview": text[:200],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_s = max(1e-4, time.monotonic() - t0)
        return {
            "ok": False,
            "model": getattr(model, "name", "unknown"),
            "latency_ms": int(elapsed_s * 1000),
            "output_chars": 0,
            "est_tokens_per_sec": 0.0,
            "preview": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


__all__ = [
    "BUILTIN_COOKBOOK",
    "FitEvaluation",
    "HardwareProfile",
    "ModelRecipe",
    "SUPPORTED_MODALITIES",
    "benchmark_model",
    "evaluate_recipe_fit",
    "probe_hardware",
    "recommend_models",
]
