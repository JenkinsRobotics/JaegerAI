"""Prevent developer-machine paths from entering executable product code."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOTS = (
    ROOT / "jaeger_ai",
    ROOT / "packages" / "jaeger-agent" / "jaeger_agent",
    ROOT / "packages" / "jaeger-os" / "jaeger_os",
    ROOT / "packages" / "jaeger-kokoro-tts" / "jaeger_kokoro_tts",
)


def test_executable_sources_contain_no_absolute_macos_home_paths() -> None:
    findings: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in source_root.rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part in {"dev", "tests", "references"} for part in relative.parts):
                continue
            if any(part == ".build" for part in relative.parts):
                continue
            if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"https?://\S+", "", text)
            text = re.sub(r"<[^>]+>/home/", "", text)
            homes = re.findall(r"/(?:Users|home)/([^/\s'\"`]+)", text)
            concrete = [
                user for user in homes
                if user.lower() not in {
                    "<you>", "<user>", "you", "user", "me", "example",
                    "tester", "x", "runner", "ares", "areswebui",
                }
            ]
            if concrete:
                findings.append(str(relative))

    assert findings == [], (
        "Executable sources must derive home directories from pathlib, the "
        "environment, or instance layout; personal home paths found in:\n"
        + "\n".join(findings)
    )
