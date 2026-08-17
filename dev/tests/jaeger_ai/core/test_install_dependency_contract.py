"""Clean-install dependency graph stays reproducible and internally consistent."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
COMMIT_PIN = re.compile(r"@[0-9a-f]{40}$")


def _git_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "git+https://github.com/JenkinsRobotics/" in line and not line.lstrip().startswith("#")
    ]


def test_all_git_dependencies_are_commit_pinned():
    rows = _git_requirements(ROOT / "requirements.txt")
    assert len(rows) == 4
    assert all(COMMIT_PIN.search(row) for row in rows)


def test_framework_dependency_points_to_jaeger_os_repository():
    rows = _git_requirements(ROOT / "requirements.txt")
    framework = next(row for row in rows if row.startswith("jaeger-os "))
    assert "/JenkinsRobotics/JaegerOS@" in framework
    assert "/JenkinsRobotics/JaegerAI@" not in framework


def test_installer_never_bypasses_dependency_resolution():
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--no-deps" not in installer
    assert "for sib in JaegerOS jaeger-agent JaegerKokoroTTS JaegerWhisperSTT" in installer
