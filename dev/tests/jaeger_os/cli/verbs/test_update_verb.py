"""INST-7 — ``jaeger update``.

Most of update's work is shelling out (pip / pipx); these tests
mock that and assert the orchestration: stale instances detected,
``--check`` doesn't upgrade, per-instance migration with backup
fires once stale instances exist, etc.
"""

from __future__ import annotations

import json
import tarfile
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


# ── download + apply (clean / no-.git install) ─────────────────────


def _make_archive(tmp: Path, ref: str = "9.9.9") -> Path:
    """A GitHub-style release tarball: one top dir ``JROS-<ref>/`` holding
    product items plus a ``dev/`` tree that the allowlist must skip."""
    src = tmp / "src" / f"JROS-{ref}"
    (src / "jaeger_os").mkdir(parents=True)
    (src / "jaeger_os" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    (src / "requirements.txt").write_text("msgspec\n")
    (src / "README.md").write_text("# JROS\n")
    (src / "dev" / "tests").mkdir(parents=True)   # NOT product → must be skipped
    tarball = tmp / "jros.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(src, arcname=f"JROS-{ref}")
    return tarball


def test_extract_product_copies_allowlist_only(tmp_path):
    copied = U._extract_product(_make_archive(tmp_path), tmp_path / "staging")
    assert {"jaeger_os", "requirements.txt", "README.md"} <= set(copied)
    assert "dev" not in copied                                   # not in PRODUCT
    assert (tmp_path / "staging" / "jaeger_os" / "__init__.py").exists()
    assert not (tmp_path / "staging" / "dev").exists()


def test_swap_and_restore_preserve_venv_and_state(tmp_path):
    """The data-loss-critical path: swap replaces product, keeps the old in
    prev, and never touches .venv/ or .jaeger_os/; restore is the exact
    inverse."""
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("OLD")
    (home / "requirements.txt").write_text("old-deps")
    (home / ".venv").mkdir(); (home / ".venv" / "marker").write_text("venv")
    (home / ".jaeger_os").mkdir(); (home / ".jaeger_os" / "state").write_text("state")
    staging = home / ".update-staging"
    (staging / "jaeger_os").mkdir(parents=True)
    (staging / "jaeger_os" / "__init__.py").write_text("NEW")
    (staging / "requirements.txt").write_text("new-deps")
    prev = home / ".update-prev"

    swapped = U._swap_in(home, staging, ["jaeger_os", "requirements.txt"], prev)
    assert set(swapped) == {"jaeger_os", "requirements.txt"}
    assert (home / "jaeger_os" / "__init__.py").read_text() == "NEW"
    assert (prev / "jaeger_os" / "__init__.py").read_text() == "OLD"
    assert (home / ".venv" / "marker").read_text() == "venv"          # untouched
    assert (home / ".jaeger_os" / "state").read_text() == "state"     # untouched

    restored = U._restore(home, prev, ["jaeger_os", "requirements.txt"])
    assert set(restored) == {"jaeger_os", "requirements.txt"}
    assert (home / "jaeger_os" / "__init__.py").read_text() == "OLD"


def test_deps_changed(tmp_path):
    home, prev = tmp_path / "home", tmp_path / "prev"
    home.mkdir(); prev.mkdir()
    (home / "requirements.txt").write_text("a")
    (prev / "requirements.txt").write_text("a")
    assert not U._deps_changed(home, prev)               # identical
    (home / "requirements.txt").write_text("b")
    assert U._deps_changed(home, prev)                   # content differs
    (home / "requirements.txt").write_text("a")
    (home / "pyproject.toml").write_text("x")            # present one side only
    assert U._deps_changed(home, prev)


def test_rollback_restores_and_consumes_prev(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / "jaeger_os" / "__init__.py").write_text("NEW")    # current (bad)
    prev = home / ".update-prev"
    (prev / "jaeger_os").mkdir(parents=True)
    (prev / "jaeger_os" / "__init__.py").write_text("OLD")    # stashed good
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: 0)    # no subprocess
    assert U._do_rollback(home) == 0
    assert (home / "jaeger_os" / "__init__.py").read_text() == "OLD"
    assert not prev.exists()                                  # consumed


