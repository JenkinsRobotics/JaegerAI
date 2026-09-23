"""Prevent developer-machine paths from entering executable product code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOTS = (
    ROOT / "jaeger_ai",
    ROOT / "packages" / "jaeger-agent" / "jaeger_agent",
    ROOT / "packages" / "jaeger-os" / "jaeger_os",
    ROOT / "packages" / "jaeger-kokoro-tts" / "jaeger_kokoro_tts",
)


def _concrete_homes(text: str, *, python: bool) -> set[str]:
    """Inspect executable string literals, not prose, comments or regex syntax."""
    if python:
        tree = ast.parse(text)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        strings = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
    else:
        strings = [text]
    homes: set[str] = set()
    for value in strings:
        value = re.sub(r"https?://\S+", "", value)
        homes.update(re.findall(r"(?<![\w/])/(?:Users|home)/([\w.-]+)(?=/|\s|$)", value))
    return homes - {"you", "user", "me", "example", "tester", "x", "runner", "ares", "areswebui"}


def test_executable_sources_contain_no_absolute_macos_home_paths() -> None:
    findings: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in source_root.rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part in {"dev", "tests", "references", "evals"} for part in relative.parts):
                continue
            if any(part == ".build" for part in relative.parts):
                continue
            # Markdown is documentation/skill prose, not executable configuration.
            if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            concrete = _concrete_homes(text, python=path.suffix == ".py")
            if relative.as_posix() == "jaeger_ai/vendor/hermes_agent/tools/environments/daytona.py":
                # Remote sandbox image's account, not an operator home on this host.
                concrete.discard("daytona")
            if concrete:
                findings.append(str(relative))

    assert findings == [], (
        "Executable sources must derive home directories from pathlib, the "
        "environment, or instance layout; personal home paths found in:\n"
        + "\n".join(findings)
    )


@pytest.mark.parametrize("source, expected", [
    ('ROOT = "/Users/alice/state"', {"alice"}),
    ('ROOT = Path("/home/bob/state")', {"bob"}),
    ('command = "cp /Users/alice/file /tmp/file"', {"alice"}),
    ('ROOT = f"/Users/alice/{filename}"', {"alice"}),
    ('ROOT = f"/home/{username}/state"', set()),
    ('"""Example: /home/alice/state"""\n# /Users/bob/state\nROOT = None', set()),
    ('pattern = r"(?:/home/|~/)[a-z]+"', set()),
    ('hint = "/mnt/c/Users/<username>/Documents"', set()),
])
def test_personal_path_scanner_distinguishes_code_from_examples(source, expected):
    assert _concrete_homes(source, python=True) == expected
