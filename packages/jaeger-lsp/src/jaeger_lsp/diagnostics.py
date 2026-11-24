"""Fast bounded post-edit diagnostics (opencode feedback-loop pattern)."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    file: str
    line: int
    col: int
    severity: str
    message: str
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
        }


@dataclass(frozen=True)
class DiagnosticReport:
    ok: bool
    path: str
    language: str
    checker: str
    diagnostics: tuple[Diagnostic, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "language": self.language,
            "checker": self.checker,
            "error_count": sum(1 for d in self.diagnostics if d.severity == "error"),
            "warning_count": sum(1 for d in self.diagnostics if d.severity == "warning"),
            "diagnostics": [d.to_dict() for d in self.diagnostics[:30]],
            "error": self.error,
        }


def _check_python(path: Path, timeout_s: float) -> DiagnosticReport:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return DiagnosticReport(
            ok=False,
            path=str(path),
            language="python",
            checker="python-ast",
            diagnostics=(Diagnostic(
                file=str(path),
                line=int(exc.lineno or 1),
                col=int(exc.offset or 1),
                severity="error",
                message=exc.msg or "syntax error",
                source="python-ast",
            ),),
        )
    ruff = shutil.which("ruff")
    if ruff:
        try:
            res = subprocess.run(
                [ruff, "check", "--output-format=json", "--select=E,F", str(path)],
                capture_output=True, text=True, timeout=timeout_s, check=False,
            )
            if res.stdout.strip().startswith("["):
                items = json.loads(res.stdout)
                diags = tuple(
                    Diagnostic(
                        file=str(path),
                        line=int((it.get("location") or {}).get("row") or 1),
                        col=int((it.get("location") or {}).get("column") or 1),
                        severity="error" if str(it.get("code", "")).startswith("F") else "warning",
                        message=f"{it.get('code', '')}: {it.get('message', '')}".strip(": "),
                        source="ruff",
                    )
                    for it in items[:30]
                )
                has_err = any(d.severity == "error" for d in diags)
                return DiagnosticReport(ok=not has_err, path=str(path), language="python", checker="ruff", diagnostics=diags)
        except Exception:
            pass
    return DiagnosticReport(ok=True, path=str(path), language="python", checker="python-ast")


def _check_json(path: Path) -> DiagnosticReport:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return DiagnosticReport(
            ok=False,
            path=str(path),
            language="json",
            checker="json",
            diagnostics=(Diagnostic(str(path), exc.lineno, exc.colno, "error", exc.msg, "json"),),
        )
    return DiagnosticReport(ok=True, path=str(path), language="json", checker="json")


def _check_js(path: Path, timeout_s: float) -> DiagnosticReport:
    node = shutil.which("node")
    if not node:
        return DiagnosticReport(ok=True, path=str(path), language="javascript", checker="none")
    try:
        res = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=timeout_s, check=False)
        if res.returncode != 0:
            msg = (res.stderr or res.stdout or "syntax error").strip().splitlines()[:4]
            return DiagnosticReport(
                ok=False, path=str(path), language="javascript", checker="node-check",
                diagnostics=(Diagnostic(str(path), 1, 1, "error", " | ".join(msg), "node"),),
            )
    except subprocess.TimeoutExpired:
        return DiagnosticReport(ok=True, path=str(path), language="javascript", checker="node-check", error="timed out")
    return DiagnosticReport(ok=True, path=str(path), language="javascript", checker="node-check")


def _check_swift(path: Path, timeout_s: float) -> DiagnosticReport:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return DiagnosticReport(ok=True, path=str(path), language="swift", checker="none")
    try:
        res = subprocess.run([swiftc, "-parse", str(path)], capture_output=True, text=True, timeout=timeout_s, check=False)
        if res.returncode != 0:
            lines = [ln.strip() for ln in (res.stderr or "").splitlines() if ": error:" in ln][:10]
            diags = tuple(Diagnostic(str(path), 1, 1, "error", ln, "swiftc") for ln in (lines or [(res.stderr or "swift parse error").strip()[:240]]))
            return DiagnosticReport(ok=False, path=str(path), language="swift", checker="swiftc-parse", diagnostics=diags)
    except subprocess.TimeoutExpired:
        return DiagnosticReport(ok=True, path=str(path), language="swift", checker="swiftc-parse", error="timed out")
    return DiagnosticReport(ok=True, path=str(path), language="swift", checker="swiftc-parse")


def check_file_diagnostics(path: str | Path, *, timeout_s: float = 8.0) -> DiagnosticReport:
    """Run fast syntax/lint diagnostics on a single edited file. Never raises."""
    p = Path(path).expanduser()
    if not p.is_file():
        return DiagnosticReport(ok=False, path=str(p), language="unknown", checker="none", error="file not found")
    suffix = p.suffix.lower()
    if suffix == ".py":
        return _check_python(p, timeout_s)
    if suffix == ".json":
        return _check_json(p)
    if suffix in (".js", ".mjs", ".cjs"):
        return _check_js(p, timeout_s)
    if suffix == ".swift":
        return _check_swift(p, timeout_s)
    return DiagnosticReport(ok=True, path=str(p), language=suffix.lstrip(".") or "text", checker="noop")
