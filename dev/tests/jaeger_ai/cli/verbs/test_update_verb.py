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

from jaeger_ai.cli.verbs import update_verb as U

_REAL_PREFLIGHT = U._preflight_update


@pytest.fixture(autouse=True)
def isolated_environment_selection(monkeypatch, tmp_path):
    # Individual cases opt into a configured environment explicitly.
    monkeypatch.delenv("JAEGER_VENV", raising=False)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(U, "_preflight_update", lambda home: 0)


# ── helpers ────────────────────────────────────────────────────────


def _make_instance(home: Path, name: str, schema_version: str = "0.5.0") -> Path:
    """Build a minimal valid instance dir under HOME."""
    inst = home / "instances" / name
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
    from jaeger_ai.core.instance.schemas import SCHEMA_VERSION
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
    assert cmd[1:] == ["-m", "pip", "install", "-U", "jaeger-ai"]


def test_upgrade_command_dev_checkout_returns_none():
    assert U._upgrade_command("dev-checkout") is None


def test_upgrade_command_unknown_returns_none():
    assert U._upgrade_command("unknown") is None


def test_update_refreshes_every_wheel_in_selected_external_environment(tmp_path, monkeypatch):
    root = tmp_path / "source"
    venv = tmp_path / "external venv"
    monkeypatch.setenv("JAEGER_VENV", str(venv))
    calls = []
    from types import SimpleNamespace
    monkeypatch.setattr(U.subprocess, "run", lambda args, **kw:
                        calls.append(args) or SimpleNamespace(returncode=0))
    assert U._reinstall_deps(root) == 0
    args = calls[0]
    assert args[:4] == [str(venv / "bin/python"), str(root / "scripts/install-packages.py"),
                        "--python", str(venv / "bin/python")]
    assert args[4:] == [str(root / "packages/jaeger-os"),
                       str(root / "packages/jaeger-agent") + "[multimodal-duplex]",
                       str(root / "packages/jaeger-kokoro-tts"),
                       str(root / "packages/jaeger-whisper-stt"), str(root)]
    assert "-e" not in args


def test_detect_method_marks_product_git_checkout(tmp_path, monkeypatch):
    root = tmp_path / "product"
    package = root / "jaeger_ai"
    package.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".jaeger-product-install").write_text("")
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", package,
    )
    assert U._detect_method() == "product-checkout"


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
    inst_mf = tmp_path / "instances" / "default" / "manifest.json"
    assert json.loads(inst_mf.read_text())["schema_version"] == "0.4.0"


def _fake_editable_repo(tmp_path, monkeypatch, *, dirty: bool) -> list[list[str]]:
    """Point PACKAGE_ROOT at a throwaway repo and mock subprocess so the
    editable-update path runs in isolation — never touching or pulling the real
    repo. Returns the list of subprocess argvs the verb attempted."""
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **_):
        calls.append(list(cmd))

        class _R:
            returncode = 0
            stdout = " M jaeger_ai/x.py\n" if (dirty and "status" in cmd) else ""

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
    assert code == 1
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
    refresh = next(c for c in calls if any("install-packages.py" in a for a in c))
    assert "-e" not in refresh
    assert sum("/packages/" in a for a in refresh) == 4
    assert any("--finish-update" in c for c in calls)


# ── download + apply (clean / no-.git install) ─────────────────────


