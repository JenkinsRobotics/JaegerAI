"""Model path resolution + on-demand download.

Jaeger ships as a framework but the actual GGUF weights don't travel
in the wheel — they're too big (15 GB+) and licensing varies by model.
This module is the single place that turns "the agent wants gemma 4"
into an absolute path on disk, fetching from HuggingFace Hub if the
file isn't already cached.

Resolution order for any input string ``name_or_path``:

  1. Absolute path → use as-is (errors if it doesn't exist).
  2. Registry key (e.g. ``gemma-4-26b-a4b-it-q4_k_m``) → check the
     operator cache ``<install_root>/.jaeger_os/models/<key>/<file>``,
     then the package's ``jaeger_os/models/<file>`` (dev convenience for
     symlinks to LM Studio), then the LM Studio cache, then download
     from HF Hub to the operator cache.
  3. Relative path (e.g. ``./models/x.gguf`` or ``x.gguf``) → check
     cwd, package models/, then the operator cache. If still not found,
     fall through to treating the basename as a registry key.

The operator cache at ``<install_root>/.jaeger_os/models/<name>/<file>``
(``operator_state_root()/models``) is the production location. The
package's ``jaeger_os/models/`` directory stays valid as a dev
convenience — symlinks to LM Studio's cache resolve through step 2.

History: weights used to resolve from ``~/.jaeger/models/`` with the dev
dir at ``<repo>/src/jaeger_os/models/``. 0.2.6 dropped the ``src/``
layer (the package is ``jaeger_os/`` at the repo root) and moved the
cache to ``<install_root>/.jaeger_os/models/``; the legacy ``~/.jaeger/``
location is still honoured as a fallback for older installs.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import urllib.request
from typing import Any


# ── Registry ────────────────────────────────────────────────────────


# Every entry maps a stable key to its canonical source + filename.
# Add new entries here; don't hardcode HF paths in config files.
#
# Two roles:
#   * "realtime" — the fast conversational/routing model (Gemma 4 MoE).
#   * "coder"    — the heavy skill-authoring model used in Deep Think
#                  mode (see docs/deep_think_design.md). Swapped in via
#                  jaeger_os.main.switch_model when the robot enters
#                  Deep Think; swapped back out on wake.
MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    # ── Light tier (real-time, tight hosts) ─────────────────────────
    # Snappy small awake model — the light/real-time default. Fastest
    # in the library (3m47s bench, 100% routing on the corpus 1.1
    # leaderboard; 88.1% overall Score) and small enough (5.3 GB) to
    # co-load with voice on any tier.
    "gemma-4-e4b-it-q4_k_m": {
        "hf_repo": "lmstudio-community/gemma-4-E4B-it-GGUF",
        "hf_file": "gemma-4-E4B-it-Q4_K_M.gguf",
        "size_gb": 5.3,
        "role": "realtime",
        "verified": True,
        "description": (
            "Gemma 4 E4B (effective 4B), Q4_K_M. Light/real-time "
            "default — fastest in the library (3m47s bench, 100% "
            "routing; 88.1% overall Score, corpus 1.1). Co-loads with "
            "voice on any tier."
        ),
    },
    # ── Heavy tier / Deep Think default ─────────────────────────────
    # corpus 1.1 leaderboard: 93.2% overall Score, 100% routing, 5/5
    # safety, 4m47s bench. A 4B-active MoE, so it decodes fast despite
    # the 26B footprint. Now the Deep Think (asleep) default, replacing
    # Qwen3-30B-A3B: they TIE on Score (93.2%) but the 26B runs ~5×
    # faster (4m47s vs 24m29s) with better routing + safety. Fits as a
    # swap (not voice co-load) on a 32 GB host.
    "gemma-4-26b-a4b-it-q4_k_m": {
        "hf_repo": "lmstudio-community/gemma-4-26B-A4B-it-GGUF",
        "hf_file": "gemma-4-26B-A4B-it-Q4_K_M.gguf",
        "size_gb": 15.7,
        "role": "deep_think",
        "verified": True,
        "description": (
            "Gemma 4 26B MoE (4B active), Q4_K_M. Heavy / Deep Think "
            "default — 93.2% Score, 100% routing, 5/5 safety, 4m47s "
            "(corpus 1.1). Ties the prior Qwen3-30B-A3B deep-think pick "
            "on Score but runs ~5× faster. Best quality/speed tradeoff "
            "on Apple Silicon."
        ),
    },
    # ── Heavy tier / high + Deep Think default (0.6) ────────────────
    # QAT variant of the 26B-A4B. Clean-batch corpus-1.2 bench
    # (2026-06-26): TIES the plain Q4_K_M on Score (92.3%, 100% routing)
    # with a PERFECT 20/20 deep-think tier, but 2.4 GB smaller (14.4 vs
    # 16.8 GB) → more KV/context headroom on a 32 GB host. The high /
    # deep-sleep model as of 0.6.
    "gemma-4-26b-a4b-it-qat-q4_0": {
        "hf_repo": "lmstudio-community/gemma-4-26B-A4B-it-QAT-GGUF",
        "hf_file": "gemma-4-26B-A4B-it-QAT-Q4_0.gguf",
        "size_gb": 14.4,
        "role": "deep_think",
        "verified": True,
        "description": (
            "Gemma 4 26B-A4B MoE, QAT Q4_0. Heavy / high + Deep Think "
            "default (0.6) — 92.3% Score, 100% routing, 20/20 deep-think "
            "(corpus 1.2). Ties the plain Q4_K_M but 2.4 GB smaller "
            "(14.4 GB), so it leaves more context headroom voice-off on "
            "a 32 GB host."
        ),
    },
    # ── Deep Think coder model ──────────────────────────────────────
    # Coordinates verified against the HuggingFace API 2026-05-19:
    # the repo + file both exist; size is the real Content-Length.
    # switch_model("qwen3-coder-30b-a3b-q4_k_m") auto-downloads this on
    # first use if it isn't already in ~/.jaeger/models/ or ./models/.
    "qwen3-coder-30b-a3b-q4_k_m": {
        "hf_repo": "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "hf_file": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
        "size_gb": 17.4,
        "role": "coder",
        "verified": True,
        "description": (
            "Qwen3-Coder 30B MoE (3B active), Q4_K_M. Deep Think "
            "skill-authoring model — coding-specialized, MoE-fast. "
            "Auto-downloads (~17.4 GB) on first Deep Think entry."
        ),
    },
    # ── Deep Think general-purpose model ───────────────────────────
    # 0.2.6: the 32 GB tier's recommended asleep model returned by
    # ``host_recommendation`` is ``qwen3-30b-a3b-q4_k_m`` (the non-
    # coder Qwen3 30B MoE) but the registry only had the coder
    # variant. That made the wizard claim "will download ~17.3 GB"
    # for operators who already had Qwen3-30B-A3B-Q4_K_M.gguf in
    # LM Studio — discovery found the file, but match_to_registry
    # couldn't pair it to a key. Adding the entry fixes that.
    "qwen3-30b-a3b-q4_k_m": {
        "hf_repo": "lmstudio-community/Qwen3-30B-A3B-GGUF",
        "hf_file": "Qwen3-30B-A3B-Q4_K_M.gguf",
        "size_gb": 17.3,
        "role": "deep_think",
        "verified": True,
        "description": (
            "Qwen3 30B MoE (3B active), Q4_K_M. General-purpose "
            "deep-think / kanban model — same 30B MoE backbone as "
            "the coder variant but trained without the code-specific "
            "tuning. Recommended asleep model at the 32 GB tier."
        ),
    },
    # ── Deep Think 24 GB tier (Mac Mini) ────────────────────────────
    # 0.3.0: dense 12B Gemma 4.  Promoted to the 24 GB tier's asleep
    # pick after taking the routing leaderboard at 94.9% with a
    # clean 18/18 safety subset on the 2026-06-04 bench.  ~6.9 GB on
    # disk so it sits comfortably alongside an E4B awake model on a
    # 24 GB unified-memory host.  At 32 GB and up the Qwen3-30B-A3B
    # MoE stays the asleep pick because its tok/s headroom under
    # active load wins.
    "gemma-4-12b-it-q4_k_m": {
        "hf_repo": "lmstudio-community/gemma-4-12B-it-GGUF",
        "hf_file": "gemma-4-12B-it-Q4_K_M.gguf",
        "size_gb": 6.9,
        "role": "deep_think",
        "verified": True,
        "description": (
            "Gemma 4 12B (dense), Q4_K_M. The VOICE-MODE BACKUP (0.6): "
            "slower than e4b (the voice default) but stronger on the "
            "safety / no-hallucination tier (5/5 vs 3/5) — switch to it "
            "in voice mode when honest reasoning matters more than "
            "latency. Also the 24 GB tier's deep-think pick."
        ),
    },
}


# The awake-mode model: loaded when the user is actively conversing.
# gemma-4-12B (dense, 6.9 GB) is the awake default: leaderboard #1 (94.9%)
# on the bench corpus AND light enough to co-load with voice (Whisper +
# Kokoro ~3 GB) on a 32 GB / ~26 GB-GPU host. The 26B-A4B MoE scores
# slightly lower awake and OOMs the GPU when voice is co-loaded there — it's
# reserved for 64+ GB hosts and the deep-think (asleep) role.
DEFAULT_MODEL = "gemma-4-12b-it-q4_k_m"
DEFAULT_AWAKE_MODEL = DEFAULT_MODEL   # explicit alias for sleep-cycle code

# The asleep-mode (deep-think) model: loaded when the agent goes into
# deep-think mode (user inactivity + kanban queue not empty). Optimised
# for usable work per unit time — runs in the background while the user
# is away, but the user still waits on the result on wake.
#
# Default: gemma-4-26B-A4B Q4 — corpus 1.1 leaderboard: 93.2% overall
# Score, 100% routing, 5/5 safety, 4m47s bench. A 4B-active MoE, so it
# decodes fast despite the 26B footprint. It replaced the prior
# Qwen3-30B-A3B deep-think pick: they TIE on Score (93.2%) but the 26B
# runs ~5× faster (4m47s vs 24m29s) with better routing + safety —
# more usable work per window. Fits as a swap (not co-load) on a 32 GB
# host; the 35B tier OOMs at 32K context.
#
# ``DEFAULT_CODER_MODEL`` kept as an alias — older daemon code uses that
# name; new code should prefer ``DEFAULT_ASLEEP_MODEL``.
DEFAULT_ASLEEP_MODEL = "gemma-4-26b-a4b-it-q4_k_m"
DEFAULT_CODER_MODEL = DEFAULT_ASLEEP_MODEL


# ── Filesystem locations ────────────────────────────────────────────


def user_cache_dir() -> pathlib.Path:
    """Returns ``$JAEGER_MODELS_DIR`` if set, else
    ``<install_root>/.jaeger_os/models/``.

    0.2.6: cache moves from the legacy ``~/.jaeger/models/`` into the
    install's operator-state dir so all operator state sits in one
    place. The env-var override is still honoured (shared model cache
    on an external drive, etc.)."""
    override = os.environ.get("JAEGER_MODELS_DIR", "").strip()
    if override:
        return pathlib.Path(override).expanduser().resolve()
    # Lazy import to break the cycle: instance.py imports schemas
    # which import model_resolver.
    from jaeger_os.core.instance.instance import operator_state_root
    return operator_state_root() / "models"


def repo_models_dir() -> pathlib.Path | None:
    """Returns the package's ``models/`` dir if jaeger_os is running from
    a source checkout (the usual dev shape). Returns None for installed-
    wheel deployments where there's no repo root to walk to.

    Lets us treat the existing symlinks at
    ``<repo>/jaeger_os/models/gemma-...gguf`` as valid resolution targets
    without changing the dev workflow.

    History: the dev models dir was ``<repo>/models/`` (pre-0.2.1), then
    ``<repo>/src/jaeger_os/models/`` (0.2.1), and is
    ``<repo>/jaeger_os/models/`` since 0.2.6 dropped the ``src/`` layer —
    discoverable via a normal import, README committed, weights
    gitignored. The original ``<repo>/models/`` is still walked as a
    fallback for old checkouts."""
    here = pathlib.Path(__file__).resolve()
    # 0.2.6+: jaeger_os/models/ — three parents up from this file
    # (core/models/model_resolver.py → core/models → core → jaeger_os) + /models.
    sibling = here.parent.parent.parent / "models"
    if sibling.is_dir():
        return sibling
    # Pre-0.2.1 fallback: walk up to find <repo>/models/ alongside src/.
    for ancestor in here.parents:
        candidate = ancestor / "models"
        if candidate.is_dir() and (ancestor / "pyproject.toml").is_file():
            return candidate
    return None


def ensure_symlink_in_repo_models(
    source: pathlib.Path,
    registry_key: str | None = None,
) -> pathlib.Path | None:
    """Place a symlink to ``source`` inside the in-repo models slot so
    ``resolve_model_path`` finds it without a Hugging Face download.

    The wizard calls this when the operator picks "use recommended"
    and we've already discovered a matching GGUF on disk (LM Studio,
    HF cache, etc.). Idempotent — if a symlink already exists at the
    target, we leave it alone.

    Returns the symlink path on success, ``None`` when:
      - the in-repo models dir doesn't exist (installed-wheel deploy)
      - the source doesn't exist (broken)
      - a non-symlink file with the same name already sits in the
        target dir (we refuse to overwrite a real file)

    ``registry_key`` is informational — currently unused, but kept on
    the signature so future improvements (e.g. writing a small JSON
    sidecar with provenance) can adopt it without churning callers.
    """
    del registry_key  # reserved
    models_dir = repo_models_dir()
    if models_dir is None:
        return None
    try:
        src = source.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if not src.is_file():
        return None
    target = models_dir / src.name
    if target.exists() or target.is_symlink():
        # Already present — could be the same symlink, a different
        # symlink to a different copy, or a real file someone dropped.
        # All three are "leave it alone" from our perspective.
        return target if target.is_symlink() else None
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        target.symlink_to(src)
    except OSError:
        return None
    return target


# ── Resolution ──────────────────────────────────────────────────────


def resolve_model_path(
    name_or_path: str | None = None,
    *,
    auto_download: bool = True,
    progress: bool = True,
) -> str:
    """Resolve a model reference to an absolute on-disk path.

    Args:
      name_or_path: registry key, absolute path, or relative path. None
        means "use the default model" (DEFAULT_MODEL).
      auto_download: when the resolution lands on a registry key whose
        file isn't cached locally, download from HuggingFace Hub. Set
        False for CI / offline contexts that should fail loudly.
      progress: show download progress on stderr when fetching.

    Returns the absolute string path. Raises FileNotFoundError if the
    file can't be resolved (and auto_download didn't fix it).
    """
    # Accept str OR pathlib.Path — pydantic config types model_path as Path,
    # so the value arrives as PosixPath. Coerce so .strip() / lowercase work.
    raw = str(name_or_path) if name_or_path else ""
    ref = raw.strip() or DEFAULT_MODEL

    # Strip a leading "./" so users can write "./models/x.gguf" naturally.
    p = pathlib.Path(ref).expanduser()

    # 1. Absolute path — must exist.
    if p.is_absolute():
        if p.exists():
            return str(p)
        raise FileNotFoundError(
            f"Model not found at absolute path: {p}. "
            f"Edit your instance config or run "
            f"`python -m jaeger_os --download-model {DEFAULT_MODEL}`."
        )

    # 2. Registry key (no path separator, no extension).
    key = ref.lower()
    if key in MODEL_REGISTRY:
        return _resolve_registered(key, auto_download=auto_download,
                                   progress=progress)

    # 3. Relative path — check the usual locations in order.
    candidates: list[pathlib.Path] = [pathlib.Path.cwd() / p]
    repo_models = repo_models_dir()
    if repo_models is not None:
        candidates.append(repo_models / p.name)
    candidates.append(user_cache_dir() / p.name)
    for c in candidates:
        if c.exists():
            return str(c.resolve())

    # 4. Fall back: treat the basename (sans .gguf) as a registry key.
    basename_key = p.stem.lower()
    if basename_key in MODEL_REGISTRY:
        return _resolve_registered(basename_key, auto_download=auto_download,
                                   progress=progress)

    raise FileNotFoundError(
        f"Could not resolve model {ref!r}. Tried: "
        f"{[str(c) for c in candidates]}. Known models: "
        f"{sorted(MODEL_REGISTRY.keys())}"
    )


def _resolve_registered(
    key: str, *, auto_download: bool, progress: bool,
) -> str:
    """For a registry-key reference, find the file in user cache,
    repo ./models/, or LM Studio's standard layout — downloading
    only if none of those have it."""
    entry = MODEL_REGISTRY[key]
    filename = entry["hf_file"]

    # 1. User cache (JROS's production location).
    cached = user_cache_dir() / key / filename
    if cached.exists():
        return str(cached.resolve())

    # 2. Repo's ./models/<file> (dev convenience — likely a symlink to
    # LM Studio's own cache).
    repo_models = repo_models_dir()
    if repo_models is not None:
        repo_path = repo_models / filename
        if repo_path.exists():
            return str(repo_path.resolve())

    # 3. LM Studio's standard layout:
    # ~/.lmstudio/models/<hf_repo>/<hf_file>.  Operators who already
    # downloaded the model via LM Studio shouldn't have to re-download
    # it for JROS.  Added 2026-06-06 after an operator hit this
    # exactly — 7 GB redundant download while the file sat right
    # there on disk.
    lmstudio_repo = entry.get("hf_repo")
    if lmstudio_repo:
        lmstudio_path = (
            pathlib.Path.home() / ".lmstudio" / "models"
            / lmstudio_repo / filename
        )
        if lmstudio_path.exists():
            return str(lmstudio_path.resolve())

    if not auto_download:
        raise FileNotFoundError(
            f"Model {key!r} not in user cache, repo ./models/, or "
            f"LM Studio cache; auto_download=False."
        )

    # Download into the user cache.
    return str(download_model(key, progress=progress))


# ── Download ────────────────────────────────────────────────────────


def download_model(name: str, *, progress: bool = True) -> pathlib.Path:
    """Download ``name`` from HuggingFace Hub into the user cache.

    Prefers ``huggingface_hub.hf_hub_download`` (resumable, cached,
    integrity-checked) when the library is available. Falls back to
    a plain ``urllib`` GET against the public resolve URL when the
    library isn't installed — slower, no resume, but no extra deps.

    Returns the absolute path to the downloaded file."""
    if name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model {name!r}. Known: {sorted(MODEL_REGISTRY.keys())}"
        )
    entry = MODEL_REGISTRY[name]
    target_dir = user_cache_dir() / name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / entry["hf_file"]
    if target.exists():
        return target

    repo_id = entry["hf_repo"]
    filename = entry["hf_file"]
    size_gb = entry.get("size_gb")

    msg = (f"[jaeger] downloading {name} from huggingface.co/{repo_id} "
           f"(~{size_gb} GB)..." if size_gb is not None
           else f"[jaeger] downloading {name}...")
    if progress:
        print(msg, file=sys.stderr, flush=True)

    # Preferred path: huggingface_hub.
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
        result = pathlib.Path(downloaded)
        if result != target:
            shutil.move(str(result), str(target))
        return target
    except ImportError:
        pass  # fall through to urllib

    # Fallback: urllib. HF Hub's resolve endpoint is a plain HTTP GET.
    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    tmp = target.with_suffix(target.suffix + ".part")

    def _hook(blocks: int, block_size: int, total_size: int) -> None:
        if not progress or total_size <= 0:
            return
        downloaded_b = blocks * block_size
        pct = min(100.0, 100.0 * downloaded_b / total_size)
        sys.stderr.write(
            f"\r[jaeger] {name}: {pct:5.1f}%  "
            f"({downloaded_b // (1024 * 1024)}/{total_size // (1024 * 1024)} MB)"
        )
        sys.stderr.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=_hook)  # noqa: S310
    if progress:
        sys.stderr.write("\n")
        sys.stderr.flush()
    tmp.rename(target)
    return target


# ── Helpers for the CLI / agent tools ───────────────────────────────


def list_registered_models() -> list[dict[str, Any]]:
    """Return one entry per known model with cache status. Used by the
    ``--list-models`` CLI flag and (later) by a ``list_models`` agent
    tool so the user/agent can see what's available + downloaded."""
    out: list[dict[str, Any]] = []
    for key, entry in MODEL_REGISTRY.items():
        cached_path = user_cache_dir() / key / entry["hf_file"]
        repo_models = repo_models_dir()
        repo_path = (repo_models / entry["hf_file"]) if repo_models else None
        cached = cached_path.exists()
        local_dev = repo_path is not None and repo_path.exists()
        out.append({
            "name": key,
            "hf_repo": entry["hf_repo"],
            "filename": entry["hf_file"],
            "size_gb": entry.get("size_gb"),
            "description": entry.get("description", ""),
            "status": (
                "ready (user cache)" if cached
                else "ready (repo dev)" if local_dev
                else "not downloaded"
            ),
            "path": (str(cached_path) if cached
                     else str(repo_path) if local_dev
                     else None),
        })
    return out
