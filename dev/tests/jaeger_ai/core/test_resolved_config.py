"""F01 — StatePaths + ResolvedRuntimeConfig (release convergence, M1.1).

``docs/architecture/RELEASE_AGENT_PROMPT.md`` section 7 / M1.1: an immutable
``StatePaths`` value, resolved with no I/O, and a resolved application
configuration snapshot that defensively copies the existing serialized
``Config`` so a later live edit cannot perturb an already-captured view.

These are new, additive types — see ``jaeger_ai/core/instance/instance.py``
(``StatePaths``) and ``jaeger_ai/core/instance/resolved_config.py``
(``ResolvedRuntimeConfig``). Neither migrates ``operator_state_root()``'s
existing 84 call sites; that remains explicitly out of scope (see the
external checkpoint / CONVERGENCE.md's 2026-09-22 continuation).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from jaeger_ai.core.instance.instance import (
    OPERATOR_STATE_DIR_NAME,
    StatePaths,
    is_source_checkout,
    operator_state_root,
)
from jaeger_ai.core.instance.resolved_config import ResolvedRuntimeConfig
from jaeger_ai.core.instance.schemas import Config, ModelConfig


def _minimal_config(instance_name: str = "fresh") -> Config:
    return Config(instance_name=instance_name, model=ModelConfig(model_path="/dev/null"))


# ── StatePaths: pure resolution ──────────────────────────────────────


def test_resolve_is_pure_no_directory_created(tmp_path, monkeypatch):
    target = tmp_path / "state-root"
    monkeypatch.setenv("JAEGER_STATE_DIR", str(target))
    monkeypatch.delenv("JAEGER_HOME", raising=False)

    paths = StatePaths.resolve()

    assert paths.state_root == target.resolve()
    assert not target.exists(), "StatePaths.resolve() must perform no I/O"


def test_ensure_creates_the_directory_and_returns_self(tmp_path, monkeypatch):
    target = tmp_path / "state-root"
    monkeypatch.setenv("JAEGER_STATE_DIR", str(target))
    monkeypatch.delenv("JAEGER_HOME", raising=False)

    paths = StatePaths.resolve()
    returned = paths.ensure()

    assert returned is paths
    assert target.is_dir()


def test_precedence_state_dir_beats_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))

    paths = StatePaths.resolve()

    assert paths.state_root == (tmp_path / "state").resolve()
    assert paths.source == "JAEGER_STATE_DIR"


def test_precedence_home_appends_operator_state_dir_name(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))

    paths = StatePaths.resolve()

    assert paths.state_root == (tmp_path / "home" / OPERATOR_STATE_DIR_NAME).resolve()
    assert paths.source == "JAEGER_HOME"


def test_precedence_default_is_home_dot_jaeger(monkeypatch):
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_HOME", raising=False)

    paths = StatePaths.resolve()

    assert paths.state_root == (Path.home() / ".jaeger").resolve()
    assert paths.source == "default"


def test_blank_overrides_are_ignored_like_the_legacy_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", "   ")
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))

    paths = StatePaths.resolve()

    assert paths.source == "JAEGER_HOME"


def test_resolve_matches_operator_state_root_for_explicit_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("JAEGER_HOME", raising=False)

    assert StatePaths.resolve().state_root == operator_state_root()


def test_resolve_matches_operator_state_root_for_home_override(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))

    assert StatePaths.resolve().state_root == operator_state_root()


def test_derived_paths_are_under_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))

    paths = StatePaths.resolve()

    assert paths.instances_root == paths.state_root / "instances"
    assert paths.active_instance_file == paths.state_root / "active_instance"


def test_explicit_env_mapping_overrides_os_environ(monkeypatch, tmp_path):
    """An explicit ``env`` mapping is honored even if the real process
    environment says something else — useful for admission-time snapshots
    that must not depend on ambient global state."""
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "real-env"))

    paths = StatePaths.resolve(env={"JAEGER_STATE_DIR": str(tmp_path / "injected")})

    assert paths.state_root == (tmp_path / "injected").resolve()


def test_state_paths_is_frozen():
    paths = StatePaths(state_root=Path("/tmp/x"), source="default")
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.state_root = Path("/tmp/y")  # type: ignore[misc]


# ── is_source_checkout / reject_source_checkouts (A02 hazard) ───────


def test_is_source_checkout_detects_this_repo():
    repo_root = Path(__file__).resolve().parents[4]
    assert (repo_root / ".git").exists()
    assert (repo_root / "pyproject.toml").is_file()

    found = is_source_checkout(repo_root / "jaeger_ai" / "core" / "instance")

    assert found == repo_root


def test_is_source_checkout_none_for_an_ordinary_directory(tmp_path):
    plain = tmp_path / "not-a-checkout"
    plain.mkdir()
    assert is_source_checkout(plain) is None


def test_is_source_checkout_requires_both_git_and_pyproject(tmp_path):
    """A bare ``.git`` directory alone (an operator's dotfiles/notes repo,
    say) must not be flagged — only an actual Python project checkout."""
    only_git = tmp_path / "just-git"
    only_git.mkdir()
    (only_git / ".git").mkdir()
    assert is_source_checkout(only_git) is None

    only_pyproject = tmp_path / "just-pyproject"
    only_pyproject.mkdir()
    (only_pyproject / "pyproject.toml").write_text("", encoding="utf-8")
    assert is_source_checkout(only_pyproject) is None


def test_is_source_checkout_canonicalizes_symlinks(tmp_path):
    real_checkout = tmp_path / "real-checkout"
    real_checkout.mkdir()
    (real_checkout / ".git").mkdir()
    (real_checkout / "pyproject.toml").write_text("", encoding="utf-8")

    alias = tmp_path / "alias"
    alias.symlink_to(real_checkout, target_is_directory=True)

    found = is_source_checkout(alias / "some" / "nested" / "path")

    assert found == real_checkout.resolve()


def test_resolve_reject_source_checkouts_raises_for_jaeger_home_inside_a_checkout(tmp_path):
    checkout = tmp_path / "opt-jaeger"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / "pyproject.toml").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="inside a source checkout"):
        StatePaths.resolve(
            env={"JAEGER_HOME": str(checkout)},
            reject_source_checkouts=True,
        )


def test_resolve_reject_source_checkouts_defaults_to_off_for_compat(tmp_path):
    """``operator_state_root()``'s 84 existing call sites are not migrated
    to this check yet — the default must stay permissive."""
    checkout = tmp_path / "opt-jaeger"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / "pyproject.toml").write_text("", encoding="utf-8")

    paths = StatePaths.resolve(env={"JAEGER_HOME": str(checkout)})

    assert paths.state_root == (checkout / OPERATOR_STATE_DIR_NAME).resolve()


def test_resolve_reject_source_checkouts_allows_a_clean_state_dir(tmp_path):
    clean = tmp_path / "clean-state"
    paths = StatePaths.resolve(
        env={"JAEGER_STATE_DIR": str(clean)},
        reject_source_checkouts=True,
    )
    assert paths.state_root == clean.resolve()


# ── ResolvedRuntimeConfig: defensive snapshot ────────────────────────


def test_capture_snapshots_a_deep_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    config = _minimal_config()
    paths = StatePaths.resolve()

    snapshot = ResolvedRuntimeConfig.capture(config, paths)

    assert snapshot.config.instance_name == "fresh"
    assert snapshot.state_paths == paths
    assert isinstance(snapshot.captured_at, float)


def test_mutating_the_original_config_after_capture_does_not_affect_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    config = _minimal_config()
    paths = StatePaths.resolve()

    snapshot = ResolvedRuntimeConfig.capture(config, paths)

    # Live mutation, mirroring a supported runtime edit (e.g. the TUI's
    # /voice command mutating VoiceConfig fields on the operator's live
    # Config object).
    config.instance_name = "mutated-after-capture"
    config.runtime.gguf_engine = "llama-cpp-python"

    assert snapshot.config.instance_name == "fresh"
    assert snapshot.config.runtime.gguf_engine == "auto"


def test_resolved_runtime_config_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    snapshot = ResolvedRuntimeConfig.capture(_minimal_config(), StatePaths.resolve())

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.config = _minimal_config("other")  # type: ignore[misc]


def test_existing_runtime_config_fields_are_preserved_through_capture(tmp_path, monkeypatch):
    """A05 (RELEASE_AUDIT.md): ``schemas.RuntimeConfig`` (inference-engine
    selection) is a distinct, pre-existing type this snapshot must not
    replace or reinterpret — it must simply be carried through untouched."""
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    config = _minimal_config()
    config.runtime.mlx_engine = "mlx-vlm"

    snapshot = ResolvedRuntimeConfig.capture(config, StatePaths.resolve())

    assert snapshot.config.runtime.mlx_engine == "mlx-vlm"
    assert snapshot.config.runtime.gguf_engine == "auto"
    assert type(snapshot.config.runtime).__name__ == "RuntimeConfig"