def test_rollback_nothing_to_restore(tmp_path, capsys):
    home = tmp_path / "home"; home.mkdir()
    assert U._do_rollback(home) == 1
    assert "nothing to roll back" in capsys.readouterr().err


def test_clean_install_routes_to_download(tmp_path, monkeypatch):
    """No .git in the install root → _update_editable delegates to
    _update_download (the clean-install path), forwarding --ref."""
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)                  # NO .git
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.PACKAGE_ROOT", home / "jaeger_os")
    seen: dict = {}
    monkeypatch.setattr(
        U, "_update_download",
        lambda h, *, ref=None: (seen.update(home=h, ref=ref), 0)[1])
    assert U._update_editable(ref="0.7.0") == 0
    assert seen == {"home": home, "ref": "0.7.0"}


def test_update_download_noop_when_current(tmp_path, monkeypatch, capsys):
    import jaeger_os
    from jaeger_os.core import version_check
    monkeypatch.setattr(version_check, "latest_version",
                        lambda *a, **k: jaeger_os.__version__)
    assert U._update_download(tmp_path) == 0
    assert "already up to date" in capsys.readouterr().out


def test_update_download_unreachable_returns_1(tmp_path, monkeypatch, capsys):
    from jaeger_os.core import version_check
    monkeypatch.setattr(version_check, "latest_version", lambda *a, **k: None)
    assert U._update_download(tmp_path) == 1
    assert "couldn't reach GitHub" in capsys.readouterr().err


# ── reinstall (clean re-fetch / repair) ────────────────────────────


def test_reinstall_clean_install_forces_download(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)                  # NO .git
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.PACKAGE_ROOT", home / "jaeger_os")
    seen: dict = {}
    monkeypatch.setattr(
        U, "_update_download",
        lambda h, *, ref=None, force=False:
            (seen.update(home=h, ref=ref, force=force), 0)[1])
    assert U._cmd_reinstall_argv([]) == 0
    assert seen == {"home": home, "ref": None, "force": True}


def test_reinstall_dev_clone_repairs_editable(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "jaeger_os").mkdir(parents=True)
    (home / ".git").mkdir()
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.PACKAGE_ROOT", home / "jaeger_os")
    calls: list = []
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: calls.append(h) or 0)
    assert U._cmd_reinstall_argv([]) == 0
    assert calls == [home]                                    # repaired in place
    assert "dev clone" in capsys.readouterr().out


def test_resolve_ref_precedence(monkeypatch):
    monkeypatch.delenv("JAEGER_REF", raising=False)
    assert U._resolve_ref("0.6.0", "stable") == "0.6.0"        # --ref wins
    assert U._resolve_ref("0.6.0", "latest") == "0.6.0"        # --ref overrides channel
    assert U._resolve_ref(None, "latest") == U._LATEST_BRANCH  # latest → master
    assert U._resolve_ref(None, "stable") is None              # stable → newest tag (lookup)
    monkeypatch.setenv("JAEGER_REF", "0.5.2")
    assert U._resolve_ref(None, "stable") == "0.5.2"           # $JAEGER_REF honoured
    assert U._resolve_ref(None, "latest") == U._LATEST_BRANCH  # channel beats env
    assert U._resolve_ref("0.7.0", "stable") == "0.7.0"        # --ref still wins


def test_update_download_force_reinstalls_even_if_deps_unchanged(tmp_path, monkeypatch):
    home = tmp_path
    (home / "jaeger_os").mkdir()
    (home / "requirements.txt").write_text("same")

    def fake_extract(tarball, staging):
        (staging / "jaeger_os").mkdir(parents=True)
        (staging / "requirements.txt").write_text("same")     # identical → no change
        return ["jaeger_os", "requirements.txt"]

    monkeypatch.setattr(U, "_download_tarball", lambda repo, ref, dest: dest.write_bytes(b""))
    monkeypatch.setattr(U, "_extract_product", fake_extract)
    deps: list = []
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: deps.append(h) or 0)
    assert U._update_download(home, ref="9.9.9", force=True) == 0
    assert deps == [home]      # force resyncs deps even though requirements match


