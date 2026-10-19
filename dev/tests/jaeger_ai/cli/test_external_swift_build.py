"""Regression tests: external Swift build path contract.

Verifies:
  - Default path is outside the repo checkout (fully resolved)
  - JAEGER_MAC_BUILD override is honoured (including tilde)
  - In-repo override is rejected (including symlink-to-repo)
  - Dangerous broad roots are rejected
  - Path with spaces is handled
  - All callers (_boot_swift, _rebuild_swift_app, _find_app_bundle) use the
    same resolver and produce no in-repo .build fallback
  - Shell-boundary: build-app.sh rejects bad paths before calling swift,
    fails hard when resolver is unavailable
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# The actual build script location (used for shell-boundary tests).
_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "jaeger_ai" / "interfaces" / "macos-shell" / "Scripts" / "build-shell.sh"
)


# ── _common.mac_shell_build_dir / mac_app_bundle ─────────────────────────────


def test_default_build_dir_is_outside_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_MAC_BUILD", raising=False)
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / "jaeger_ai").mkdir()
    (repo / "jaeger_ai" / "__init__.py").write_text("")

    result = mac_shell_build_dir(repo)
    repo_real = repo.resolve()
    assert not str(result).startswith(str(repo_real) + "/"), (
        f"default build dir {result} must not be inside repo {repo_real}"
    )


def test_default_build_dir_is_fully_resolved(tmp_path, monkeypatch):
    """Default path must be fully resolved (no trailing symlink segments)."""
    monkeypatch.delenv("JAEGER_MAC_BUILD", raising=False)
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    result = mac_shell_build_dir(repo)
    assert result == result.resolve()


def test_env_override_is_used(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    external = tmp_path / "external" / "build"
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(external))

    result = mac_shell_build_dir(repo)
    assert result == external.resolve()


def test_tilde_override_is_expanded(tmp_path, monkeypatch):
    """JAEGER_MAC_BUILD with a tilde prefix must be expanded, not passed raw."""
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setenv("JAEGER_MAC_BUILD", "~/.jaeger/test-tilde-build")

    result = mac_shell_build_dir(repo)
    assert "~" not in str(result), f"tilde not expanded in {result}"
    assert result.is_absolute()


def test_in_repo_override_is_rejected(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(repo / "nested" / "build"))

    with pytest.raises(ValueError, match="outside the repository"):
        mac_shell_build_dir(repo)


def test_dangerous_root_slash_is_rejected(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setenv("JAEGER_MAC_BUILD", "/")

    with pytest.raises(ValueError, match="dedicated build directory"):
        mac_shell_build_dir(repo)


def test_dangerous_root_applications_is_rejected(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setenv("JAEGER_MAC_BUILD", "/Applications")

    with pytest.raises(ValueError, match="dedicated build directory"):
        mac_shell_build_dir(repo)


def test_path_with_spaces_is_handled(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_app_bundle

    repo = tmp_path / "checkout"
    repo.mkdir()
    external = tmp_path / "my build dir" / "apps"
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(external))

    bundle = mac_app_bundle(repo)
    assert bundle.name == "JaegerShell.app"
    assert " " in str(bundle)


def test_mac_app_bundle_is_under_build_dir(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import mac_app_bundle, mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    external = tmp_path / "external"
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(external))

    build = mac_shell_build_dir(repo)
    bundle = mac_app_bundle(repo)
    assert bundle == build / "JaegerShell.app"


# ── symlink resolution: override that symlinks back into repo is rejected ───


def test_symlink_to_repo_is_rejected(tmp_path, monkeypatch):
    """A JAEGER_MAC_BUILD that is a symlink pointing into the repo is rejected."""
    from jaeger_ai.cli._common import mac_shell_build_dir

    repo = tmp_path / "checkout"
    repo.mkdir()
    inside = repo / "inside"
    inside.mkdir()
    link = tmp_path / "sneaky-link"
    link.symlink_to(inside)

    monkeypatch.setenv("JAEGER_MAC_BUILD", str(link))
    with pytest.raises(ValueError, match="outside the repository"):
        mac_shell_build_dir(repo)


# ── lifecycle_verbs._find_app_bundle does not surface in-repo .build ────────


def test_find_app_bundle_prefers_external_over_repo_build(tmp_path, monkeypatch):
    """_find_app_bundle must return the external bundle when present."""
    from jaeger_ai.cli.verbs import lifecycle_verbs as lv

    external = tmp_path / "external" / "JaegerShell.app"
    (external / "Contents/MacOS").mkdir(parents=True)
    (external / "Contents/MacOS/JaegerShell").write_text("shell")
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(tmp_path / "external"))
    monkeypatch.setattr(lv, "REPO_ROOT", tmp_path / "checkout")

    result = lv._find_app_bundle()
    assert result is not None
    assert result == external


def test_find_app_bundle_returns_none_when_nothing_exists(tmp_path, monkeypatch):
    """Must return None when no bundle exists anywhere — stubbing Path.exists
    so the test runs on every host regardless of installed software."""
    from jaeger_ai.cli.verbs import lifecycle_verbs as lv

    monkeypatch.setenv("JAEGER_MAC_BUILD", str(tmp_path / "nowhere"))
    monkeypatch.setattr(lv, "REPO_ROOT", tmp_path / "checkout")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fakehome"))
    monkeypatch.setattr(Path, "exists", lambda self: False)

    result = lv._find_app_bundle()
    assert result is None


# ── callers agree on the same path, no in-repo fallback ─────────────────────


def test_update_verb_rebuild_uses_external_path(tmp_path, monkeypatch):
    """_rebuild_mac_shell calls build-shell.sh; the bundle it checks for staleness
    must be the external path, not the in-repo .build."""
    from jaeger_ai.cli.verbs import update_verb as U

    external = tmp_path / "ext-build"
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(external))

    home = tmp_path / "home"
    (home / "jaeger_ai" / "interfaces" / "macos-shell" / "Scripts").mkdir(parents=True)
    (home / "jaeger_ai" / "interfaces" / "macos-shell" / "Scripts" / "build-shell.sh").write_text("#!/bin/bash\n")

    calls = []
    monkeypatch.setattr(
        U.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or __import__("subprocess").CompletedProcess(cmd, 0),
    )
    monkeypatch.setattr(U.shutil, "which", lambda name: "/usr/bin/swift" if name == "swift" else None)

    U._rebuild_mac_shell(home)
    assert calls, "expected build-shell.sh to be invoked"
    assert all("build-shell.sh" in str(c) for c in calls)
    for cmd in calls:
        assert ".build" not in " ".join(str(a) for a in cmd)


def test_update_verb_rebuild_fails_on_bad_override(tmp_path, monkeypatch, capsys):
    """_rebuild_mac_shell must print an error and not call build-shell.sh when
    JAEGER_MAC_BUILD is a bad override (not silently fall back)."""
    from jaeger_ai.cli.verbs import update_verb as U

    home = tmp_path / "home"
    (home / "jaeger_ai" / "interfaces" / "macos-shell" / "Scripts").mkdir(parents=True)
    script = home / "jaeger_ai" / "interfaces" / "macos-shell" / "Scripts" / "build-shell.sh"
    script.write_text("#!/bin/bash\n")
    # Point JAEGER_MAC_BUILD inside `home` (which IS the repo root argument).
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(home / "inside"))

    calls = []
    monkeypatch.setattr(
        U.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or __import__("subprocess").CompletedProcess(cmd, 0),
    )

    U._rebuild_mac_shell(home)
    # build-shell.sh must NOT have been called.
    assert not calls, f"build-shell.sh must not be called on bad override; got {calls}"
    captured = capsys.readouterr()
    assert "JAEGER_MAC_BUILD" in captured.err or "JAEGER_MAC_BUILD" in captured.out


# ── shell-boundary tests (invoke the real build-app.sh via bash) ─────────────
# These tests run bash directly on build-app.sh and check that validation
# occurs before any swift invocation. They are fast (the script exits before
# calling swift) and deterministic; NOT marked @pytest.mark.subprocess so
# they run in the default unit tier.


def _run_build_script(env_override: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_override}
    return subprocess.run(
        ["bash", str(_SCRIPT.with_name("build-root.sh"))],
        capture_output=True, text=True, env=env, timeout=15, check=False,
    )


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_rejects_in_repo_build_dir(tmp_path):
    """Script must exit non-zero with 'outside the repository' when JAEGER_MAC_BUILD
    resolves outside the repository."""
    repo = _SCRIPT.parents[4]
    result = _run_build_script({"JAEGER_MAC_BUILD": str(repo / "inside_build")})
    assert result.returncode != 0
    assert "outside the repository" in result.stderr


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_rejects_symlink_to_repo(tmp_path):
    """Script must exit non-zero when JAEGER_MAC_BUILD is a symlink pointing
    outside the repository."""
    repo = _SCRIPT.parents[4]
    link = tmp_path / "sneaky"
    link.symlink_to(repo / "jaeger_ai")
    result = _run_build_script({"JAEGER_MAC_BUILD": str(link)})
    assert result.returncode != 0
    assert "outside the repository" in result.stderr


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_rejects_dangerous_root(tmp_path):
    """Script must exit non-zero for dangerous broad root /."""
    result = _run_build_script({"JAEGER_MAC_BUILD": "/"})
    assert result.returncode != 0
    assert "dedicated build directory" in result.stderr


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_accepts_path_with_spaces(tmp_path):
    """Read-only resolution must succeed without starting Swift or creating output."""
    ext = tmp_path / "my build dir" / "swift-build"
    result = _run_build_script({"JAEGER_MAC_BUILD": str(ext)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(ext.resolve())
    assert not ext.exists()


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_accepts_tilde_override(tmp_path):
    """Tilde in JAEGER_MAC_BUILD should be expanded and accepted (not inside repo,
    not a dangerous root)."""
    result = _run_build_script({"JAEGER_MAC_BUILD": "~/.jaeger/test-shell-build"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(Path("~/.jaeger/test-shell-build").expanduser().resolve())


@pytest.mark.skipif(not _SCRIPT.exists(), reason="build-app.sh not in tree")
def test_shell_fails_hard_when_resolver_unavailable(tmp_path):
    """When python3 is replaced with a stub that exits 1, the script must exit
    non-zero with a diagnostic. It must NOT produce an app bundle."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_py = fake_bin / "python3"
    fake_py.write_text("#!/bin/bash\necho '[fake-python3] always fails' >&2\nexit 1\n")
    fake_py.chmod(0o755)
    new_path = f"{fake_bin}:{os.environ.get('PATH', '')}"
    result = _run_build_script({"PATH": new_path})
    assert result.returncode != 0
    # Script must not produce a bundle — assert the "build root" confirmation
    # message never appeared (i.e., we exited before mkdir/build).
    assert "build root:" not in result.stdout


