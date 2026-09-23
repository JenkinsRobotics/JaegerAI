"""Static convergence evidence; never import the application or execute its tools.

Print JSON to stdout. Consumers may archive it outside the source tree. Findings
are source evidence, not proof of reachable routes or runtime response schemas.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path


def _http_method_for_dispatcher(name: str) -> str | None:
    lowered = name.lower()
    for prefix in ("handle_", "do_"):
        if lowered.startswith(prefix):
            candidate = lowered[len(prefix):].upper()
            if candidate in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                return candidate
    return None


def inspect_python(source: str) -> dict:
    tree = ast.parse(source)
    result = {key: [] for key in (
        "imports", "routes", "tools", "environment", "stores", "entrypoints",
    )}
    dispatchers = []
    for candidate in ast.walk(tree):
        if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method = _http_method_for_dispatcher(candidate.name)
        if method:
            dispatchers.append((candidate.lineno, candidate.end_lineno or candidate.lineno,
                                method, candidate.name))

    def route_context(line: int) -> tuple[str | None, str | None]:
        matches = [item for item in dispatchers if item[0] <= line <= item[1]]
        if not matches:
            return None, None
        _start, _end, method, dispatcher = min(matches, key=lambda item: item[1] - item[0])
        return method, dispatcher

    def add_route(literal: str, line: int, matcher: str = "reference") -> None:
        if not (literal.startswith(("/api/", "/v1/")) or literal == "/health"):
            return
        method, dispatcher = route_context(line)
        result["routes"].append({
            "literal": literal,
            "line": line,
            "method": method,
            "dispatcher": dispatcher,
            "matcher": matcher,
        })

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result["imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result["imports"].append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in {"main", "execute_turn", "run_turn", "run_for_voice"}:
                result["entrypoints"].append({"name": node.name, "line": node.lineno})
            for decorator in node.decorator_list:
                name = ast.unparse(decorator.func if isinstance(decorator, ast.Call) else decorator)
                if name.endswith("register_tool_from_function"):
                    metadata = {"name": node.name, "line": node.lineno,
                                "arguments": ast.unparse(node.args)}
                    if isinstance(decorator, ast.Call):
                        metadata.update({kw.arg: ast.literal_eval(kw.value)
                                         for kw in decorator.keywords
                                         if kw.arg and isinstance(kw.value, ast.Constant)})
                    result["tools"].append(metadata)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            add_route(node.value, node.lineno)
        elif isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "startswith"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                add_route(node.args[0].value, node.lineno, "prefix")
            if name in {"os.getenv", "os.environ.get", "os.environ.setdefault"}:
                if node.args and isinstance(node.args[0], ast.Constant):
                    result["environment"].append(str(node.args[0].value))
            if name in {"sqlite3.connect", "aiosqlite.connect"}:
                result["stores"].append({"line": node.lineno,
                                          "expression": ast.unparse(node)})
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            if isinstance(node.slice, ast.Constant):
                result["environment"].append(str(node.slice.value))
    for key in ("imports", "environment"):
        result[key] = sorted(set(result[key]))
    route_rank = {"reference": 0, "prefix": 1, "exact": 2}
    deduplicated: dict[tuple[str, str | None, str | None], dict] = {}
    for route in result["routes"]:
        key = (route["literal"], route["method"], route["dispatcher"])
        current = deduplicated.get(key)
        if current is None or route_rank[route["matcher"]] > route_rank[current["matcher"]]:
            deduplicated[key] = route
    result["routes"] = sorted(
        deduplicated.values(),
        key=lambda route: (route["literal"], route["method"] or "", route["line"]),
    )
    return result


def inventory(root: Path) -> dict:
    tracked = set(filter(None, subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.split("\0")))
    untracked = set(filter(None, subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.split("\0")))

    all_relatives = sorted(tracked | untracked)
    files, errors = {}, []
    for relative in all_relatives:
        path = root / relative
        record = {"kind": "file", "tracked": relative in tracked}
        if path.is_symlink():
            record = {"kind": "symlink", "target": str(path.readlink()), "tracked": relative in tracked}
        elif not path.is_file():
            record = {"kind": "missing", "tracked": relative in tracked}
        else:
            record["bytes"] = path.stat().st_size
            record["vendor"] = relative.startswith("jaeger_ai/vendor/")
            if path.suffix == ".py":
                try:
                    source = path.read_text(encoding="utf-8-sig")
                    record["lines"] = len(source.splitlines())
                    record.update(inspect_python(source))
                except (SyntaxError, UnicodeError, ValueError, RecursionError) as exc:
                    errors.append({"path": relative, "error": str(exc)})
            if path.name == "SKILL.md":
                record["kind"] = "skill"
        files[relative] = record
    return {"schema_version": 2, "coverage": "tracked and untracked non-ignored files; Python AST evidence",
            "limitations": ["Dynamic registration and computed routes require runtime probes",
                            "Route literals do not establish methods, auth, status or response schemas",
                            "Non-Python clients and launch scripts are indexed, not semantically parsed"],
            "files": files, "parse_errors": errors}


def _component_records(files: dict[str, dict]) -> list[dict]:
    roots: set[str] = set()
    for relative in files:
        parts = Path(relative).parts
        if len(parts) >= 2 and parts[0] in {"apps", "extensions"}:
            roots.add("/".join(parts[:2]))
        elif len(parts) >= 3 and parts[:2] == ("jaeger_ai", "interfaces"):
            roots.add("/".join(parts[:3]))
    records: list[dict] = []
    for component in sorted(roots):
        owned = {path: rec for path, rec in files.items()
                 if path == component or path.startswith(component + "/")}
        records.append({
            "component": component,
            "kind": "client_or_extension_candidate",
            "files": len(owned),
            "python_entrypoints": [
                {"source_file": path, **entry}
                for path, rec in owned.items()
                for entry in rec.get("entrypoints", [])
            ],
            "symlink_target": files.get(component, {}).get("target"),
            "maturity": "unclassified",
            "evidence": "filesystem and Python AST",
        })
    for path, rec in sorted(files.items()):
        for entry in rec.get("entrypoints", []):
            records.append({
                "component": path,
                "kind": "python_entrypoint",
                "entrypoint": entry,
                "maturity": "unclassified",
                "evidence": "Python AST",
            })
    return records


def _feature_records(files: dict[str, dict], root: Path) -> list[dict]:
    feature_root = root / "jaeger_ai" / "features"
    if not feature_root.is_dir():
        return []
    records: list[dict] = []
    for directory in sorted(path for path in feature_root.iterdir() if path.is_dir()):
        name = directory.name
        prefix = f"jaeger_ai/features/{name}/"
        module = f"jaeger_ai.features.{name}"
        owned = {path: rec for path, rec in files.items() if path.startswith(prefix)}
        readme = directory / "README.md"
        try:
            readme_text = readme.read_text(encoding="utf-8")
        except OSError:
            readme_text = ""
        lowered = readme_text[:4000].lower()
        maturity = "experimental" if "experimental" in lowered else "unclassified"
        importers = sorted({
            path for path, rec in files.items()
            if path not in owned and any(
                imported == module or imported.startswith(module + ".")
                for imported in rec.get("imports", [])
            )
        })
        tests = sorted(path for path in files
                       if path.startswith("dev/tests/")
                       and (f"/{name}/" in path or f"test_{name}" in path))
        records.append({
            "capability": name,
            "source_owner": prefix.rstrip("/"),
            "source_files": len(owned),
            "callers": importers,
            "configuration_keys": sorted({key for rec in owned.values()
                                           for key in rec.get("environment", [])}),
            "dependencies": sorted({imported for rec in owned.values()
                                    for imported in rec.get("imports", [])}),
            "maturity": maturity,
            "maturity_evidence": "README text" if maturity != "unclassified" else None,
            "existing_tests": tests,
            "replacement_owner": None,
            "parity_evidence": [],
            "readme": str(readme.relative_to(root)) if readme.is_file() else None,
        })
    return records


def build_domains(report: dict, root: Path) -> dict:
    files = report["files"]
    processes_clients = _component_records(files)
    stores = [
        {"source_file": path, "line": store["line"],
         "expression": store["expression"], "ownership": "unclassified",
         "evidence": "Python AST"}
        for path, rec in sorted(files.items())
        for store in rec.get("stores", [])
    ]
    features = _feature_records(files, root)

    # 4. Tools and Skills
    tool_entries = []
    skill_entries = []
    for rel_path, rec in files.items():
        if rec.get("kind") == "skill":
            skill_entries.append({
                "path": rel_path,
                "name": Path(rel_path).parent.name,
                "vendor": rec.get("vendor", False),
                "tracked": rec.get("tracked", True),
            })
        for tool_meta in rec.get("tools", []):
            tool_entries.append({
                "source_file": rel_path,
                "name": tool_meta.get("name"),
                "side_effect": tool_meta.get("side_effect", "read"),
                "vendor": rec.get("vendor", False),
                "tracked": rec.get("tracked", True),
            })

    # 5. HTTP / IPC routes
    http_routes = []
    for rel_path, rec in files.items():
        for route_meta in rec.get("routes", []):
            http_routes.append({
                "source_file": rel_path,
                "literal": route_meta.get("literal"),
                "line": route_meta.get("line"),
                "method": route_meta.get("method"),
                "matcher": route_meta.get("matcher", "reference"),
                "dispatcher": route_meta.get("dispatcher"),
                "auth_contract": "unverified",
                "request_contract": "unverified",
                "response_contract": "unverified",
                "streaming_contract": "unverified",
                "client_consumers": [],
                "vendor": rec.get("vendor", False),
            })

    return {
        "schema_version": 2,
        "evidence": "source-derived; unclassified fields require runtime verification",
        "processes_clients": processes_clients,
        "stores": stores,
        "features": features,
        "tools_skills": {"skills_count": len(skill_entries), "tools_count": len(tool_entries), "skills": skill_entries, "tools": tool_entries},
        "http_ipc": {"routes_count": len(http_routes), "routes": http_routes},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--emit-all-domains", type=Path, default=None,
                        help="Directory to write domain inventory JSON files")
    args = parser.parse_args()
    report = inventory(args.root)
    domains = build_domains(report, args.root)

    if args.emit_all_domains:
        out_dir = args.emit_all_domains
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "inventory_raw.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "features.json").write_text(json.dumps(domains["features"], indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "processes_clients.json").write_text(json.dumps(domains["processes_clients"], indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "stores.json").write_text(json.dumps(domains["stores"], indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "tools_skills.json").write_text(json.dumps(domains["tools_skills"], indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "http_ipc.json").write_text(json.dumps(domains["http_ipc"], indent=2, sort_keys=True), encoding="utf-8")
        print(f"Emitted all domain inventories to {out_dir}")

    if args.summary:
        files = report["files"]
        report = {"tracked_files": sum(item.get("tracked", True) for item in files.values()),
                  "untracked_files": sum(not item.get("tracked", True) for item in files.values()),
                  "python_files": sum("imports" in item for item in files.values()),
                  "skills": sum(item["kind"] == "skill" for item in files.values()),
                  "parse_errors": report["parse_errors"],
                  "limitations": report["limitations"]}
    if not args.emit_all_domains:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["parse_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
