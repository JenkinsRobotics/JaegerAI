"""Resolver + wheel-cleanliness — HYGIENE-4/5 + INST-1/-10.

0.1.0 lost data both ways: the bundled dir won over ``~/.jaeger/``
whenever it was writable (which is always, on a normal pip install),
and the wheel itself shipped packager-machine state. HYGIENE-4
swapped the priority; INST-10 (0.2.0) dropped the bundled dir
entirely and INST-1 nested instances under ``~/.jaeger/instances/``.
These tests pin the post-INST-1/-10 resolver shape.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from jaeger_ai.core.instance import instance as instance_module


def test_installed_wheel_keeps_checkout_separate_from_state(tmp_path, monkeypatch):
    checkout = tmp_path / "source"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: /external/worktree\n")
    monkeypatch.setenv("JAEGER_INSTALL_ROOT", str(checkout))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "legacy-state"))
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT",
                        tmp_path / "venv/lib/python3.11/site-packages/jaeger_ai")
    assert instance_module.is_pip_installed()
    assert instance_module.install_root() == checkout
    assert instance_module.detect_install_method() == "dev-checkout"
    assert instance_module.operator_state_root() == tmp_path / "state"
    (checkout / ".jaeger-product-install").touch()
    assert instance_module.detect_install_method() == "product-checkout"


def test_state_override_cannot_become_update_destination(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_INSTALL_ROOT", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", tmp_path / "source/jaeger_ai")
    assert instance_module.install_root() == tmp_path / "source"
from jaeger_ai.core.instance import legacy_state


# ── INST-1: resolver priority ───────────────────────────────────────


def test_env_var_override_always_wins(tmp_path, monkeypatch):
    """`JAEGER_INSTANCE_DIR` (priority 2 — explicit path) bypasses all
    nesting / sticky / env-name logic. Used by the dev sandbox and
    by tests that want a throwaway location."""
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(target))
    resolved = instance_module.resolve_instance_dir("default")
    assert resolved == target.resolve()


def test_dev_checkout_uses_user_instances_root(monkeypatch):
    """When the package is NOT under site-packages AND no override is
    set, the resolver returns ``~/.jaeger/instances/<name>/``. The
    0.1.0-style bundled fallback at ``src/jaeger_os/instance/<name>/``
    is gone (INST-10)."""
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)
    assert instance_module.is_pip_installed() is False, (
        "test environment looks like site-packages — adjust fixture"
    )
    resolved = instance_module.resolve_instance_dir("default")
    expected = (instance_module.user_instances_root() / "default").resolve()
    assert resolved == expected


def test_pip_install_uses_user_instances_root(tmp_path, monkeypatch):
    """When PACKAGE_ROOT sits under a ``site-packages`` component, the
    resolver MUST pick ``~/.jaeger/instances/<name>/``. Site-packages
    is never written into."""
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    fake_pkg = tmp_path / "venv" / "lib" / "python3.11" / "site-packages" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("JAEGER_HOME", str(fake_home))
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)

    assert instance_module.is_pip_installed() is True
    resolved = instance_module.resolve_instance_dir("default")
    expected = (fake_home / ".jaeger_ai" / "instances" / "default").resolve()
    assert resolved == expected


def test_pip_install_detection_catches_dist_packages(tmp_path, monkeypatch):
    """Debian-style installs put the package under ``dist-packages``;
    that path component should be flagged too."""
    fake_pkg = tmp_path / "usr" / "lib" / "python3" / "dist-packages" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)
    assert instance_module.is_pip_installed() is True


def test_editable_install_still_treated_as_dev(tmp_path, monkeypatch):
    """``pip install -e .`` points the package back at the source
    checkout — no ``site-packages`` ancestor, so it must NOT trigger
    the pip-install branch (the resolver returns the same
    user-instances path either way; this test pins the detection)."""
    fake_pkg = tmp_path / "GITHUB" / "JaegerAI" / "jaeger_os"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(instance_module, "PACKAGE_ROOT", fake_pkg, raising=True)
    assert instance_module.is_pip_installed() is False


# ── INST-1: active_instance sticky file ─────────────────────────────


def test_default_instance_name_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    assert instance_module.default_instance_name() == "default"


def test_default_instance_name_reads_active_instance_file(monkeypatch, tmp_path):
    """``~/.jaeger/active_instance`` overrides the literal default
    when no env var is set."""
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_ai").mkdir()
    (tmp_path / ".jaeger_ai" / "active_instance").write_text("work\n",
                                                          encoding="utf-8")
    assert instance_module.default_instance_name() == "work"


def test_env_var_beats_active_instance_file(monkeypatch, tmp_path):
    """If both the env var and the sticky file are set, the env var
    wins — explicit (in-shell) beats implicit (on-disk)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_ai").mkdir()
    (tmp_path / ".jaeger_ai" / "active_instance").write_text("sticky-name\n",
                                                          encoding="utf-8")
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "env-name")
    assert instance_module.default_instance_name() == "env-name"