def test_real_build_invocation_uses_external_scratch_without_running_swift(tmp_path):
    """Execute the producer up to a sentinel Swift command, never a real build."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    swift = fake_bin / "swift"
    swift.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\nexit 91\n")
    swift.chmod(0o755)
    output = tmp_path / "build with spaces"
    env = {**os.environ, "JAEGER_MAC_BUILD": str(output),
           "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    # The script itself must enforce import purity, independent of the runner.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
    repo = _SCRIPT.parents[4]
    caches = [repo / "jaeger_ai" / "__pycache__",
              repo / "jaeger_ai" / "cli" / "__pycache__"]
    before = {str(p): p.stat().st_mtime_ns for directory in caches
              for p in directory.glob("*.pyc")}
    result = subprocess.run(["bash", str(_SCRIPT)], env=env,
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 91, result.stderr
    assert ["--scratch-path", str(output.resolve() / "scratch")] == result.stdout.splitlines()[-2:]
    assert output.is_dir()
    assert not (output / "JaegerShell.app").exists()
    after = {str(p): p.stat().st_mtime_ns for directory in caches
             for p in directory.glob("*.pyc")}
    assert after == before


def test_lifecycle_launch_passes_checkout_to_external_app(tmp_path, monkeypatch):
    from jaeger_ai.cli.verbs import lifecycle_verbs as lv

    repo = tmp_path / "checkout with spaces"
    bundle = tmp_path / "external" / "JaegerShell.app"
    monkeypatch.setattr(lv, "REPO_ROOT", repo)
    calls = []
    monkeypatch.setattr(lv, "_command", lambda cmd: calls.append(cmd)
                        or subprocess.CompletedProcess(cmd, 0))
    assert lv._open_app_bundle(bundle).returncode == 0
    assert calls == [["open", "--env", f"JAEGER_REPO={repo}", str(bundle)]]


def test_invalid_build_override_does_not_launch_another_installed_app(tmp_path, monkeypatch, capsys):
    from jaeger_ai.cli.verbs import lifecycle_verbs as lv

    monkeypatch.setattr(lv, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("JAEGER_MAC_BUILD", str(tmp_path / "inside"))
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert lv._find_app_bundle() is None
    assert "Invalid Mac build configuration" in capsys.readouterr().err


# ── mac_app_is_stale freshness tests ──────────────────────────────────────


def _make_fake_bundle(base: Path) -> Path:
    bundle = base / "JaegerShell.app"
    exe = bundle / "Contents" / "MacOS" / "JaegerShell"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"\x7fELF")
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    return bundle


def _make_fake_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    swift_dir = repo / "jaeger_ai" / "interfaces" / "macos-shell"
    swift_dir.mkdir(parents=True)
    (swift_dir / "Package.swift").write_text("// swift-tools-version:5.9\n")
    sources = swift_dir / "Sources"
    sources.mkdir()
    (sources / "main.swift").write_text("import Foundation\n")
    return repo


def _stamp(bundle: Path, repo: Path) -> None:
    from jaeger_ai.cli._common import mac_source_fingerprint
    fp = mac_source_fingerprint(repo)
    (bundle / "Contents" / "Resources" / "build-source-hash").write_text(fp + "\n")


def test_stale_missing_executable(tmp_path):
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = tmp_path / "JaegerShell.app"
    bundle.mkdir()
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_legacy_bundle_no_stamp(tmp_path):
    """Bundle with executable but no build-source-hash (old build) → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_legacy_bundle_has_only_build_commit(tmp_path):
    """Bundle with build-commit but no build-source-hash (pre-fingerprint build) → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    (bundle / "Contents" / "Resources" / "build-commit").write_text("abc1234\n")
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_empty_stamp(tmp_path):
    """Bundle with an empty build-source-hash (failed stamp write) → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    (bundle / "Contents" / "Resources" / "build-source-hash").write_text("  \n")
    assert mac_app_is_stale(repo, bundle) is True