def _make_archive(tmp: Path, ref: str = "9.9.9") -> Path:
    """A GitHub-style release tarball: one top dir ``JaegerAI-<ref>/`` holding
    product items plus a ``dev/`` tree that the allowlist must skip."""
    src = tmp / "src" / f"JaegerAI-{ref}"
    (src / "jaeger_ai").mkdir(parents=True)
    (src / "jaeger_ai" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    (src / "requirements.txt").write_text("msgspec\n")
    (src / "README.md").write_text("# JaegerAI\n")
    (src / "dev" / "tests").mkdir(parents=True)   # NOT product → must be skipped
    tarball = tmp / "jaeger.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(src, arcname=f"JaegerAI-{ref}")
    return tarball


def test_extract_product_copies_allowlist_only(tmp_path):
    copied = U._extract_product(_make_archive(tmp_path), tmp_path / "staging")
    assert {"jaeger_ai", "requirements.txt", "README.md"} <= set(copied)
    assert "dev" not in copied                                   # not in PRODUCT
    assert (tmp_path / "staging" / "jaeger_ai" / "__init__.py").exists()
    assert not (tmp_path / "staging" / "dev").exists()


def test_swap_and_restore_preserve_venv_and_state(tmp_path):
    """The data-loss-critical path: swap replaces product, keeps the old in
    prev, and never touches .venv/ or .jaeger_ai/; restore is the exact
    inverse."""
    home = tmp_path / "home"
    (home / "jaeger_ai").mkdir(parents=True)
    (home / "jaeger_ai" / "__init__.py").write_text("OLD")
    (home / "requirements.txt").write_text("old-deps")
    (home / ".venv").mkdir(); (home / ".venv" / "marker").write_text("venv")
    (home / ".jaeger_ai").mkdir(); (home / ".jaeger_ai" / "state").write_text("state")
    staging = home / ".update-staging"
    (staging / "jaeger_ai").mkdir(parents=True)
    (staging / "jaeger_ai" / "__init__.py").write_text("NEW")
    (staging / "requirements.txt").write_text("new-deps")
    prev = home / ".update-prev"

    swapped = U._swap_in(home, staging, ["jaeger_ai", "requirements.txt"], prev)
    assert set(swapped) == {"jaeger_ai", "requirements.txt"}
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "NEW"
    assert (prev / "jaeger_ai" / "__init__.py").read_text() == "OLD"
    assert (home / ".venv" / "marker").read_text() == "venv"          # untouched
    assert (home / ".jaeger_ai" / "state").read_text() == "state"     # untouched

    restored = U._restore(home, prev, ["jaeger_ai", "requirements.txt"])
    assert set(restored) == {"jaeger_ai", "requirements.txt"}
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "OLD"


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
    (home / "jaeger_ai").mkdir(parents=True)
    (home / "jaeger_ai" / "__init__.py").write_text("NEW")    # current (bad)
    prev = home / ".update-prev"
    (prev / "jaeger_ai").mkdir(parents=True)
    (prev / "jaeger_ai" / "__init__.py").write_text("OLD")    # stashed good
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: 0)    # no subprocess
    assert U._do_rollback(home) == 0
    assert (home / "jaeger_ai" / "__init__.py").read_text() == "OLD"
    assert not prev.exists()                                  # consumed


def test_rollback_nothing_to_restore(tmp_path, capsys):
    home = tmp_path / "home"; home.mkdir()
    assert U._do_rollback(home) == 1
    assert "nothing to roll back" in capsys.readouterr().err


def test_clean_install_routes_to_download(tmp_path, monkeypatch):
    """No .git in the install root → _update_editable delegates to
    _update_download (the clean-install path), forwarding --ref."""
    home = tmp_path / "home"
    (home / "jaeger_ai").mkdir(parents=True)                  # NO .git
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", home / "jaeger_ai")
    seen: dict = {}
    monkeypatch.setattr(
        U, "_update_download",
        lambda h, *, ref=None: (seen.update(home=h, ref=ref), 0)[1])
    assert U._update_editable(ref="0.7.0") == 0
    assert seen == {"home": home, "ref": "0.7.0"}


def test_update_download_noop_when_current(tmp_path, monkeypatch, capsys):
    import jaeger_ai
    from jaeger_ai.core import version_check
    monkeypatch.setattr(version_check, "latest_release",
                        lambda *a, **k: jaeger_ai.__version__)
    assert U._update_download(tmp_path) == 0
    assert "already up to date" in capsys.readouterr().out


def test_update_download_unreachable_returns_1(tmp_path, monkeypatch, capsys):
    from jaeger_ai.core import version_check
    monkeypatch.setattr(version_check, "latest_release", lambda *a, **k: None)
    assert U._update_download(tmp_path) == 1
    assert "couldn't reach GitHub" in capsys.readouterr().err


# ── reinstall (clean re-fetch / repair) ────────────────────────────


def test_reinstall_clean_install_forces_download(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "jaeger_ai").mkdir(parents=True)                  # NO .git
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", home / "jaeger_ai")
    seen: dict = {}
    monkeypatch.setattr(
        U, "_update_download",
        lambda h, *, ref=None, force=False:
            (seen.update(home=h, ref=ref, force=force), 0)[1])
    assert U._cmd_reinstall_argv([]) == 0
    assert seen == {"home": home, "ref": None, "force": True}