def test_write_active_instance_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    instance_module.write_active_instance("work")
    assert (tmp_path / ".jaeger_ai" / "active_instance").read_text().strip() == "work"


def test_legacy_operator_state_migrates_without_data_loss(monkeypatch, tmp_path):
    legacy = tmp_path / legacy_state._LEGACY_STATE_DIR_NAME
    legacy.mkdir()
    (legacy / "active_instance").write_text("work\n", encoding="utf-8")
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    destination = instance_module.operator_state_root()

    assert destination == tmp_path / ".jaeger_ai"
    assert (destination / "active_instance").read_text(encoding="utf-8").strip() == "work"
    # F04: the legacy directory is left intact (no compatibility symlink —
    # nothing reads the old path once the destination is active).
    assert not legacy.is_symlink()
    assert (legacy / "active_instance").read_text(encoding="utf-8").strip() == "work"
    assert instance_module.operator_state_root() == destination


def test_write_active_instance_none_removes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_ai").mkdir()
    (tmp_path / ".jaeger_ai" / "active_instance").write_text("work\n",
                                                          encoding="utf-8")
    instance_module.write_active_instance(None)
    assert not (tmp_path / ".jaeger_ai" / "active_instance").exists()


def test_read_active_instance_treats_whitespace_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_ai").mkdir()
    (tmp_path / ".jaeger_ai" / "active_instance").write_text("   \n  \n",
                                                          encoding="utf-8")
    assert instance_module.read_active_instance() is None


# ── INST-10: wheel-cleanliness audit (post-instance-dir-removal) ────


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").exists() and (ancestor / "dev" / "scripts").exists():
            return ancestor
    raise RuntimeError("could not locate repo root from test file")


REPO_ROOT = _find_repo_root()


