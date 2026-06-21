"""Unit tests for ``core/models/local_discovery``.

Discovery is filesystem-driven, so the tests build a tmp_path tree that
mimics the LM Studio / HF cache shapes, set ``JAEGER_MODEL_SCAN_PATHS``
to point at it, and assert what comes back. No real LM Studio install
is touched.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from jaeger_os.core.models import local_discovery as ld


# ── helpers ──────────────────────────────────────────────────────────


def _make_gguf(p: pathlib.Path, size_bytes: int = 1024) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size_bytes)
    return p


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Wipe every default scan path so only env-pointed dirs are seen.

    Also points $HOME at a tmp dir so the ``~`` expansions in the
    default scan-path list don't accidentally pick up the developer's
    real LM Studio cache.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.delenv("JAEGER_MODEL_SCAN_PATHS", raising=False)
    # Disable the in-tree dev path too — _in_tree_models_path resolves
    # via __file__, which still points at the real repo. Monkeypatch it.
    monkeypatch.setattr(ld, "_in_tree_models_path", lambda: None)
    # 2026-06-07: also isolate _operator_state_models_path.  It
    # resolves to ``<repo>/.jaeger_os/models/`` which is where
    # JROS caches downloaded GGUFs — once an operator downloads
    # ANY model, this path goes non-empty and tests that assume
    # discovery returns nothing start failing.  Mock to None so
    # the operator's real cache never leaks into the test scan.
    monkeypatch.setattr(ld, "_operator_state_models_path", lambda: None)
    return tmp_path


# ── scan_paths() ─────────────────────────────────────────────────────


def test_scan_paths_skips_missing_dirs(isolated_env):
    """All default paths point at ``~`` which we just redirected to a
    tmp dir — none of them exist, so the scan list is empty."""
    paths = ld.scan_paths()
    assert paths == []


def test_scan_paths_honours_env_override(isolated_env, monkeypatch, tmp_path):
    cache = tmp_path / "my-models"
    cache.mkdir()
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(cache))
    paths = ld.scan_paths()
    assert len(paths) == 1
    assert paths[0][0] == cache.resolve()
    assert paths[0][1] == str(cache)  # label echoes the literal path


def test_scan_paths_dedupes_overlap(isolated_env, monkeypatch, tmp_path):
    cache = tmp_path / "shared"
    cache.mkdir()
    # Same dir in env override AND a default — should appear once
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", f"{cache}:{cache}")
    paths = ld.scan_paths()
    assert len(paths) == 1


# ── discover_local_gguf_files() ──────────────────────────────────────


def test_discover_finds_ggufs_recursively(isolated_env, monkeypatch, tmp_path):
    root = tmp_path / "lm-studio"
    _make_gguf(root / "vendor/model-a/model-a.gguf", 2_000_000_000)
    _make_gguf(root / "vendor/model-b/v2/model-b.gguf", 500_000_000)
    _make_gguf(root / "not-a-gguf.bin")  # decoy
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(root))

    discovered = ld.discover_local_gguf_files()
    names = {d.filename for d in discovered}
    assert names == {"model-a.gguf", "model-b.gguf"}


def test_discover_reports_size_in_gb(isolated_env, monkeypatch, tmp_path):
    root = tmp_path / "models"
    _make_gguf(root / "small.gguf", 1_500_000_000)  # 1.5 GB
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(root))
    discovered = ld.discover_local_gguf_files()
    assert len(discovered) == 1
    assert discovered[0].size_gb == pytest.approx(1.5, rel=0.01)


def test_discover_first_hit_wins_for_dup_filename(isolated_env, monkeypatch,
                                                  tmp_path):
    """Two scan dirs both contain ``shared.gguf``; the earlier dir wins
    and its source label is reported."""
    a = tmp_path / "first"
    b = tmp_path / "second"
    _make_gguf(a / "shared.gguf", 1_000_000)
    _make_gguf(b / "shared.gguf", 2_000_000)
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", f"{a}:{b}")
    discovered = ld.discover_local_gguf_files()
    assert len(discovered) == 1
    assert discovered[0].source == str(a)  # env-override label is the path itself
    # Size matches the FIRST one (1 MB), not the second
    assert discovered[0].size_gb < 0.01


def test_discover_empty_when_no_paths_exist(isolated_env):
    """Default scan paths all under fake $HOME — empty result."""
    assert ld.discover_local_gguf_files() == []


def test_discover_returns_sorted(isolated_env, monkeypatch, tmp_path):
    root = tmp_path / "m"
    _make_gguf(root / "z.gguf")
    _make_gguf(root / "a.gguf")
    _make_gguf(root / "M.gguf")
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(root))
    discovered = ld.discover_local_gguf_files()
    names = [d.filename for d in discovered]
    # Case-insensitive sort
    assert names == ["a.gguf", "M.gguf", "z.gguf"]


# ── match_to_registry() ──────────────────────────────────────────────


def test_match_to_registry_pairs_by_hf_filename(isolated_env, monkeypatch,
                                                tmp_path):
    """A discovered file whose name equals the registry's ``hf_file``
    field gets matched to that registry key."""
    from jaeger_os.core.models.model_resolver import MODEL_REGISTRY

    # Pick the first registry entry as our reference
    key, info = next(iter(MODEL_REGISTRY.items()))
    target_filename = info["hf_file"]

    root = tmp_path / "models"
    _make_gguf(root / target_filename, 1024)
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(root))

    discovered = ld.discover_local_gguf_files()
    matched = ld.match_to_registry(discovered)
    assert key in matched
    assert matched[key].filename == target_filename


def test_match_to_registry_returns_empty_when_no_overlap(isolated_env,
                                                        monkeypatch, tmp_path):
    root = tmp_path / "m"
    _make_gguf(root / "totally-unknown.gguf")
    monkeypatch.setenv("JAEGER_MODEL_SCAN_PATHS", str(root))
    discovered = ld.discover_local_gguf_files()
    assert ld.match_to_registry(discovered) == {}


# ── DiscoveredModel dataclass ────────────────────────────────────────


def test_discovered_model_filename_property(tmp_path):
    p = tmp_path / "x" / "test.gguf"
    p.parent.mkdir()
    p.write_text("")
    d = ld.DiscoveredModel(path=p, size_gb=0.1, source="test")
    assert d.filename == "test.gguf"


def test_discovered_model_is_frozen():
    """Hashable + immutable so it can live in sets / dict keys."""
    p = pathlib.Path("/tmp/x.gguf")
    d = ld.DiscoveredModel(path=p, size_gb=1.0, source="s")
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
        d.size_gb = 2.0  # type: ignore[misc]
