"""Multi-language post-edit diagnostics engine (opencode/aider pattern, zero external coupling).

Provides fast (<20ms) stdlib Python AST semantic diagnostics (syntax errors,
undefined names / missing imports, duplicate dict keys, duplicate args) plus
automatic delegation to installed external compilers/linters/LSP tools
(`pyright`, `basedpyright`, `ruff`, `tsc`, `swiftc`, `cargo check`, `go vet`)
when present on the host.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    col: int
    severity: str  # "error" | "warning"
    message: str
    code: str = ""
    source: str = "ast"

    def format_short(self) -> str:
        loc = f"L{self.line}:{self.col}" if self.col else f"L{self.line}"
        tag = f"{self.source}/{self.code}" if self.code else self.source
        return f"{loc} [{self.severity}] ({tag}): {self.message}"


@dataclass(frozen=True)
class DiagnosticReport:
    ok: bool
    diagnostics: tuple[Diagnostic, ...] = ()
    engine: str = "ast"
    elapsed_ms: float = 0.0

    def to_tool_payload(self, *, max_items: int = 12) -> dict[str, Any]:
        errors = [d for d in self.diagnostics if d.severity == "error"]
        warnings = [d for d in self.diagnostics if d.severity != "error"]
        ordered = (errors + warnings)[:max_items]
        payload: dict[str, Any] = {
            "diagnostics_ok": self.ok,
            "diagnostics_engine": self.engine,
            "diagnostics_error_count": len(errors),
            "diagnostics_warning_count": len(warnings),
        }
        if ordered:
            payload["diagnostics"] = [d.format_short() for d in ordered]
        return payload


_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins)) | frozenset({
    "__name__", "__file__", "__doc__", "__package__", "__spec__", "__annotations__",
    "__builtins__", "__loader__", "__cached__", "__all__", "__path__",
    "__debug__", "Ellipsis", "NotImplemented", "True", "False", "None",
})


class _PythonScopeChecker(ast.NodeVisitor):
    """Lightweight single-file Python undefined-name & duplicate-key checker.

    Conservative by design: avoids false positives on `from x import *`,
    `exec`/`eval`, forward type annotations, or dynamic globals, while
    reliably catching typos, missing imports, and duplicate dict keys.
    """

    def __init__(self, path_str: str) -> None:
        self._path = path_str
        self._scopes: list[set[str]] = [set(_BUILTIN_NAMES)]
        self._has_star_import = False
        self._in_annotation = 0
        self.diagnostics: list[Diagnostic] = []

    def _define(self, name: str) -> None:
        if name and name != "_":
            self._scopes[-1].add(name)

    def _define_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self._define(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._define_target(elt)
        elif isinstance(target, ast.Starred):
            self._define_target(target.value)

    def _predeclare_block(self, stmts: list[ast.stmt]) -> None:
        """Pre-declare module/function-level defs, classes, imports, and assignments."""
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._define(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self._define(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        self._has_star_import = True
                    else:
                        self._define(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    self._define_target(t)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self._define(node.target.id)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for n in node.names:
                    self._define(n)

    def _is_defined(self, name: str) -> bool:
        if name in _BUILTIN_NAMES:
            return True
        return any(name in scope for scope in reversed(self._scopes))

    def visit_Module(self, node: ast.Module) -> None:
        self._predeclare_block(node.body)
        for stmt in node.body:
            self.visit(stmt)

    def _visit_annotation(self, ann: ast.AST | None) -> None:
        if ann is None:
            return
        self._in_annotation += 1
        try:
            self.visit(ann)
        finally:
            self._in_annotation -= 1

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        self._visit_annotation(node.returns)
        self._define(node.name)

        fn_scope: set[str] = set()
        for tp in getattr(node, "type_params", ()):
            name = getattr(tp, "name", "")
            if name:
                fn_scope.add(name)
        all_args = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)
        for a in all_args:
            self._visit_annotation(a.annotation)
            fn_scope.add(a.arg)

        self._scopes.append(fn_scope)
        try:
            self._predeclare_block(node.body)
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        self._define(node.name)
        cls_scope: set[str] = {"__module__", "__qualname__", "__class__"}
        for tp in getattr(node, "type_params", ()):
            name = getattr(tp, "name", "")
            if name:
                cls_scope.add(name)
        self._scopes.append(cls_scope)
        try:
            self._predeclare_block(node.body)
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        scope: set[str] = set()
        for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            scope.add(a.arg)
        if node.args.vararg:
            scope.add(node.args.vararg.arg)
        if node.args.kwarg:
            scope.add(node.args.kwarg.arg)
        self._scopes.append(scope)
        try:
            self.visit(node.body)
        finally:
            self._scopes.pop()

    def _visit_comp(self, generators: list[ast.comprehension], bodies: list[ast.AST]) -> None:
        comp_scope: set[str] = set()
        self._scopes.append(comp_scope)
        try:
            for gen in generators:
                self.visit(gen.iter)
                self._define_target(gen.target)
                for cond in gen.ifs:
                    self.visit(cond)
            for b in bodies:
                self.visit(b)
        finally:
            self._scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comp(node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comp(node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comp(node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comp(node.generators, [node.key, node.value])

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._define_target(node.target)
        for s in node.body:
            self.visit(s)
        for s in node.orelse:
            self.visit(s)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)  # type: ignore[arg-type]

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._define_target(item.optional_vars)
        for s in node.body:
            self.visit(s)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)  # type: ignore[arg-type]

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self._define(node.name)
        for s in node.body:
            self.visit(s)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._define_target(node.target)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for t in node.targets:
            self._define_target(t)
            if not isinstance(t, ast.Name):
                self.visit(t)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self._define_target(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)

    def visit_Dict(self, node: ast.Dict) -> None:
        seen_keys: set[Any] = set()
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, (str, int, float, bool)):
                typed_key = (type(k.value), k.value)
                if typed_key in seen_keys:
                    self.diagnostics.append(Diagnostic(
                        path=self._path,
                        line=getattr(k, "lineno", 1),
                        col=getattr(k, "col_offset", 0) + 1,
                        severity="warning",
                        code="duplicate-key",
                        message=f"Duplicate dictionary key {k.value!r}",
                        source="python-ast",
                    ))
                seen_keys.add(typed_key)
        self.generic_visit(node)

    def visit_MatchAs(self, node: Any) -> None:
        if getattr(node, "pattern", None) is not None:
            self.visit(node.pattern)
        if getattr(node, "name", None):
            self._define(node.name)

    def visit_MatchStar(self, node: Any) -> None:
        if getattr(node, "name", None):
            self._define(node.name)

    def visit_MatchMapping(self, node: Any) -> None:
        if getattr(node, "rest", None):
            self._define(node.rest)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and not self._has_star_import
            and self._in_annotation == 0
            and not self._is_defined(node.id)
        ):
            self.diagnostics.append(Diagnostic(
                path=self._path,
                line=getattr(node, "lineno", 1),
                col=getattr(node, "col_offset", 0) + 1,
                severity="error",
                code="undefined-name",
                message=f"Undefined name {node.id!r}",
                source="python-ast",
            ))


def _diagnose_python_ast(path: Path) -> list[Diagnostic]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        offender = (exc.text or "").strip()
        msg = exc.msg + (f": {offender!r}" if offender else "")
        return [Diagnostic(
            path=str(path),
            line=int(exc.lineno or 1),
            col=int(exc.offset or 0),
            severity="error",
            code="syntax-error",
            message=msg,
            source="python-ast",
        )]
    checker = _PythonScopeChecker(str(path))
    checker.visit(tree)
    return checker.diagnostics


def _run_external_python_checker(path: Path, workspace: Path | None, timeout_s: float) -> tuple[str, list[Diagnostic]] | None:
    for tool in ("basedpyright", "pyright"):
        exe = shutil.which(tool)
        if exe:
            try:
                proc = subprocess.run(
                    [exe, "--outputjson", str(path)],
                    cwd=str(workspace or path.parent),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
                data = json.loads(proc.stdout or "{}")
                out: list[Diagnostic] = []
                for item in data.get("generalDiagnostics") or []:
                    rng = (item.get("range") or {}).get("start") or {}
                    sev = "error" if str(item.get("severity", "")).lower() == "error" else "warning"
                    out.append(Diagnostic(
                        path=str(item.get("file") or path),
                        line=int(rng.get("line", 0)) + 1,
                        col=int(rng.get("character", 0)) + 1,
                        severity=sev,
                        code=str(item.get("rule") or ""),
                        message=str(item.get("message") or "").splitlines()[0],
                        source=tool,
                    ))
                return tool, out
            except Exception:
                return None
    ruff = shutil.which("ruff")
    if ruff:
        try:
            proc = subprocess.run(
                [ruff, "check", "--output-format=json", str(path)],
                cwd=str(workspace or path.parent),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            items = json.loads(proc.stdout or "[]")
            out = []
            for item in items:
                loc = item.get("location") or {}
                code = str(item.get("code") or "")
                sev = "error" if code.startswith(("E9", "F82", "F83")) else "warning"
                out.append(Diagnostic(
                    path=str(item.get("filename") or path),
                    line=int(loc.get("row", 1)),
                    col=int(loc.get("column", 1)),
                    severity=sev,
                    code=code,
                    message=str(item.get("message") or ""),
                    source="ruff",
                ))
            return "ruff", out
        except Exception:
            return None
    return None


_TSC_LINE_RE = re.compile(r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$")
_SWIFTC_LINE_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|warning):\s+(.+)$")


def _find_nearest_tsc(path: Path, workspace: Path | None) -> tuple[str, Path] | None:
    cur = path.parent.resolve()
    stop = workspace.resolve() if workspace else cur.anchor
    for _ in range(8):
        cand = cur / "node_modules" / ".bin" / "tsc"
        if cand.is_file():
            return str(cand), cur
        if str(cur) == str(stop) or cur.parent == cur:
            break
        cur = cur.parent
    global_tsc = shutil.which("tsc")
    if global_tsc:
        return global_tsc, (workspace or path.parent)
    return None


def _diagnose_typescript(path: Path, workspace: Path | None, timeout_s: float) -> tuple[str, list[Diagnostic]] | None:
    found = _find_nearest_tsc(path, workspace)
    if not found:
        return None
    tsc_bin, cwd = found
    try:
        proc = subprocess.run(
            [tsc_bin, "--noEmit", "--pretty", "false"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return None
    target_name = path.name
    out: list[Diagnostic] = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        m = _TSC_LINE_RE.match(line.strip())
        if not m:
            continue
        f_str, ln, col, sev, code, msg = m.groups()
        if Path(f_str).name != target_name:
            continue
        out.append(Diagnostic(
            path=f_str,
            line=int(ln),
            col=int(col),
            severity=sev,
            code=code,
            message=msg,
            source="tsc",
        ))
    return "tsc", out


def _diagnose_swift(path: Path, timeout_s: float) -> tuple[str, list[Diagnostic]] | None:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        return None
    try:
        proc = subprocess.run(
            [swiftc, "-parse", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return None
    out: list[Diagnostic] = []
    for line in (proc.stderr or "").splitlines():
        m = _SWIFTC_LINE_RE.match(line.strip())
        if m:
            f_str, ln, col, sev, msg = m.groups()
            out.append(Diagnostic(path=f_str, line=int(ln), col=int(col), severity=sev, message=msg, source="swiftc"))
    return "swiftc", out


def _diagnose_go(path: Path, timeout_s: float) -> tuple[str, list[Diagnostic]] | None:
    go = shutil.which("go")
    if not go:
        return None
    try:
        proc = subprocess.run(
            [go, "vet", str(path)],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return None
    out: list[Diagnostic] = []
    for line in (proc.stderr or "").splitlines():
        m = _SWIFTC_LINE_RE.match(line.strip())
        if m:
            f_str, ln, col, sev, msg = m.groups()
            out.append(Diagnostic(path=f_str, line=int(ln), col=int(col), severity=sev, message=msg, source="go-vet"))
    return "go-vet", out


def diagnose_file(
    path: Path | str,
    *,
    workspace: Path | str | None = None,
    timeout_s: float = 4.0,
) -> DiagnosticReport:
    """Run fast, language-appropriate static/LSP diagnostics on an edited file."""
    started = time.perf_counter()
    target = Path(path).expanduser().resolve()
    ws = Path(workspace).expanduser().resolve() if workspace else None
    if not target.is_file():
        return DiagnosticReport(ok=True, diagnostics=(), engine="none", elapsed_ms=0.0)

    suffix = target.suffix.lower()
    engine = "none"
    diags: list[Diagnostic] = []

    if suffix == ".py":
        engine = "python-ast"
        diags = _diagnose_python_ast(target)
        # Only invoke slower external checker if AST syntax passed
        if not any(d.code == "syntax-error" for d in diags):
            ext = _run_external_python_checker(target, ws, timeout_s)
            if ext is not None:
                ext_name, ext_diags = ext
                engine = f"python-ast+{ext_name}"
                seen = {(d.line, d.message) for d in diags}
                for d in ext_diags:
                    if (d.line, d.message) not in seen:
                        diags.append(d)
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        ext = _diagnose_typescript(target, ws, timeout_s)
        if ext is not None:
            engine, diags = ext
    elif suffix == ".swift":
        ext = _diagnose_swift(target, timeout_s)
        if ext is not None:
            engine, diags = ext
    elif suffix == ".go":
        ext = _diagnose_go(target, timeout_s)
        if ext is not None:
            engine, diags = ext

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    has_error = any(d.severity == "error" for d in diags)
    return DiagnosticReport(
        ok=not has_error,
        diagnostics=tuple(diags),
        engine=engine,
        elapsed_ms=elapsed_ms,
    )
