"""Discover GGUF model files already on the host filesystem.

The setup wizard uses this to avoid forcing operators to download a
15+ GB model from Hugging Face when the same file is sitting in their
LM Studio cache, their Hugging Face cache, or any other folder where
they already keep GGUFs.

Resolution philosophy: discovery is **read-only and best-effort**.
The wizard surfaces what it finds; the operator picks. If a scan
path doesn't exist or isn't readable, it's silently skipped — the
wizard still works against the empty result. Never raise from a scan
path that just happens to be missing.

Scan order (deduped, first hit wins for any given filename):

  1. ``JAEGER_MODEL_SCAN_PATHS`` env var (colon-separated, override)
  2. ``~/.jaeger/models/`` (JROS production cache)
  3. ``<repo>/src/jaeger_os/models/`` (in-tree dev / symlink slot)
  4. ``~/.lmstudio/models/`` (LM Studio default)
  5. ``~/Library/Application Support/LM Studio/models/`` (macOS alt)
  6. ``~/.cache/lm-studio/models/`` (legacy LM Studio)
  7. ``~/.cache/huggingface/hub/`` (Hugging Face Hub cache)
  8. ``~/Models/`` (generic catch-all)

The first path that hits a given GGUF filename wins, so the JROS-
owned locations rank above third-party caches — if a user has the
same file in both ``~/.jaeger/models/`` and LM Studio, the JROS
copy is reported.

Returned ``DiscoveredModel`` records carry ``path`` (absolute,
symlink-resolved), ``size_gb`` (real bytes), and ``source`` (a
human label like ``"LM Studio"`` or ``"Hugging Face cache"``).
``match_to_registry()`` maps these against ``MODEL_REGISTRY`` by
filename so the wizard can annotate the recommended-model option
with "✓ found locally" when the file already exists.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Iterable


# ── Scan-path definitions ────────────────────────────────────────────


# (path-template, human-readable source label). Path-templates may
# include ``~`` — they're expanded via ``Path.expanduser()`` at scan
# time. Order matters: earlier entries win when the same filename
# appears in multiple locations.
# 0.2.6: ``~/.jaeger/models`` is gone — the JROS-owned cache moved into
# ``<install_root>/.jaeger_os/models``. Added at scan time by
# ``scan_paths()`` since it depends on the runtime install root, not
# a static template.
_DEFAULT_SCAN_PATHS: list[tuple[str, str]] = [
    ("~/.lmstudio/models",                          "LM Studio"),
    ("~/Library/Application Support/LM Studio/models", "LM Studio"),
    ("~/.cache/lm-studio/models",                   "LM Studio (legacy)"),
    ("~/.cache/huggingface/hub",                    "Hugging Face cache"),
    ("~/Models",                                    "~/Models"),
]


def _env_override_paths() -> list[tuple[str, str]]:
    """Parse ``JAEGER_MODEL_SCAN_PATHS`` (colon-separated) into entries
    we can scan. Empty / unset → empty list."""
    raw = os.environ.get("JAEGER_MODEL_SCAN_PATHS", "").strip()
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for chunk in raw.split(":"):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Use the path itself as the source label — operators who set
        # the env var generally want to see the literal dir they picked.
        out.append((chunk, chunk))
    return out


def _in_tree_models_path() -> tuple[str, str] | None:
    """Locate the framework's ``jaeger_os/models/`` dir (where the
    wizard auto-symlinks discovered GGUFs). 0.2.6: lives directly
    inside the package after the src/ prefix was dropped."""
    here = pathlib.Path(__file__).resolve()
    # core/models/local_discovery.py → core/.. → jaeger_os/models
    candidate = here.parent.parent.parent / "models"
    if candidate.is_dir():
        return (str(candidate), "JROS in-tree (dev)")
    return None


def _operator_state_models_path() -> tuple[str, str] | None:
    """The 0.2.6 operator-state cache at
    ``<install_root>/.jaeger_os/models/``. Lazy-imported to avoid
    circular dependency on instance.py at module load."""
    try:
        from jaeger_ai.core.instance.instance import operator_state_root
    except ImportError:
        return None
    candidate = operator_state_root() / "models"
    if candidate.is_dir():
        return (str(candidate), "JROS cache")
    return None


def scan_paths() -> list[tuple[pathlib.Path, str]]:
    """Build the de-duplicated, expanded list of (path, label) pairs
    that will be scanned. Honours the env-var override and adds the
    in-tree + operator-state dev slots when applicable.

    Paths that don't exist are dropped here so callers don't repeat
    that check. Same path under multiple labels collapses to the
    first label seen — keeps the discover output tidy."""
    entries: list[tuple[str, str]] = []
    entries.extend(_env_override_paths())

    op_state = _operator_state_models_path()
    if op_state is not None:
        entries.append(op_state)

    in_tree = _in_tree_models_path()
    if in_tree is not None:
        entries.append(in_tree)

    entries.extend(_DEFAULT_SCAN_PATHS)

    seen: set[pathlib.Path] = set()
    resolved: list[tuple[pathlib.Path, str]] = []
    for raw, label in entries:
        try:
            p = pathlib.Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if not p.is_dir():
            continue
        if p in seen:
            continue
        seen.add(p)
        resolved.append((p, label))
    return resolved


# ── Discovery ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveredModel:
    """One GGUF file found on disk by the scanner."""
    path: pathlib.Path           # absolute, symlinks NOT followed (.resolve() of name only)
    size_gb: float               # real bytes / 1e9; -1.0 if stat failed
    source: str                  # human label: "LM Studio", "JROS cache", etc.

    @property
    def filename(self) -> str:
        return self.path.name


def _safe_size_gb(p: pathlib.Path) -> float:
    """Resolve through symlinks for size; -1.0 on any stat failure
    (broken symlink, permission denied, race)."""
    try:
        return p.stat().st_size / 1_000_000_000
    except OSError:
        return -1.0


def _iter_gguf_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    """Recursively yield ``*.gguf`` files under ``root``.

    Walks errors are swallowed — discovery is best-effort. Symlinks
    to files are yielded (LM Studio uses them); symlinks to dirs are
    followed via ``rglob`` so e.g. an in-tree models/ symlink to a
    cached weight still gets picked up.
    """
    try:
        yield from (p for p in root.rglob("*.gguf") if p.is_file())
    except (OSError, PermissionError):
        return


def discover_local_gguf_files() -> list[DiscoveredModel]:
    """Scan well-known paths for GGUF model files.

    Returns a deduplicated list — same filename in two scan paths
    only appears once, with the source from whichever path ranked
    higher (env override → in-tree → JROS cache → LM Studio → …).
    Sorted by filename for stable, predictable wizard output.
    """
    found: dict[str, DiscoveredModel] = {}
    for root, label in scan_paths():
        for gguf in _iter_gguf_files(root):
            name = gguf.name
            if name in found:
                continue  # first-hit wins
            found[name] = DiscoveredModel(
                path=gguf.resolve(),
                size_gb=_safe_size_gb(gguf),
                source=label,
            )
    return sorted(found.values(), key=lambda d: d.filename.lower())


# ── Registry matching ───────────────────────────────────────────────


def match_to_registry(
    discovered: list[DiscoveredModel],
) -> dict[str, DiscoveredModel]:
    """Map registry keys to the first discovered GGUF whose filename
    matches the registry entry's ``hf_file``.

    The wizard uses this to mark the recommended-model option with
    "✓ found locally" — and to skip the Hugging Face download when
    the operator picks it. Match is by basename only; symlink
    targets are followed for the actual on-disk size.

    Imports ``MODEL_REGISTRY`` lazily so this module stays cheap to
    import (the registry pulls in HF download URL constants).
    """
    from jaeger_ai.core.models.model_resolver import MODEL_REGISTRY

    by_filename: dict[str, DiscoveredModel] = {
        d.filename: d for d in discovered
    }

    matched: dict[str, DiscoveredModel] = {}
    for key, info in MODEL_REGISTRY.items():
        target = info.get("hf_file")
        if target and target in by_filename:
            matched[key] = by_filename[target]
    return matched