def test_fresh_after_unchanged_build(tmp_path):
    """Freshly stamped bundle, nothing changed → fresh."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    assert mac_app_is_stale(repo, bundle) is False


def test_fresh_repeated_call_unchanged(tmp_path):
    """Calling stale-check twice on an unchanged tree → fresh both times."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    assert mac_app_is_stale(repo, bundle) is False
    assert mac_app_is_stale(repo, bundle) is False


def test_stale_after_tracked_file_edited(tmp_path):
    """Editing a source file after stamping → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    (repo / "jaeger_ai" / "interfaces" / "macos-shell" / "Sources" / "main.swift").write_text(
        "import Foundation\nlet x = 1\n"
    )
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_after_untracked_file_added(tmp_path):
    """Adding an untracked file to the Swift tree → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    (repo / "jaeger_ai" / "interfaces" / "macos-shell" / "Sources" / "NewFeature.swift").write_text(
        "class NewFeature {}\n"
    )
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_after_file_removed(tmp_path):
    """Removing a source file after stamping → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    (repo / "jaeger_ai" / "interfaces" / "macos-shell" / "Sources" / "main.swift").unlink()
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_after_file_renamed(tmp_path):
    """Renaming a source file after stamping → stale."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)
    _stamp(bundle, repo)
    old = repo / "jaeger_ai" / "interfaces" / "macos-shell" / "Sources" / "main.swift"
    old.rename(old.parent / "app.swift")
    assert mac_app_is_stale(repo, bundle) is True