# ── Swift app rebuild after product swap (0.7.3) ───────────────────


def _swift_layout(home: Path) -> Path:
    """A fake built app + build script under HOME; returns the script."""
    swift = home / "jaeger_os" / "interfaces" / "swift"
    (swift / ".build" / "JaegerOS.app").mkdir(parents=True)
    script = swift / "Scripts" / "build-app.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\nexit 0\n")
    return script


def test_update_download_rebuilds_swift_app(tmp_path, monkeypatch):
    home = tmp_path
    (home / "jaeger_os").mkdir()
    (home / "requirements.txt").write_text("same")
    _swift_layout(home)

    def fake_extract(tarball, staging):
        (staging / "jaeger_os").mkdir(parents=True)
        (staging / "requirements.txt").write_text("same")
        return ["jaeger_os", "requirements.txt"]

    monkeypatch.setattr(U, "_download_tarball",
                        lambda repo, ref, dest: dest.write_bytes(b""))
    monkeypatch.setattr(U, "_extract_product", fake_extract)
    rebuilds: list = []
    monkeypatch.setattr(U, "_rebuild_swift_app", lambda h: rebuilds.append(h))
    assert U._update_download(home, ref="9.9.9") == 0
    assert rebuilds == [home]   # rebuild runs on the swapped-in install


def test_rebuild_swift_app_skips_when_never_built(tmp_path, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(U.subprocess, "run",
                        lambda *a, **k: calls.append(a))
    U._rebuild_swift_app(tmp_path)      # no .build/JaegerOS.app → no-op
    assert calls == []
    assert capsys.readouterr().err == ""


def test_rebuild_swift_app_runs_build_script(tmp_path, monkeypatch, capsys):
    script = _swift_layout(tmp_path)
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_swift_app(tmp_path)
    assert ran == [["bash", str(script), "--release"]]
    assert "ready" in capsys.readouterr().out


def test_rebuild_swift_app_builds_when_app_missing(tmp_path, monkeypatch, capsys):
    """A failed install-time build must not exempt a station forever:
    script present + app absent -> BUILD (this was the 'never even
    installed' half of the deployed-station bug)."""
    import shutil as _sh
    script = _swift_layout(tmp_path)
    _sh.rmtree(tmp_path / "jaeger_os" / "interfaces" / "swift" / ".build")
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_swift_app(tmp_path)
    assert ran == [["bash", str(script), "--release"]]
    assert "building" in capsys.readouterr().out


def test_rebuild_swift_app_dev_checkout_builds_dev_flavor(tmp_path, monkeypatch):
    """Flavor follows the install: dev/ present -> JaegerOS-dev.app via --dev
    (mirrors install.sh); a git-clone station gets the dev shell."""
    script = _swift_layout(tmp_path)
    (tmp_path / "dev").mkdir()
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_swift_app(tmp_path)
    assert ran == [["bash", str(script), "--dev"]]


def test_rebuild_swift_app_only_if_stale_skips_fresh(tmp_path, monkeypatch):
    _swift_layout(tmp_path)
    from jaeger_os.cli import _common
    monkeypatch.setattr(_common, "swift_app_is_stale", lambda repo, bundle: False)
    ran: list = []
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: ran.append(a))
    U._rebuild_swift_app(tmp_path, only_if_stale=True)
    assert ran == []


def test_rebuild_swift_app_warns_without_toolchain(tmp_path, monkeypatch, capsys):
    _swift_layout(tmp_path)
    monkeypatch.setattr(U.shutil, "which", lambda name: None)
    U._rebuild_swift_app(tmp_path)
    assert "NOT (re)built" in capsys.readouterr().err


def test_swift_app_is_stale_basics(tmp_path):
    """Missing executable -> stale; no .git (tarball install) -> never stale
    (that path rebuilds explicitly after every product swap)."""
    from jaeger_os.cli._common import swift_app_is_stale
    bundle = tmp_path / "JaegerOS.app"
    assert swift_app_is_stale(tmp_path, bundle) is True   # no exe
    exe = bundle / "Contents" / "MacOS" / "JaegerOS"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert swift_app_is_stale(tmp_path, bundle) is False  # exe, but no .git