def test_reinstall_dev_clone_repairs_editable(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "jaeger_ai").mkdir(parents=True)
    (home / ".git").mkdir()
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", home / "jaeger_ai")
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
    (home / "jaeger_ai").mkdir()
    (home / "requirements.txt").write_text("same")

    def fake_extract(tarball, staging):
        (staging / "jaeger_ai").mkdir(parents=True)
        (staging / "requirements.txt").write_text("same")     # identical → no change
        return ["jaeger_ai", "requirements.txt"]

    monkeypatch.setattr(U, "_download_tarball", lambda repo, ref, dest: dest.write_bytes(b""))
    monkeypatch.setattr(U, "_extract_product", fake_extract)
    deps: list = []
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: deps.append(h) or 0)
    assert U._update_download(home, ref="9.9.9", force=True) == 0
    assert deps == [home]      # force resyncs deps even though requirements match


# ── Swift app rebuild after product swap (0.7.3) ───────────────────


def _shell_layout(home: Path) -> Path:
    """A fake built app + build script under HOME; returns the script."""
    swift = home / "jaeger_ai" / "interfaces" / "macos-shell"
    (swift / ".build" / "JaegerAI.app").mkdir(parents=True)
    script = swift / "Scripts" / "build-shell.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\nexit 0\n")
    return script


def test_update_download_rebuilds_swift_app(tmp_path, monkeypatch):
    home = tmp_path
    (home / "jaeger_ai").mkdir()
    (home / "requirements.txt").write_text("same")
    _shell_layout(home)

    def fake_extract(tarball, staging):
        (staging / "jaeger_ai").mkdir(parents=True)
        (staging / "requirements.txt").write_text("same")
        return ["jaeger_ai", "requirements.txt"]

    monkeypatch.setattr(U, "_download_tarball",
                        lambda repo, ref, dest: dest.write_bytes(b""))
    monkeypatch.setattr(U, "_extract_product", fake_extract)
    monkeypatch.setattr(U, "_reinstall_deps", lambda h: 0)
    rebuilds: list = []
    monkeypatch.setattr(U, "_rebuild_mac_shell", lambda h: rebuilds.append(h))
    assert U._update_download(home, ref="9.9.9") == 0
    assert rebuilds == [home]   # rebuild runs on the swapped-in install


def test_rebuild_mac_shell_skips_when_never_built(tmp_path, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(U.subprocess, "run",
                        lambda *a, **k: calls.append(a))
    U._rebuild_mac_shell(tmp_path)      # no .build/JaegerAI.app → no-op
    assert calls == []
    assert capsys.readouterr().err == ""


def test_rebuild_mac_shell_runs_build_script(tmp_path, monkeypatch, capsys):
    script = _shell_layout(tmp_path)
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_mac_shell(tmp_path)
    assert ran == [["bash", str(script)]]
    assert "exited 0" in capsys.readouterr().out


def test_rebuild_mac_shell_builds_when_app_missing(tmp_path, monkeypatch, capsys):
    """A failed install-time build must not exempt a station forever:
    script present + app absent -> BUILD (this was the 'never even
    installed' half of the deployed-station bug)."""
    import shutil as _sh
    script = _shell_layout(tmp_path)
    _sh.rmtree(tmp_path / "jaeger_ai" / "interfaces" / "macos-shell" / ".build")
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_mac_shell(tmp_path)
    assert ran == [["bash", str(script)]]
    assert "build exited 0" in capsys.readouterr().out


def test_rebuild_mac_shell_dev_checkout_builds_dev_flavor(tmp_path, monkeypatch):
    """Flavor follows the install: dev/ present -> debug build via --dev
    (mirrors install.sh); same JaegerAI.app bundle either way."""
    script = _shell_layout(tmp_path)
    (tmp_path / "dev").mkdir()
    ran: list = []

    class _R:
        returncode = 0

    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(U.subprocess, "run", lambda argv, **k: ran.append(argv) or _R())
    U._rebuild_mac_shell(tmp_path)
    assert ran == [["bash", str(script)]]


def test_rebuild_mac_shell_only_if_stale_skips_fresh(tmp_path, monkeypatch):
    _shell_layout(tmp_path)
    from jaeger_ai.cli import _common
    monkeypatch.setattr(_common, "mac_app_is_stale", lambda repo, bundle: False)
    ran: list = []
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: ran.append(a))
    U._rebuild_mac_shell(tmp_path, only_if_stale=True)
    assert ran == []


