"""Memory-tier-based model recommendations + host detection.

The wizard calls into here to detect the host's unified-memory budget,
classify it into a tier (12 / 24 / 32 / 64+ GB), and offer the data-
validated awake + asleep model picks for that tier — plus download
URLs for the recommended GGUFs so the operator can pull them with one
prompt at first-run.

The picks track the corpus 1.1 overall-Score leaderboard in
``dev/benchmark/HISTORY.md`` (Score = passed/total across deep-think +
real-time + multi-turn + safety, mode=auto). The gemma 4 family leads
every tier — E4B (light, fastest, the awake pick everywhere) and the
26B-A4B (heavy / deep-think). The dense 12B is RETIRED: the corpus-1.2
sweep put E4B above every 12B quant on routing while being smaller, so
12B has no tier where it wins. ``score_pct`` below is the HISTORY
overall Score, NOT a single routing run. Refresh when a re-bench
regenerates HISTORY.md.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ModelPick:
    """One recommended model for a given mode + tier.

    NOTE for future iteration (user direction 2026-05-31): when bench
    scores are similar, the tiebreaker hierarchy is
    ``MoE > dense → larger base params → speed → peak TPS →
    peak load``. Not encoded in the dataclass yet; ranking lives in
    the picks themselves until the leaderboard surfaces it formally."""
    registry_key: str          # matches MODEL_REGISTRY in model_resolver
    display_name: str          # human-friendly, e.g. "gemma-4-26B-A4B Q4"
    size_gb: float             # on-disk size; rough swap budget signal
    score_pct: float           # corpus 1.1 overall Score (HISTORY.md)
    tokens_per_task: int       # verbosity — lower = faster per turn
    notes: str = ""            # one-liner trade-off
    download_url: str = ""     # HF or direct link; empty if not downloadable


@dataclass(frozen=True)
class TierRecommendation:
    """Recommended awake/asleep pair for a memory tier."""
    tier_label: str            # "12 GB", "24 GB", etc.
    description: str           # one-line tier intent
    awake: ModelPick
    asleep: ModelPick | None   # None for tiers where the host can't sustain a swap
    alternates: list[ModelPick] = field(default_factory=list)


# ── Model catalogue (data-validated 2026-06-19 routing sweep) ───────
#
# Picks track the leaderboard. If you change these, also refresh the
# bench numbers in ``docs/deep_think_design.md`` so the wizard and the
# design doc never disagree.

_GEMMA_E4B_Q4 = ModelPick(
    registry_key="gemma-4-e4b-it-q4_k_m",
    display_name="gemma-4-E4B Q4",
    size_gb=5.3,
    score_pct=88.1,
    tokens_per_task=76,
    notes=("Light/real-time default. 88.1% overall Score (corpus 1.1) "
           "but the FASTEST model in the library — 3m47s bench, 100% "
           "routing, 76 tok/task. Small enough (5.3 GB) to co-load with "
           "voice on any tier. The speed pick where latency matters most."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf"),
)

# 0.6.x: the dense 12B is RETIRED from the tier table. The clean corpus-1.2
# sweep put E4B (89.2% route, 5.3 GB) above every 12B quant (84–88%) while
# being smaller — so there is no RAM tier where 12B wins: below it E4B is
# better AND lighter, above it the 26B-A4B owns deep-think. The 24 GB tier
# now swaps in the 26B-A4B QAT (14.4 GB, 92.3% route) instead. (The registry
# key still exists for the runtime's VOICE_BACKUP / deep-think realtime
# fallback until those are repointed to E4B.)

# 0.6.x: the plain (non-QAT) 26B-A4B Q4_K_M is retired from the tier table —
# the QAT Q4_0 ties it on routing (92.3%) and is 2.4 GB smaller, so QAT is the
# one canonical 26B at every tier. The plain key stays in MODEL_REGISTRY
# (re-downloadable) but is no longer a recommended pick.

_GEMMA_26B_A4B_QAT = ModelPick(
    registry_key="gemma-4-26b-a4b-it-qat-q4_0",
    display_name="gemma-4-26B-A4B QAT Q4_0",
    size_gb=14.4,
    score_pct=92.3,
    tokens_per_task=89,
    notes=("MoE 4B active, QAT Q4_0 — the high / Deep Think default (0.6). "
           "Clean corpus-1.2 batch: 92.3% Score, 100% routing, a PERFECT "
           "20/20 deep-think tier. Ties the plain Q4_K_M but 2.4 GB smaller "
           "(14.4 GB) → more KV/context headroom voice-off on a 32 GB host."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "gemma-4-26B-A4B-it-QAT-GGUF/resolve/main/"
                  "gemma-4-26B-A4B-it-QAT-Q4_0.gguf"),
)

_QWEN_4B_THINKING_Q3 = ModelPick(
    registry_key="qwen3-4b-thinking-2507-q3_k_l",
    display_name="Qwen3-4B-Thinking-2507 Q3",
    size_gb=2.1,
    score_pct=93.2,
    tokens_per_task=1850,
    notes=("Tiny (2.1 GB) but verbose — emits reasoning by design. "
           "Use only when memory is too tight for anything else."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "Qwen3-4B-Thinking-2507-GGUF/resolve/main/"
                  "Qwen3-4B-Thinking-2507-Q3_K_L.gguf"),
)


# ── Tier table ──────────────────────────────────────────────────────


def recommend_for_tier(tier_gb: int) -> TierRecommendation:
    """Map a memory tier (``12`` / ``24`` / ``32`` / ``64+``) to a
    recommended awake + asleep pair.

    Below 12 GB the wizard should refuse to recommend a local model
    (too tight even for swap). 12 GB only supports a single small
    model — no swap, no asleep. 24 GB and 32 GB both run gemma-4-E4B
    awake and swap in gemma-4-26B-A4B (QAT) for deep-think. 64+ GB runs
    gemma-4-26B-A4B in both modes (no swap).
    """
    if tier_gb < 12:
        # Under-spec: still assign both modes for code-path symmetry,
        # but flag clearly that the host can't comfortably run the
        # recommended awake model. Caller should warn the operator.
        return TierRecommendation(
            tier_label=f"{tier_gb} GB (under-spec)",
            description=("Below 12 GB unified memory — local agent "
                         "isn't really viable. Same tiny model for "
                         "both modes (no swap) as a least-bad "
                         "fallback; a hosted model is the right "
                         "answer at this tier."),
            awake=_QWEN_4B_THINKING_Q3,
            asleep=_QWEN_4B_THINKING_Q3,
        )
    if tier_gb < 24:
        # 12 GB tier: tight, but Qwen3-4B-Thinking Q3 (2.1 GB) + the
        # awake model (5 GB) can SWAP cleanly — they just can't
        # co-load. The asleep pick prioritises deep-think score over
        # verbosity (1850 tok/task is fine when the user isn't
        # waiting), while keeping the file small enough that swap
        # fits comfortably on a 12 GB host.
        return TierRecommendation(
            tier_label="12 GB",
            description=("Tightest tier with full sleep-cycle support. "
                         "macOS + KV cache leave ~7-8 GB usable; swap "
                         "(not co-load) between the 5 GB awake model "
                         "and the 2.1 GB asleep model. Wake-up is "
                         "fast because the asleep model is tiny."),
            awake=_GEMMA_E4B_Q4,
            asleep=_QWEN_4B_THINKING_Q3,
        )
    if tier_gb < 32:
        # 24 GB: Mac Mini sweet spot. gemma-4-E4B awake + the 26B-A4B QAT
        # asleep — at 14.4 GB it swaps in cleanly on a 24 GB host (the
        # awake model is unloaded first) and wins deep-think outright. The
        # dense 12B that used to sit here is retired (E4B beats it + the
        # QAT is the better heavy model).
        return TierRecommendation(
            tier_label="24 GB",
            description=("Mac Mini sweet spot.  gemma-4-E4B awake "
                         "(5.3 GB, fastest) + gemma-4-26B-A4B QAT asleep "
                         "(14.4 GB, 92.3% route, 6/6 self-improvement "
                         "audit).  The QAT swaps in for deep-think (the "
                         "awake model unloads first) on a 24 GB host."),
            awake=_GEMMA_E4B_Q4,
            asleep=_GEMMA_26B_A4B_QAT,
        )
    if tier_gb < 64:
        # 32 GB (0.6, clean corpus-1.2 batch): gemma-4-E4B awake — fastest +
        # smallest (p50 2.8s, 5.3 GB), so it co-loads with voice with the MOST
        # headroom. gemma-4-26B-A4B QAT swaps in for deep-think (voice off) —
        # ties the plain 26B but 2.4 GB smaller. The 26B awake is still NOT
        # recommended (26B + voice + 32K KV OOMs the GPU).
        return TierRecommendation(
            tier_label="32 GB",
            description=("gemma-4-E4B Q4 awake — fastest/smallest (5.3 GB), "
                         "co-loads with voice (Whisper + Kokoro) with the most "
                         "headroom. gemma-4-26B-A4B QAT asleep for deep-think "
                         "(swap, not co-load) — 92.3% Score, 100% route, 20/20 "
                         "deep-think, 2.4 GB smaller than the plain 26B."),
            awake=_GEMMA_E4B_Q4,
            asleep=_GEMMA_26B_A4B_QAT,
        )
    # 64+ GB: plenty of room — gemma-4-26B-A4B QAT in both modes (no swap),
    # so mode transitions are instant. The 35B tier OOMs at 32K context
    # even here on the measured hardware, so 26B-A4B is the heavy ceiling.
    # QAT is the one canonical 26B (ties the plain Q4 on routing, smaller);
    # the plain Q4_K_M is no longer recommended at any tier.
    return TierRecommendation(
        tier_label="64+ GB",
        description=("Plenty of unified memory. gemma-4-26B-A4B QAT in "
                     "both awake and deep-think modes — same model, no "
                     "swap, instant mode transitions. 92.3% route, 20/20 "
                     "deep-think, 6/6 self-improvement audit (corpus 1.2)."),
        awake=_GEMMA_26B_A4B_QAT,
        asleep=_GEMMA_26B_A4B_QAT,
    )


# ── Host detection ──────────────────────────────────────────────────


HostKind = Literal["macos", "linux", "other"]


def detect_total_memory_gb() -> float:
    """Return total physical RAM in GB. Falls back to 0 if detection
    fails (caller should treat 0 as "unknown — ask the user")."""
    try:
        if platform.system() == "Darwin":
            # macOS — use sysctl. Faster than parsing vm_stat and works
            # without elevated privileges.
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=2, check=True,
            )
            return int(out.stdout.strip()) / (1024 ** 3)
        # Linux + POSIX fallback via sysconf — works on most Unixes.
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (pages * page_size) / (1024 ** 3)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


def classify_tier(total_gb: float) -> int:
    """Bucket the detected memory into the wizard's tier vocabulary.
    Rounds DOWN to the next supported tier so a 30 GB machine doesn't
    get over-promised a 32 GB pairing."""
    if total_gb >= 64:
        return 64
    if total_gb >= 32:
        return 32
    if total_gb >= 24:
        return 24
    if total_gb >= 12:
        return 12
    return int(total_gb)   # under-spec marker


def recommend_for_host() -> TierRecommendation:
    """Convenience — detect + classify + recommend in one call."""
    total = detect_total_memory_gb()
    tier = classify_tier(total)
    return recommend_for_tier(tier)
