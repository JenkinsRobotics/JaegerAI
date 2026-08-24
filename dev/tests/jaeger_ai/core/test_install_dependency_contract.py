"""Clean-install dependency graph stays reproducible and internally consistent.

Rewritten for the monorepo absorption. This file used to assert the OPPOSITE
contract: that requirements.txt carried four
``git+https://github.com/JenkinsRobotics/...`` direct references, release-locked
by tag or commit. JaegerOS, jaeger-agent and the two voice engines now live in
this repository under ``packages/`` and are installed from those paths, so the
property worth guarding is that no JenkinsRobotics code is fetched from the
network at install time — and, critically, that no package resolves JaegerOS
twice.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PACKAGES = ROOT / "packages"
IN_REPO_PACKAGES = (
    "jaeger-os",
    "jaeger-agent",
    "jaeger-kokoro-tts",
    "jaeger-whisper-stt",
)
JENKINS_GIT_PREFIX = "git+https://github.com/JenkinsRobotics/"


def _requirement_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _all_requirement_files() -> list[Path]:
    files = [ROOT / "requirements.txt"]
    files.extend(PACKAGES / pkg / "requirements.txt" for pkg in IN_REPO_PACKAGES)
    return [path for path in files if path.exists()]


def test_every_in_repo_package_is_present_and_installable():
    """The checkout carries its own framework, mind, and voice engines."""
    for pkg in IN_REPO_PACKAGES:
        pyproject = PACKAGES / pkg / "pyproject.toml"
        assert pyproject.is_file(), f"packages/{pkg}/pyproject.toml is missing"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert data["project"]["name"] == pkg


def test_no_jenkinsrobotics_code_is_fetched_from_the_network():
    """A clean clone installs without reaching GitHub for our own packages.

    That is the whole point of the absorption: `git clone && ./install.sh`
    reaches a working robot offline, and there is no window where a moved tag
    or an unreachable remote changes what gets installed.
    """
    offenders: list[str] = []
    for path in _all_requirement_files():
        for line in _requirement_lines(path):
            if JENKINS_GIT_PREFIX in line:
                offenders.append(f"{path.relative_to(ROOT)}: {line}")
    assert offenders == [], (
        "In-repo packages must be installed from packages/, not fetched:\n"
        + "\n".join(offenders)
    )


def test_jaeger_os_is_never_resolved_twice():
    """The failure mode the absorption was done to remove.

    Both voice engines used to carry their own
    ``jaeger-os @ git+...@0.9.0`` direct reference. Installing either one
    alongside the local package put two ``jaeger_os`` distributions in play with
    no defined sys.path winner. A dependent may require jaeger-os; it may not
    name a SOURCE for it.
    """
    offenders: list[str] = []
    for pkg in IN_REPO_PACKAGES:
        if pkg == "jaeger-os":
            continue
        for line in _requirement_lines(PACKAGES / pkg / "requirements.txt"):
            normalized = line.replace(" ", "")
            if normalized.startswith("jaeger-os@") or (
                "jaeger-os" in normalized and "@git+" in normalized
            ):
                offenders.append(f"packages/{pkg}/requirements.txt: {line}")
        pyproject = PACKAGES / pkg / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for dep in data.get("project", {}).get("dependencies", []) or []:
            normalized = str(dep).replace(" ", "")
            if normalized.startswith("jaeger-os@"):
                offenders.append(f"packages/{pkg}/pyproject.toml: {dep}")
    assert offenders == [], (
        "jaeger-os must be required as a version range, never as a direct "
        "reference, so the in-repo package satisfies it:\n" + "\n".join(offenders)
    )


def test_installer_installs_in_repo_packages_before_the_root_package():
    """Order is load-bearing.

    jaeger-agent and both engines require ``jaeger-os``. Installing JaegerOS
    from packages/ first means that requirement is already satisfied locally;
    resolving the root package first would send pip looking for it.
    """
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--no-deps" not in installer
    loop = 'for pkg in jaeger-os jaeger-agent jaeger-kokoro-tts jaeger-whisper-stt'
    assert loop in installer
    assert installer.index(loop) < installer.index('-e "$REPO_ROOT"')


def test_installer_no_longer_lets_a_sibling_checkout_shadow_the_repo():
    """The override this restructure made both meaningless and dangerous."""
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'for sib in JaegerOS jaeger-agent JaegerKokoroTTS JaegerWhisperSTT' not in installer
    assert "SIBLINGS_FOUND" not in installer