def test_rebuild_mac_shell_warns_without_toolchain(tmp_path, monkeypatch, capsys):
    _shell_layout(tmp_path)
    monkeypatch.setattr(U.shutil, "which", lambda name: None)
    U._rebuild_mac_shell(tmp_path)
    assert "was not built" in capsys.readouterr().err


def test_mac_app_is_stale_basics(tmp_path):
    """Missing executable -> stale; no .git (tarball install) -> never stale
    (that path rebuilds explicitly after every product swap)."""
    from jaeger_ai.cli._common import mac_app_is_stale
    bundle = tmp_path / "JaegerShell.app"
    assert mac_app_is_stale(tmp_path, bundle) is True   # no exe
    exe = bundle / "Contents" / "MacOS" / "JaegerShell"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert mac_app_is_stale(tmp_path, bundle) is True  # no source stamp


# ── app-bridge run_update (0.8 in-app updates) ──────────────────────


def test_jaeger_exe_uses_external_environment_without_a_repo_venv(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai")
    # No venv yet -> falls back to the wrapper script at the install root.
    assert U.jaeger_exe() == repo / "jaeger"
    venv_bin = tmp_path / "external-venv" / "bin"
    monkeypatch.setenv("JAEGER_VENV", str(venv_bin.parent))
    venv_bin.mkdir(parents=True)
    (venv_bin / "jaeger").write_text("#!/bin/sh\n")
    assert U.jaeger_exe() == venv_bin / "jaeger"


def test_run_update_subprocess_invokes_jaeger_update(tmp_path, monkeypatch):
    """Calls the SAME ``jaeger update`` machinery — never reimplements the
    upgrade logic — with stdin closed (non-interactive)."""
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))

        class _R:
            returncode = 0
            stdout = "[jaeger update] now at 0.9.0.\n"

        return _R()

    monkeypatch.setattr(U.subprocess, "run", fake_run)
    res = U.run_update_subprocess()
    assert res == {"ok": True, "returncode": 0,
                    "output": "[jaeger update] now at 0.9.0.\n",
                    "restart_required": True, "error": None}
    argv, kwargs = calls[0]
    assert argv == [str(repo / "jaeger"), "update"]
    assert kwargs["stdin"] is U.subprocess.DEVNULL