@pytest.fixture(scope="module")
def check_wheel_module():
    """Import ``dev/scripts/check_wheel.py`` without dragging it onto the
    install path — the script is intentionally not under ``src/``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_wheel", REPO_ROOT / "dev" / "scripts" / "check_wheel.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_fake_wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)


def test_check_wheel_passes_when_no_instance_dir_in_wheel(tmp_path, check_wheel_module):
    """0.2.0 wheels MUST NOT contain a ``jaeger_os/instance/`` dir at
    all (INST-10). A wheel that only ships the framework code passes."""
    wheel = tmp_path / "clean-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/__init__.py": b"",
            "jaeger_os/main.py": b"# entry",
            "jaeger_os/core/instance/__init__.py": b"",
        },
    )
    assert check_wheel_module.check_wheel(wheel) == []


@pytest.mark.parametrize(
    "leaked",
    [
        "jaeger_os/instance/.gitignore",          # the parent file is gone too
        "jaeger_os/instance/README.md",
        "jaeger_os/instance/default/config.yaml",
        "jaeger_os/instance/default/identity.yaml",
        "jaeger_os/instance/default/memory/.gitkeep",
        "jaeger_os/instance/default/skills/some_skill.py",
        "jaeger_os/instance/default/run/jaeger.pid",
    ],
)
def test_check_wheel_flags_anything_under_instance_prefix(
    tmp_path, check_wheel_module, leaked,
):
    """Post-INST-10 the allow-list is empty — ANYTHING under
    ``jaeger_os/instance/`` is a regression."""
    wheel = tmp_path / "dirty-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/__init__.py": b"",
            leaked: b"banned",
        },
    )
    assert check_wheel_module.check_wheel(wheel) == [leaked]


def test_check_wheel_main_returns_nonzero_on_dirty(tmp_path, check_wheel_module, capsys):
    wheel = tmp_path / "dirty-1.0-py3-none-any.whl"
    _build_fake_wheel(
        wheel,
        {
            "jaeger_os/instance/default/config.yaml": b"# leftover",
        },
    )
    code = check_wheel_module.main(["check_wheel.py", str(wheel)])
    assert code == 1
    err = capsys.readouterr().err
    assert "config.yaml" in err


# ── F02: import purity (release convergence, RELEASE_AUDIT.md A02) ──


def test_importing_instance_module_creates_no_state_directory(tmp_path):
    """Merely importing ``instance.py`` must never resolve or create the
    operator state root. A prior revision assigned a module-level
    ``USER_ROOT = operator_state_root()`` with zero internal or external
    readers (confirmed dead: no callsite anywhere in the tree imported
    ``USER_ROOT``) — a pure import triggered ``mkdir`` and potential legacy
    migration purely as an unused side effect. This runs a real fresh
    subprocess (not just ``importlib.reload`` in-process) so no already-
    imported module or conftest env override can mask the regression.
    """
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("JAEGER_HOME", None)
    env.pop("JAEGER_STATE_DIR", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("JAEGER_NO_ATTACH", None)
    result = subprocess.run(
        [sys.executable, "-c", "import jaeger_ai.core.instance.instance"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not (home / ".jaeger").exists(), (
        "importing instance.py created ~/.jaeger — resolution is not pure"
    )


def test_pytest_fallback_state_dir_is_stable_but_not_a_shared_fixed_path(
    monkeypatch, tmp_path,
):
    """The pytest-context fallback (no explicit override, but
    ``PYTEST_CURRENT_TEST`` set) must still return the *same* directory on
    repeated calls within one process — callers rely on a stable root for
    the run — but must not be the old hardcoded ``/tmp/jaeger_test_state``,
    which let concurrent test processes on the same machine race on one
    shared directory.
    """
    monkeypatch.delenv("JAEGER_HOME", raising=False)
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic::case")
    monkeypatch.setattr(instance_module, "_PROCESS_TEST_STATE_DIR", None)

    first = instance_module.operator_state_root()
    second = instance_module.operator_state_root()

    assert first == second
    assert first != Path("/tmp/jaeger_test_state")
    assert first.is_dir()


# ── F02: JAEGER_HOME pointing into a source checkout fails loudly (A02) ──


def _fake_checkout(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    return root


def test_jaeger_home_inside_a_checkout_raises_instead_of_nesting_state(monkeypatch, tmp_path):
    checkout = _fake_checkout(tmp_path / "opt-jaeger")
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(checkout))

    with pytest.raises(RuntimeError, match="inside a source checkout"):
        instance_module.operator_state_root()

    assert not (checkout / instance_module.OPERATOR_STATE_DIR_NAME).exists()


def test_explicit_state_dir_is_never_second_guessed_by_the_checkout_guard(monkeypatch, tmp_path):
    checkout = _fake_checkout(tmp_path / "opt-jaeger")
    state = tmp_path / "state"
    monkeypatch.setenv("JAEGER_HOME", str(checkout))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))

    assert instance_module.operator_state_root() == state.resolve()


def test_jaeger_home_outside_any_checkout_keeps_historical_behavior(monkeypatch, tmp_path):
    home = tmp_path / "plain-home"
    home.mkdir()
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(home))

    assert instance_module.operator_state_root() == home.resolve() / ".jaeger_ai"
@pytest.mark.parametrize('leaked', [
    'jaeger_ai/core/__pycache__/runtime.cpython-311.pyc',
    'jaeger_ai/models/local.gguf',
    'jaeger_agent/nodes/model.safetensors',
    'jaeger_ai/interfaces/swift/.build/release/JaegerOS',
    'jaeger_ai/.env',
    'jaeger_ai/.env.production',
    'jaeger_ai/.jaeger_os/instances/dev/config.yaml',
    '../outside.txt',
])
def test_check_wheel_rejects_runtime_state_from_every_package(tmp_path, check_wheel_module, leaked):
    wheel = tmp_path / 'dirty.whl'
    _build_fake_wheel(wheel, {leaked: b'private'})
    assert check_wheel_module.check_wheel(wheel) == [leaked]


def test_wheel_requires_the_reference_vad_not_arbitrary_weights(tmp_path, check_wheel_module):
    wheel = tmp_path / 'agent.whl'
    _build_fake_wheel(wheel, {'jaeger_agent/core/assets.py': b'asset loader'})
    assert check_wheel_module.check_wheel(wheel)
    _build_fake_wheel(wheel, {check_wheel_module.VAD_ASSET: b'wrong weights'})
    assert 'checksum' in check_wheel_module.check_wheel(wheel)[0]
    _build_fake_wheel(wheel, {'jaeger_ai/models/private.onnx': b'private model'})
    assert check_wheel_module.check_wheel(wheel) == ['jaeger_ai/models/private.onnx']
