from pathlib import Path
import subprocess
import sys

from jaeger_ai.core.native_app import swift_app_bundle, swift_build_dir


def test_builder_and_launchers_share_external_location(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_SWIFT_BUILD_DIR", str(tmp_path / "native builds"))
    repo = tmp_path / "source checkout"
    from jaeger_ai.core import native_app

    actual = subprocess.check_output(
        [sys.executable, native_app.__file__, str(repo)], text=True).strip()
    assert Path(actual) == swift_build_dir(repo)
    assert swift_app_bundle(repo) == Path(actual) / "JaegerAI.app"


def test_checkouts_do_not_overwrite_each_others_native_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_SWIFT_BUILD_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert swift_build_dir(first) != swift_build_dir(second)
    assert not swift_build_dir(first).is_relative_to(first)
    assert swift_build_dir(first).is_relative_to(tmp_path / ".cache")


def test_staleness_checks_authoritative_swift_sources(tmp_path, monkeypatch):
    from jaeger_ai.cli._common import swift_app_is_stale

    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    source = repo / "jaeger_ai/interfaces/swift/Sources/main.swift"
    source.parent.mkdir(parents=True)
    source.write_text("// first version\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "first")
    bundle = tmp_path / "build/JaegerAI.app"
    binary = bundle / "Contents/MacOS/JaegerAI"
    binary.parent.mkdir(parents=True)
    binary.touch()
    stamp = bundle / "Contents/Resources/build-commit"
    stamp.parent.mkdir()
    stamp.write_text(git("rev-parse", "HEAD"))
    assert not swift_app_is_stale(repo, bundle)
    source.write_text("// second version\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "second")
    assert swift_app_is_stale(repo, bundle)
