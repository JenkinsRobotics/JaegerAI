"""Clean-install dependency graph stays reproducible and internally consistent."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
COMMIT_PIN = re.compile(r"@[0-9a-f]{40}$")
JAEGER_OS_RELEASE_REF = "@0.9.0"
JAEGER_OS_RELEASE_COMMIT = "149de70b4e2289e01ef49407e4ae8c37a4b23185"


def _git_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "git+https://github.com/JenkinsRobotics/" in line and not line.lstrip().startswith("#")
    ]


def test_git_dependencies_are_release_locked():
    rows = _git_requirements(ROOT / "requirements.txt")
    assert len(rows) == 4
    framework = next(row for row in rows if row.startswith("jaeger-os "))
    assert framework.endswith(JAEGER_OS_RELEASE_REF)
    assert all(
        COMMIT_PIN.search(row)
        for row in rows
        if not row.startswith("jaeger-os ")
    )

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert JAEGER_OS_RELEASE_COMMIT in requirements


def test_framework_dependency_points_to_jaeger_os_repository():
    rows = _git_requirements(ROOT / "requirements.txt")
    framework = next(row for row in rows if row.startswith("jaeger-os "))
    assert "/JenkinsRobotics/JaegerOS@" in framework
    assert "/JenkinsRobotics/JaegerAI@" not in framework


def test_installer_never_bypasses_dependency_resolution():
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--no-deps" not in installer
    assert "for sib in JaegerOS jaeger-agent JaegerKokoroTTS JaegerWhisperSTT" in installer
