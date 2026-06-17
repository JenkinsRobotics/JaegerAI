"""Memory-tier-based model recommendations + host detection.

The wizard calls into here to detect the host's unified-memory budget,
classify it into a tier (12 / 24 / 32 / 64+ GB), and offer the data-
validated awake + asleep model picks for that tier — plus download
URLs for the recommended GGUFs so the operator can pull them with one
prompt at first-run.

The picks are sourced from the bench corpus 1.1 leaderboard captured
in ``benchmark/HISTORY.md``. Refresh the constants below when re-
benching shifts the rankings.
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
    score_pct: float           # latest bench corpus 1.1 score
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


# ── Model catalogue (data-validated 2026-05-31, corpus 1.1) ─────────
#
# Picks track the leaderboard. If you change these, also refresh the
# bench numbers in ``docs/deep_think_design.md`` so the wizard and the
# design doc never disagree.

_GEMMA_E4B_Q4 = ModelPick(
    registry_key="gemma-4-e4b-it-q4_k_m",
    display_name="gemma-4-E4B Q4",
    size_gb=5.0,
    score_pct=89.8,
    tokens_per_task=76,
    notes=("Snappy realtime — 76 tok/task, ~4m bench. Best small awake "
           "model in the library."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf"),
)

# 0.3.0: dense 12B Gemma 4.  Becomes the 24 GB tier's asleep pick
# (Mac Mini sweet spot) — fits cleanly alongside the E4B awake model
# with room for KV cache + host headroom, and leads the routing
# leaderboard at 94.9% with a clean 18/18 safety subset (the strict
# safety win that pushed it above Qwen3.5-9B at the 24 GB tier).
# At 32 GB and above the Qwen3-30B-A3B MoE stays the asleep pick
# because its 30B/3B-active speed (~3× tok/s) is the more important
# axis when host RAM allows.
_GEMMA_12B_Q4 = ModelPick(
    registry_key="gemma-4-12b-it-q4_k_m",
    display_name="gemma-4-12B Q4",
    size_gb=6.9,
    score_pct=94.9,
    tokens_per_task=65,
    notes=("Dense 12B, 6.9 GB on disk.  Leaderboard #1 at 94.9% "
           "routing with a clean 18/18 safety subset (today's bench, "
           "2026-06-04).  Slower tok/s than Qwen3.5-9B but stronger "
           "on safety and honest reasoning — ideal asleep pick on a "
           "24 GB host where MoE asleep models don't fit."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "gemma-4-12B-it-GGUF/resolve/main/"
                  "gemma-4-12B-it-Q4_K_M.gguf"),
)

_GEMMA_26B_A4B_Q4 = ModelPick(
    registry_key="gemma-4-26b-a4b-it-q4_k_m",
    display_name="gemma-4-26B-A4B Q4",
    size_gb=15.6,
    score_pct=91.5,
    tokens_per_task=65,
    notes=("MoE 4B active — 91.5% score at 65 tok/task. The "
           "speed-and-quality champion for awake mode."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "gemma-4-26B-A4B-it-GGUF/resolve/main/"
                  "gemma-4-26B-A4B-it-Q4_K_M.gguf"),
)

_QWEN_35_9B_Q4 = ModelPick(
    registry_key="qwen3.5-9b-q4_k_m",
    display_name="Qwen3.5-9B Q4",
    size_gb=5.2,
    score_pct=93.2,
    tokens_per_task=203,
    notes=("Highest deep-think tier score (17/18). Lowest peak load "
           "(2.4) measured anywhere. Gentle on the host while asleep."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"),
)

_QWEN_30B_A3B_Q4 = ModelPick(
    registry_key="qwen3-30b-a3b-q4_k_m",
    display_name="Qwen3-30B-A3B Q4",
    size_gb=17.3,
    score_pct=93.2,
    tokens_per_task=660,
    notes=("MoE 3B active. Same overall score as Qwen3.5-9B Q4 but "
           "+1 safety case (4/5 vs 3/5) and 2.5× faster bench. "
           "Pick this for asleep mode when the kanban includes "
           "safety-sensitive tool calls."),
    download_url=("https://huggingface.co/lmstudio-community/"
                  "Qwen3-30B-A3B-GGUF/resolve/main/"
                  "Qwen3-30B-A3B-Q4_K_M.gguf"),
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
    model — no swap, no asleep. 24 GB is the sweet spot for the
    Qwen3.5-9B asleep pairing. 32 GB unlocks the gemma-4-26B-A4B awake
    pick. 64+ GB unlocks Qwen3-30B-A3B as the safety-heavy asleep
    swap.
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
        # 24 GB: Mac Mini sweet spot — both ~5 GB models swap cleanly.
        return TierRecommendation(
            tier_label="24 GB",
            description=("Mac Mini sweet spot.  gemma-4-E4B awake "
                         "(5 GB, snappy) + gemma-4-12B asleep "
                         "(6.9 GB, leaderboard-#1 routing + clean "
                         "18/18 safety subset on the 2026-06-04 "
                         "bench).  Both fit alongside the KV cache + "
                         "host headroom on a 24 GB unified-memory "
                         "host.  Qwen3.5-9B kept as an alternate for "
                         "operators who prefer thinking-mode asleep "
                         "behaviour."),
            awake=_GEMMA_E4B_Q4,
            asleep=_GEMMA_12B_Q4,
            alternates=[_QWEN_35_9B_Q4],
        )
    if tier_gb < 64:
        # 32 GB: gemma-4-12B dense awake (leaderboard #1) leaves headroom for
        # voice (Whisper + Kokoro ~3 GB) CO-LOADED with the awake model. The
        # 26B-A4B awake is NOT recommended here — on a 32 GB host (e.g. M1
        # Max, ~26 GB GPU working set) the 26B + voice + 32K KV cache OOMs
        # the GPU. It stays a power-user alternate (text-only) and the
        # 64+ GB awake pick. Qwen3-30B-A3B asleep swaps in for deep-think.
        return TierRecommendation(
            tier_label="32 GB",
            description=("gemma-4-12B Q4 awake (dense, leaderboard #1, "
                         "6.9 GB) — leaves room to CO-LOAD voice (Whisper "
                         "+ Kokoro), which the 26B-A4B does not on a 32 GB "
                         "/ ~26 GB-GPU host (OOM). Qwen3-30B-A3B Q4 asleep "
                         "for deep-think (swap, not co-load). 26B-A4B "
                         "available as a text-only alternate."),
            awake=_GEMMA_12B_Q4,
            asleep=_QWEN_30B_A3B_Q4,
            alternates=[_GEMMA_26B_A4B_Q4, _QWEN_35_9B_Q4],
        )
    # 64+ GB: plenty of room — same picks, but can optionally co-load
    # for instant mode transitions if the operator wires that up.
    return TierRecommendation(
        tier_label="64+ GB",
        description=("Plenty of unified memory. Same awake/asleep "
                     "pairing as 32 GB — but co-load becomes "
                     "viable if you want zero-latency mode "
                     "transitions instead of swap."),
        awake=_GEMMA_26B_A4B_Q4,
        asleep=_QWEN_30B_A3B_Q4,
        alternates=[_QWEN_35_9B_Q4],
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