def test_run_update_subprocess_pins_ref(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class _R:
            returncode = 0
            stdout = ""

        return _R()

    monkeypatch.setattr(U.subprocess, "run", fake_run)
    U.run_update_subprocess(ref="0.9.0")
    assert calls[0] == [str(repo / "jaeger"), "update", "--ref", "0.9.0"]


def test_run_update_subprocess_nonzero_exit_reports_error(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai")

    def fake_run(argv, **kwargs):
        class _R:
            returncode = 2
            stdout = "boom\n"

        return _R()

    monkeypatch.setattr(U.subprocess, "run", fake_run)
    res = U.run_update_subprocess()
    assert res["ok"] is False
    # still restart-worthy — the process ran and may have changed files.
    assert res["restart_required"] is True
    assert "exited 2" in res["error"]


def test_run_update_subprocess_missing_binary_never_raises(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "jaeger_ai").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.PACKAGE_ROOT", repo / "jaeger_ai")

    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(U.subprocess, "run", fake_run)
    res = U.run_update_subprocess()
    assert res == {"ok": False, "returncode": None, "output": "",
                    "restart_required": False, "error": "no such file"}


def test_migration_failures_are_not_update_success(monkeypatch):
    monkeypatch.setattr(U, '_list_stale_instances', lambda: [
        {'name': 'default', 'current_version': 'old'}])
    monkeypatch.setattr(U, '_ask_yn', lambda *a: True)
    monkeypatch.setattr(U, '_migrate_instance_with_backup', lambda name: 2)
    assert U._cmd_update_argv(['--finish-update']) == 2


def test_migration_discovery_runs_only_after_upgrade(monkeypatch):
    calls = []
    monkeypatch.setattr(U, '_detect_method', lambda: 'product-checkout')
    monkeypatch.setattr(U, '_list_stale_instances', lambda: pytest.fail('old process scanned schemas'))
    monkeypatch.setattr(U, '_run_upgrade', lambda *a, **k: calls.append('upgrade') or 0)
    monkeypatch.setattr(U, '_finish_update_subprocess', lambda **k: calls.append('fresh-process') or 3)
    assert U._cmd_update_argv([]) == 3
    assert calls == ['upgrade', 'fresh-process']


def test_failed_upgrade_never_runs_migrations(monkeypatch):
    monkeypatch.setattr(U, '_detect_method', lambda: 'pip')
    monkeypatch.setattr(U, '_run_upgrade', lambda *a, **k: 7)
    monkeypatch.setattr(U, '_finish_update_subprocess', lambda **k: pytest.fail('migration after failure'))
    assert U._cmd_update_argv([]) == 7


def test_fresh_process_reads_new_schema(tmp_path, monkeypatch):
    import sys
    executable = tmp_path / 'jaeger'
    schema = tmp_path / 'schema.txt'
    schema.write_text('new-schema')
    executable.write_text(f'#!{sys.executable}\n'
        'import pathlib, sys\n'
        'assert sys.argv[1:] == ["update", "--finish-update"]\n'
        f'assert pathlib.Path({str(schema)!r}).read_text() == "new-schema"\n')
    executable.chmod(0o755)
    monkeypatch.setattr(U, 'jaeger_exe', lambda: executable)
    assert U._finish_update_subprocess() == 0


def _real_product_repository(tmp_path, monkeypatch):
    import subprocess
    origin = tmp_path / 'origin'
    origin.mkdir()
    run = lambda *args, **kw: subprocess.run(['git', *args], check=True, capture_output=True, text=True, **kw)
    run('init', str(origin))
    run('-C', str(origin), 'config', 'user.email', 'isolated@example.invalid')
    run('-C', str(origin), 'config', 'user.name', 'Isolated test')
    updater = origin / 'jaeger_ai/cli/verbs/update_verb.py'
    updater.parent.mkdir(parents=True)
    updater.write_text('# coordinated updater supports --finish-update\n')
    (origin / 'version.txt').write_text('old')
    run('-C', str(origin), 'add', 'version.txt', 'jaeger_ai')
    run('-C', str(origin), 'commit', '-m', 'old')
    old = run('-C', str(origin), 'rev-parse', 'HEAD').stdout.strip()
    run('-C', str(origin), 'tag', 'v1.0.0')
    (origin / 'version.txt').write_text('new')
    run('-C', str(origin), 'commit', '-am', 'new')
    new = run('-C', str(origin), 'rev-parse', 'HEAD').stdout.strip()
    run('-C', str(origin), 'tag', 'v2.0.0')
    home = tmp_path / 'product'
    run('clone', str(origin), str(home))
    monkeypatch.setattr(U, '_reinstall_deps', lambda home: 0)
    monkeypatch.setattr(U, '_rebuild_mac_shell', lambda home, **kw: 0)
    return home, old, new


def test_product_git_update_honors_pin_and_rollback(tmp_path, monkeypatch):
    home, old, new = _real_product_repository(tmp_path, monkeypatch)
    assert U._update_product_git(home, ref='v1.0.0') == 0
    assert (home / 'version.txt').read_text() == 'old'
    assert U._git(home, 'rev-parse', 'HEAD').stdout.strip() == old
    assert U._git(home, 'rev-parse', U.UPDATE_PREVIOUS_GIT_REF).stdout.strip() == new
    assert U._do_rollback(home) == 0
    assert (home / 'version.txt').read_text() == 'new'
    assert U._git(home, 'status', '--porcelain').stdout == ''


def test_product_git_update_stable_resolves_tag(tmp_path, monkeypatch):
    from jaeger_ai.core import version_check
    home, old, new = _real_product_repository(tmp_path, monkeypatch)
    U._git(home, 'checkout', '--detach', old)
    monkeypatch.setattr(version_check, 'latest_release', lambda *a, **kw: 'v2.0.0')
    assert U._update_product_git(home) == 0
    assert U._git(home, 'rev-parse', 'HEAD').stdout.strip() == new


def test_product_git_refuses_dirty_checkout(tmp_path, monkeypatch):
    home, old, new = _real_product_repository(tmp_path, monkeypatch)
    (home / 'version.txt').write_text('operator work')
    assert U._update_product_git(home, ref=old) == 1
    assert (home / 'version.txt').read_text() == 'operator work'
    assert U._git(home, 'rev-parse', 'HEAD').stdout.strip() == new


def test_product_git_failure_retains_recovery_ref(tmp_path, monkeypatch):
    home, old, new = _real_product_repository(tmp_path, monkeypatch)
    monkeypatch.setattr(U, '_reinstall_deps', lambda home: 17)
    assert U._update_product_git(home, ref=old) == 17
    assert U._git(home, 'rev-parse', U.UPDATE_PREVIOUS_GIT_REF).stdout.strip() == new
    assert U._update_product_git(home, ref=old) == 1
    assert U._git(home, 'rev-parse', U.UPDATE_PREVIOUS_GIT_REF).stdout.strip() == new
    monkeypatch.setattr(U, '_reinstall_deps', lambda home: 0)
    assert U._do_rollback(home) == 0
    assert U._git(home, 'rev-parse', 'HEAD').stdout.strip() == new


def test_preflight_refuses_live_services_without_changing_files(tmp_path, monkeypatch):
    import socket
    from contextlib import nullcontext
    sentinel = tmp_path / 'version.txt'
    sentinel.write_text('untouched')
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: nullcontext())
    assert _REAL_PREFLIGHT(tmp_path) == 1
    assert sentinel.read_text() == 'untouched'


def test_preflight_refuses_running_native_shell(tmp_path, monkeypatch):
    import errno
    import socket
    from types import SimpleNamespace
    def stopped(*a, **kw):
        raise ConnectionRefusedError(errno.ECONNREFUSED, 'refused')
    monkeypatch.setattr(socket, 'create_connection', stopped)
    monkeypatch.setattr(U.sys, 'platform', 'darwin')
    monkeypatch.setattr(U.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    assert _REAL_PREFLIGHT(tmp_path) == 1


def test_preflight_process_inspection_failure_is_closed(tmp_path, monkeypatch):
    import errno
    import socket
    from types import SimpleNamespace
    def stopped(*a, **kw):
        raise ConnectionRefusedError(errno.ECONNREFUSED, 'refused')
    monkeypatch.setattr(socket, 'create_connection', stopped)
    monkeypatch.setattr(U.sys, 'platform', 'darwin')
    monkeypatch.setattr(U.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=2))
    assert _REAL_PREFLIGHT(tmp_path) == 1


def test_product_git_refuses_target_without_coordinated_migrations(tmp_path, monkeypatch):
    home, old, new = _real_product_repository(tmp_path, monkeypatch)
    U._git(home, 'config', 'user.email', 'isolated@example.invalid')
    U._git(home, 'config', 'user.name', 'Isolated test')
    (home / 'jaeger_ai/cli/verbs/update_verb.py').write_text('# historical updater\n')
    U._git(home, 'commit', '-am', 'historical updater fixture')
    historical = U._git(home, 'rev-parse', 'HEAD').stdout.strip()
    U._git(home, 'push', 'origin', 'HEAD:refs/heads/historical')
    U._git(home, 'checkout', '--detach', new)
    assert U._update_product_git(home, ref='historical') == 1
    assert U._git(home, 'rev-parse', 'HEAD').stdout.strip() == new


@pytest.mark.parametrize('argv', [['--check', '--rollback'], ['--check', '--finish-update']])
def test_read_only_check_cannot_be_combined_with_mutation(monkeypatch, argv):
    monkeypatch.setattr(U, '_do_rollback', lambda *a: pytest.fail('read-only rollback'))
    monkeypatch.setattr(U, '_finish_update', lambda **kw: pytest.fail('conflicting modes'))
    with pytest.raises(SystemExit) as result:
        U._cmd_update_argv(argv)
    assert result.value.code == 2


def test_product_reinstall_ref_uses_canonical_pinned_update(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    (tmp_path / '.jaeger-product-install').touch()
    monkeypatch.setattr('jaeger_ai.core.instance.instance.install_root', lambda: tmp_path)
    calls = []
    monkeypatch.setattr(U, '_cmd_update_argv', lambda argv: calls.append(argv) or 7)
    assert U._cmd_reinstall_argv(['--ref', 'owned-commit']) == 7
    assert calls == [['--ref', 'owned-commit']]