def test_fresh_no_git_dir(tmp_path):
    """Missing source stamp remains stale even in a tarball install."""
    from jaeger_ai.cli._common import mac_app_is_stale
    repo = tmp_path / "repo"
    repo.mkdir()
    # Intentionally no .git
    bundle = _make_fake_bundle(tmp_path)
    assert mac_app_is_stale(repo, bundle) is True


def test_stale_during_build_simulation(tmp_path):
    """Simulate a source change that lands during the build.

    The stamp captures the pre-build fingerprint (source A). A file is then
    modified (source B). The bundle was compiled from A but the tree is now B
    — should be stale.
    """
    from jaeger_ai.cli._common import mac_app_is_stale, mac_source_fingerprint
    repo = _make_fake_repo(tmp_path)
    bundle = _make_fake_bundle(tmp_path)

    # Pre-build fingerprint (what build-app.sh writes before swift build)
    pre_build_fp = mac_source_fingerprint(repo)
    (bundle / "Contents" / "Resources" / "build-source-hash").write_text(pre_build_fp + "\n")

    # Source changes arrive mid-build
    (repo / "jaeger_ai" / "interfaces" / "macos-shell" / "Sources" / "main.swift").write_text(
        "// changed during build\nimport Foundation\n"
    )

    # The built artifact reflects the pre-build source, but tree is now different
    assert mac_app_is_stale(repo, bundle) is True
