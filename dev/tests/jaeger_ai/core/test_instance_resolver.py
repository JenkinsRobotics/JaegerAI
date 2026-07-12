"""Resolver + wheel-cleanliness — HYGIENE-4/5 + INST-1/-10.

0.1.0 lost data both ways: the bundled dir won over ``~/.jaeger/``
whenever it was writable (which is always, on a normal pip install),
and the wheel itself shipped packager-machine state. HYGIENE-4
swapped the priority; INST-10 (0.2.0) dropped the bundled dir
entirely and INST-1 nested instances under ``~/.jaeger/instances/``.
These tests pin the post-INST-1/-10 resolver shape.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from jaeger_ai.core.instance import instance as instance_module


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
    expected = (fake_home / ".jaeger_os" / "instances" / "default").resolve()
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
    fake_pkg = tmp_path / "GITHUB" / "JROS" / "jaeger_os"
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
    (tmp_path / ".jaeger_os").mkdir()
    (tmp_path / ".jaeger_os" / "active_instance").write_text("work\n",
                                                          encoding="utf-8")
    assert instance_module.default_instance_name() == "work"


def test_env_var_beats_active_instance_file(monkeypatch, tmp_path):
    """If both the env var and the sticky file are set, the env var
    wins — explicit (in-shell) beats implicit (on-disk)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_os").mkdir()
    (tmp_path / ".jaeger_os" / "active_instance").write_text("sticky-name\n",
                                                          encoding="utf-8")
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "env-name")
    assert instance_module.default_instance_name() == "env-name"


def test_write_active_instance_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    instance_module.write_active_instance("work")
    assert (tmp_path / ".jaeger_os" / "active_instance").read_text().strip() == "work"


def test_write_active_instance_none_removes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_os").mkdir()
    (tmp_path / ".jaeger_os" / "active_instance").write_text("work\n",
                                                          encoding="utf-8")
    instance_module.write_active_instance(None)
    assert not (tmp_path / ".jaeger_os" / "active_instance").exists()


def test_read_active_instance_treats_whitespace_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    (tmp_path / ".jaeger_os").mkdir()
    (tmp_path / ".jaeger_os" / "active_instance").write_text("   \n  \n",
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
