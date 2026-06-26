"""INST-7 — ``jaeger update``.

Most of update's work is shelling out (pip / pipx); these tests
mock that and assert the orchestration: stale instances detected,
``--check`` doesn't upgrade, per-instance migration with backup
fires once stale instances exist, etc.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaeger_os.cli.verbs import update_verb as U


# ── helpers ────────────────────────────────────────────────────────


def _make_instance(home: Path, name: str, schema_version: str = "0.5.0") -> Path:
    """Build a minimal valid instance dir under HOME."""
    inst = home / ".jaeger_os" / "instances" / name
    inst.mkdir(parents=True)
    (inst / "identity.yaml").write_text(f"name: {name}\nrole: r\npersonality: p\n",
                                         encoding="utf-8")
    (inst / "config.yaml").write_text(
        "instance_name: %s\nmodel:\n  model_path: gemma-4-26b-a4b-it-q4_k_m\n  ctx: 32768\n" % name,
        encoding="utf-8",
    )
    (inst / "manifest.json").write_text(
        json.dumps({"instance_name": name, "schema_version": schema_version,
                    "created_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    (inst / "memory").mkdir()
    (inst / "logs").mkdir()
    (inst / "skills").mkdir()
    (inst / "credentials").mkdir(mode=0o700)
    return inst


# ── stale detection ────────────────────────────────────────────────


def test_list_stale_returns_empty_when_no_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    assert U._list_stale_instances() == []


def test_list_stale_finds_old_manifests(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    # 0.4.0 != current SCHEMA_VERSION → stale.
    _make_instance(tmp_path, "default", schema_version="0.4.0")
    _make_instance(tmp_path, "work", schema_version="0.4.0")
    stale = U._list_stale_instances()
    names = sorted(s["name"] for s in stale)
    assert names == ["default", "work"]
    for s in stale:
        assert s["current_version"] == "0.4.0"


def test_list_stale_skips_current_version(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    from jaeger_os.core.instance.schemas import SCHEMA_VERSION
    _make_instance(tmp_path, "default", schema_version=SCHEMA_VERSION)
    assert U._list_stale_instances() == []


# ── upgrade command selection ──────────────────────────────────────


def test_upgrade_command_pipx():
    cmd = U._upgrade_command("pipx")
    assert cmd is not None
    assert cmd[:2] == ["pipx", "upgrade"]


def test_upgrade_command_pip_uses_python_m_pip():
    cmd = U._upgrade_command("pip")
    assert cmd is not None
    # First element is the Python interpreter; the rest is ``-m pip install -U``
    assert cmd[1:] == ["-m", "pip", "install", "-U", "jaeger-os"]


def test_upgrade_command_dev_checkout_returns_none():
    assert U._upgrade_command("dev-checkout") is None


def test_upgrade_command_unknown_returns_none():
    assert U._upgrade_command("unknown") is None


# ── ``--check`` mode ───────────────────────────────────────────────


def test_check_exits_0_when_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    code = U._cmd_update_argv(["--check"])
    assert code == 0
    out = capsys.readouterr().out
    assert "all instances" in out or "no migration" in out


def test_check_exits_1_when_stale(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    _make_instance(tmp_path, "default", schema_version="0.4.0")
    code = U._cmd_update_argv(["--check"])
    assert code == 1
    out = capsys.readouterr().out
    assert "need migration" in out
    assert "default" in out


# ── upgrade run ────────────────────────────────────────────────────


def test_update_runs_upgrade_and_skips_migrate_on_no_migrate(tmp_path, monkeypatch, capsys):
    """``--no-migrate`` runs the upgrade but doesn't walk stale
    instances (no prompting + no migration applied)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    _make_instance(tmp_path, "default", schema_version="0.4.0")

    upgrade_calls: list[list[str]] = []

    def fake_run(cmd, **_):
        upgrade_calls.append(cmd)
        # subprocess.CompletedProcess-like; check=False so just need .returncode
        class _R:
            returncode = 0
        return _R()

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)

    # Force the install method to ``pip`` so we get an upgrade command.
    monkeypatch.setattr(U, "_detect_method", lambda: "pip")

    code = U._cmd_update_argv(["--no-migrate"])
    assert code == 0
    # Upgrade was attempted.
    assert any("install" in c and "-U" in c for c in upgrade_calls)
    # Migration was NOT run — the manifest is still at the old version.
    inst_mf = tmp_path / ".jaeger_os" / "instances" / "default" / "manifest.json"
    assert json.loads(inst_mf.read_text())["schema_version"] == "0.4.0"


def _fake_editable_repo(tmp_path, monkeypatch, *, dirty: bool) -> list[list[str]]:
    """Point PACKAGE_ROOT at a throwaway repo and mock subprocess so the
    editable-update path runs in isolation — never touching or pulling the real
    repo. Returns the list of subprocess argvs the verb attempted."""
    repo = tmp_path / "repo"
    (repo / "jaeger_os").mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_os",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **_):
        calls.append(list(cmd))

        class _R:
            returncode = 0
            stdout = " M jaeger_os/x.py\n" if (dirty and "status" in cmd) else ""

        return _R()

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)
    return calls


def test_update_dev_checkout_dirty_prints_hint(tmp_path, monkeypatch, capsys):
    """Editable install (the default) + a dirty tree → refuse to pull, print
    the manual hint."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.setattr(U, "_detect_method", lambda: "dev-checkout")
    calls = _fake_editable_repo(tmp_path, monkeypatch, dirty=True)
    code = U._cmd_update_argv(["--no-migrate"])
    assert code == 0
    out = capsys.readouterr().out
    assert "uncommitted changes" in out and "git pull" in out
    assert any("status" in c for c in calls)         # checked status
    assert not any("pull" in c for c in calls)        # but never pulled


def test_update_dev_checkout_clean_pulls_and_reinstalls(tmp_path, monkeypatch, capsys):
    """Editable install + a clean tree → fast-forward pull then an editable
    reinstall, and still tell the user to restart (never auto-restarts)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.setattr(U, "_detect_method", lambda: "dev-checkout")
    calls = _fake_editable_repo(tmp_path, monkeypatch, dirty=False)
    code = U._cmd_update_argv(["--no-migrate"])
    assert code == 0
    assert any("pull" in c and "--ff-only" in c for c in calls)   # fast-forward pull
    assert any("-e" in c for c in calls)                          # editable reinstall
    assert "Restart" in capsys.readouterr().out
