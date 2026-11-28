"""Built-in production toolset registered cleanly onto any standalone ToolRegistry.

All tools respect PolicyPort + SandboxPort gating and zero upward dependencies:
- Filesystem: read_file, write_file, edit_file (lint-guarded), apply_patch, search_files, glob, repo_map
- Shell: policy + Seatbelt-sandboxed shell
- Web: bounded web_fetch
- Offload: search_offloaded_output (ReDoS-safe regex search)
- Meta: list_tools, describe_tool
- Memory & Workflows: memory_remember, memory_recall, workflow_create, workflow_status, workflow_checkpoint
- macOS (Darwin): list_mailboxes, list_mail, batch_move_mail
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from jaeger_contracts import SandboxProfile, ToolResult

from .editors import ApplyPatchEditor, SearchReplaceEditor, lint_guarded_edit
from .registry import ToolRegistry, ToolSpec
from .repomap import build_repo_map
from .web_search import web_search as run_web_search


def _safe_resolve(workspace: Path, raw_path: str, *, extra_read_roots: tuple[Path, ...] = ()) -> Path:
    p = Path(raw_path).expanduser()
    resolved = p.resolve() if p.is_absolute() else (workspace / p).resolve()
    allowed = (workspace.resolve(), *(r.expanduser().resolve() for r in extra_read_roots))
    if any(resolved == root or root in resolved.parents for root in allowed):
        return resolved
    raise PermissionError(f"Path {raw_path!r} escapes allowed workspace roots")


def register_builtin_tools(
    registry: ToolRegistry,
    *,
    workspace: Path,
    memory: Any = None,
    workflows: Any = None,
    extra_read_roots: tuple[Path, ...] = (),
    include_macos: bool = True,
    include_process_tools: bool = True,
    allow_network: bool = False,
    shell_timeout_s: float = 45.0,
) -> list[str]:
    """Register the complete built-in modular engineering & personal assistant toolset."""
    ws = workspace.expanduser().resolve()
    registered: list[str] = []

    def _add(spec: ToolSpec) -> None:
        registry.register(spec)
        registered.append(spec.name)

    # 1. Shell (Policy + Seatbelt/Elevated sandbox gated)
    if include_process_tools:
        registry.register_shell_tool(allow_network=allow_network, timeout_s=shell_timeout_s)
        registered.append("shell")

    # 2. read_file (paged line reader)
    def _read_file(args: Mapping[str, Any]) -> ToolResult:
        raw = str(args.get("path") or "").strip()
        if not raw:
            return ToolResult("read_file", False, error="path is required")
        target = _safe_resolve(ws, raw, extra_read_roots=extra_read_roots)
        if not target.is_file():
            return ToolResult("read_file", False, error=f"File not found: {raw}")
        offset = max(1, int(args.get("offset") or 1))
        limit = max(1, min(400, int(args.get("limit") or 120)))
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        chunk = lines[offset - 1 : offset - 1 + limit]
        numbered = "\n".join(f"{offset + i}: {ln}" for i, ln in enumerate(chunk))
        meta = {"total_lines": len(lines), "offset": offset, "returned": len(chunk)}
        return ToolResult("read_file", True, output=numbered, metadata=meta)

    _add(ToolSpec(
        name="read_file",
        description="Read a workspace file with line numbers and paging (offset/limit).",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        handler=_read_file,
        tier="read_only",
        read_only=True,
        tags=("file", "read", "code"),
    ))

    # 3. write_file
    def _write_file(args: Mapping[str, Any]) -> ToolResult:
        raw = str(args.get("path") or "").strip()
        content = str(args.get("content") or "")
        if not raw:
            return ToolResult("write_file", False, error="path is required")
        target = _safe_resolve(ws, raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult("write_file", True, output=f"Wrote {len(content)} chars to {target.relative_to(ws)}")

    _add(ToolSpec(
        name="write_file",
        description="Create or overwrite a file inside the workspace.",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=_write_file,
        tier="write_local",
        read_only=False,
        tags=("file", "write", "create"),
    ))

    # 4. edit_file (Aider SearchReplaceEditor + SWE-agent lint-guarded auto-rollback)
    def _edit_file(args: Mapping[str, Any]) -> ToolResult:
        raw = str(args.get("path") or "").strip()
        target = _safe_resolve(ws, raw)
        outcome = lint_guarded_edit(
            target,
            SearchReplaceEditor(),
            {
                "target": str(args.get("target") or args.get("old_text") or ""),
                "replacement": str(args.get("replacement") or args.get("new_text") or ""),
                "replace_all": bool(args.get("replace_all", False)),
            },
            workspace=ws,
        )
        return ToolResult("edit_file", outcome.ok, output=outcome.message if outcome.ok else "", error=None if outcome.ok else outcome.message)

    _add(ToolSpec(
        name="edit_file",
        description="Edit a workspace file using fault-tolerant search/replace with automatic lint rollback.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "replacement": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "target", "replacement"],
        },
        handler=_edit_file,
        tier="write_local",
        read_only=False,
        tags=("file", "edit", "patch"),
    ))

    # 5. apply_patch (Codex 4-tier seek_sequence + lint rollback)
    def _apply_patch(args: Mapping[str, Any]) -> ToolResult:
        raw = str(args.get("path") or "").strip()
        target = _safe_resolve(ws, raw)
        outcome = lint_guarded_edit(target, ApplyPatchEditor(), {"patch": str(args.get("patch") or "")}, workspace=ws)
        return ToolResult("apply_patch", outcome.ok, output=outcome.message if outcome.ok else "", error=None if outcome.ok else outcome.message)

    _add(ToolSpec(
        name="apply_patch",
        description="Apply a unified diff or SEARCH/REPLACE patch to a workspace file.",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "patch": {"type": "string"}},
            "required": ["path", "patch"],
        },
        handler=_apply_patch,
        tier="write_local",
        read_only=False,
        tags=("patch", "diff", "edit"),
    ))

    # 6. glob + search_files + repo_map
    def _glob(args: Mapping[str, Any]) -> ToolResult:
        pat = str(args.get("pattern") or "*").strip()
        matches = [
            str(p.relative_to(ws))
            for p in sorted(ws.glob(pat))
            if not any(part in (".git", "node_modules", "__pycache__", ".venv") for part in p.parts)
        ][:200]
        return ToolResult("glob", True, output="\n".join(matches))

    _add(ToolSpec(
        name="glob",
        description="Find files in the workspace matching a glob pattern (e.g. '**/*.py').",
        schema={"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        handler=_glob,
        tier="read_only",
        read_only=True,
        tags=("find", "files", "glob"),
    ))

    def _search_files(args: Mapping[str, Any]) -> ToolResult:
        pattern = str(args.get("pattern") or "").strip()
        if not pattern:
            return ToolResult("search_files", False, error="pattern is required")
        rx = re.compile(pattern, re.IGNORECASE)
        sub = str(args.get("subpath") or "").strip()
        scan = _safe_resolve(ws, sub) if sub else ws
        hits: list[str] = []
        for p in sorted(scan.rglob("*")):
            if not p.is_file() or any(part in (".git", "node_modules", "__pycache__", ".venv", "dist") for part in p.parts):
                continue
            if p.stat().st_size > 512_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for idx, ln in enumerate(text.splitlines(), 1):
                if rx.search(ln):
                    hits.append(f"{p.relative_to(ws)}:{idx}: {ln[:160]}")
                    if len(hits) >= 50:
                        return ToolResult("search_files", True, output="\n".join(hits))
        return ToolResult("search_files", True, output="\n".join(hits) or "(no matches)")

    _add(ToolSpec(
        name="search_files",
        description="Regex search across text files in the workspace.",
        schema={
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "subpath": {"type": "string"}},
            "required": ["pattern"],
        },
        handler=_search_files,
        tier="read_only",
        read_only=True,
        tags=("grep", "search", "code"),
    ))

    def _repo_map(args: Mapping[str, Any]) -> ToolResult:
        out = build_repo_map(
            ws,
            subpath=str(args.get("subpath") or ""),
            query=str(args.get("query") or ""),
            max_chars=int(args.get("max_chars") or 4000),
        )
        return ToolResult("repo_map", True, output=out or "(empty)")

    _add(ToolSpec(
        name="repo_map",
        description="Generate a PageRank-weighted symbol outline of the repository.",
        schema={
            "type": "object",
            "properties": {
                "subpath": {"type": "string"},
                "query": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
        },
        handler=_repo_map,
        tier="read_only",
        read_only=True,
        tags=("outline", "symbols", "map"),
    ))

    # 7. web_fetch
    def _web_fetch(args: Mapping[str, Any]) -> ToolResult:
        url = str(args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult("web_fetch", False, error="url must start with http:// or https://")
        req = urllib.request.Request(url, headers={"User-Agent": "JaegerAI/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                raw = resp.read(200_000).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            hint = " Do not retry this URL." if exc.code in (401, 403, 404, 410, 429) else ""
            return ToolResult("web_fetch", False, error=f"HTTP {exc.code}: {exc.reason}.{hint}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ToolResult("web_fetch", False, error=f"Fetch failed for {url}: {exc}")
        text = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())[:8000]
        return ToolResult("web_fetch", True, output=text)

    _add(ToolSpec(
        name="web_fetch",
        description="Fetch and extract readable text from an HTTP/HTTPS URL.",
        schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=_web_fetch,
        tier="read_only",
        read_only=True,
        tags=("web", "http", "fetch"),
    ))

    # 7b. web_search (Tavily / Brave / SearXNG / DuckDuckGo zero-config fallback)
    def _web_search(args: Mapping[str, Any]) -> ToolResult:
        try:
            res = run_web_search(
                str(args.get("query") or ""),
                limit=int(args.get("limit") or 5),
                provider=str(args.get("provider") or "auto"),
            )
            return ToolResult("web_search", True, output=json.dumps(res, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            return ToolResult("web_search", False, error=str(exc))

    _add(ToolSpec(
        name="web_search",
        description="Search the web (Tavily/Brave/SearXNG or DuckDuckGo fallback). Read-only.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        handler=_web_search,
        tier="read_only",
        read_only=True,
        tags=("web", "search", "internet"),
    ))

    # 7c. execute_code (sandboxed Python batch runner, Hermes code_execution parity)
    def _execute_code(args: Mapping[str, Any]) -> ToolResult:
        code = str(args.get("code") or "")
        if not code.strip():
            return ToolResult("execute_code", False, error="code is required")
        timeout_s = max(1.0, min(float(args.get("timeout_s") or 30.0), 60.0))
        py_bin = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
        argv = [py_bin, "-B", "-c", code]
        sb = getattr(registry, "_sandbox", None)
        if sb is not None:
            profile = SandboxProfile(workspace=ws, allow_network=False)
            argv = list(sb.prepare(argv, profile).argv)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        ws.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            argv,
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        stderr_lines = [
            ln for ln in (proc.stderr or "").splitlines()
            if "DARWIN_USER_TEMP_DIR" not in ln
        ]
        stderr_clean = "\n".join(stderr_lines).strip()
        out = ((proc.stdout or "").rstrip() + (("\n" + stderr_clean) if stderr_clean else "")).strip()[:16_000]
        return ToolResult(
            "execute_code",
            proc.returncode == 0,
            output=out,
            error=None if proc.returncode == 0 else f"exit code {proc.returncode}",
            metadata={"returncode": proc.returncode},
        )

    if include_process_tools:
        _add(ToolSpec(
            name="execute_code",
            description="Run a Python script snippet inside the workspace sandbox for computation or data transforms.",
            schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "timeout_s": {"type": "number", "default": 30.0},
                },
                "required": ["code"],
            },
            handler=_execute_code,
            tier="write_local",
            read_only=False,
            tags=("python", "code", "compute"),
        ))

    # 8. Memory + offload tools (when SqliteStateMemory attached)
    if memory is not None:
        def _remember(args: Mapping[str, Any]) -> ToolResult:
            memory.remember(
                str(args["key"]),
                str(args["value"]),
                subject=str(args.get("subject") or "user"),
                category=args.get("category"),
            )
            return ToolResult("memory_remember", True, output=f"Saved fact {args['key']!r}")

        _add(ToolSpec(
            name="memory_remember",
            description="Persist a durable key-value fact in SQLite memory.",
            schema={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "subject": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["key", "value"],
            },
            handler=_remember,
            tier="write_local",
            read_only=False,
            tags=("memory", "fact", "remember"),
        ))

        def _recall(args: Mapping[str, Any]) -> ToolResult:
            val = memory.recall(str(args["key"]), subject=str(args.get("subject") or "user"))
            return ToolResult("memory_recall", True, output="" if val is None else val)

        _add(ToolSpec(
            name="memory_recall",
            description="Recall a persisted key-value fact from SQLite memory.",
            schema={
                "type": "object",
                "properties": {"key": {"type": "string"}, "subject": {"type": "string"}},
                "required": ["key"],
            },
            handler=_recall,
            tier="read_only",
            read_only=True,
            tags=("memory", "fact", "recall"),
        ))

        def _search_offload(args: Mapping[str, Any]) -> ToolResult:
            matches = memory.offloader.grep(
                str(args["filename"]),
                str(args["pattern"]),
                max_matches=int(args.get("max_matches") or 25),
            )
            return ToolResult("search_offloaded_output", True, output="\n".join(matches) or "(no matches)")

        _add(ToolSpec(
            name="search_offloaded_output",
            description="Regex search inside an offloaded tool output artifact (ReDoS-safe).",
            schema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "pattern": {"type": "string"},
                    "max_matches": {"type": "integer"},
                },
                "required": ["filename", "pattern"],
            },
            handler=_search_offload,
            tier="read_only",
            read_only=True,
            tags=("offload", "search", "grep"),
        ))

    # 9. Durable workflow tools (when WorkflowEngine attached)
    if workflows is not None:
        def _wf_create(args: Mapping[str, Any]) -> ToolResult:
            run = workflows.create_run(
                name=str(args["name"]),
                steps=list(args["steps"]),
                context=dict(args.get("context") or {}),
            )
            return ToolResult("workflow_create", True, output=json.dumps(run.to_dict(), ensure_ascii=False))

        _add(ToolSpec(
            name="workflow_create",
            description="Create a durable SQLite-checkpointed multi-step workflow.",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "steps": {"type": "array"},
                    "context": {"type": "object"},
                },
                "required": ["name", "steps"],
            },
            handler=_wf_create,
            tier="write_local",
            read_only=False,
            tags=("workflow", "dag", "task"),
        ))

        def _wf_status(args: Mapping[str, Any]) -> ToolResult:
            rid = str(args.get("run_id") or "").strip()
            if rid:
                run = workflows.get_run(rid)
                if run is None:
                    return ToolResult("workflow_status", False, error=f"Workflow not found: {rid}")
                return ToolResult("workflow_status", True, output=json.dumps(run.to_dict(), ensure_ascii=False))
            runs = [r.summary() for r in workflows.list_runs(limit=int(args.get("limit") or 10))]
            return ToolResult("workflow_status", True, output=json.dumps(runs, ensure_ascii=False))

        _add(ToolSpec(
            name="workflow_status",
            description="List or inspect durable workflow runs.",
            schema={"type": "object", "properties": {"run_id": {"type": "string"}, "limit": {"type": "integer"}}},
            handler=_wf_status,
            tier="read_only",
            read_only=True,
            tags=("workflow", "status"),
        ))

    # 10. macOS Mail tools (Darwin only, backed by jaeger-macos)
    if include_macos and platform.system() == "Darwin":
        try:
            from jaeger_macos import (
                MAIL_RESOLVER_AS,
                escape_applescript,
                resolve_mailbox_call,
                run_applescript,
            )

            def _list_mailboxes(_args: Mapping[str, Any]) -> ToolResult:
                script = '''
                tell application "Mail"
                    set out to ""
                    repeat with acc in accounts
                        set accName to name of acc as string
                        set out to out & accName & ": "
                        repeat with mb in mailboxes of acc
                            set out to out & (name of mb as string) & ", "
                        end repeat
                        set out to out & linefeed
                    end repeat
                    return out
                end tell
                '''
                res = run_applescript(script, timeout_seconds=20.0, target="mail")
                ok = bool(res.get("ok"))
                return ToolResult(
                    "list_mailboxes",
                    ok,
                    output=str(res.get("raw_output") or ""),
                    error=None if ok else str(res.get("error") or "AppleScript failed"),
                )

            _add(ToolSpec(
                name="list_mailboxes",
                description="List configured Apple Mail.app accounts and mailboxes.",
                schema={"type": "object", "properties": {}},
                handler=_list_mailboxes,
                tier="read_only",
                read_only=True,
                tags=("mail", "macos", "email"),
            ))

            def _batch_move_mail(args: Mapping[str, Any]) -> ToolResult:
                account = str(args.get("account") or "").strip()
                src_mb = str(args.get("source_mailbox") or "INBOX").strip()
                dst_mb = str(args.get("destination_mailbox") or "Trash").strip()
                ids = [str(i).strip() for i in (args.get("message_ids") or []) if str(i).strip().isdigit()]
                if not account or not ids:
                    return ToolResult("batch_move_mail", False, error="account and numeric message_ids are required")
                src_call = resolve_mailbox_call("src", account, src_mb)
                dst_call = resolve_mailbox_call("dst", account, dst_mb)
                id_csv = ", ".join(ids)
                script = f'''
                {MAIL_RESOLVER_AS}
                tell application "Mail"
                    {src_call}
                    {dst_call}
                    set movedCount to 0
                    set idList to {{{id_csv}}}
                    set allIds to id of messages of src
                    repeat with idx from (count of allIds) to 1 by -1
                        if (item idx of allIds) is in idList then
                            set m to message idx of src
                            move m to dst
                            set movedCount to movedCount + 1
                        end if
                    end repeat
                    return movedCount as string
                end tell
                '''
                res = run_applescript(script, timeout_seconds=40.0, target="mail")
                ok = bool(res.get("ok"))
                raw_out = str(res.get("raw_output") or "").strip()
                return ToolResult(
                    "batch_move_mail",
                    ok,
                    output=f"Moved {raw_out} message(s)" if ok else "",
                    error=None if ok else str(res.get("error") or "AppleScript failed"),
                )

            _add(ToolSpec(
                name="batch_move_mail",
                description="Move messages by numeric ID between Apple Mail mailboxes (supports Gmail nested mailboxes).",
                schema={
                    "type": "object",
                    "properties": {
                        "account": {"type": "string"},
                        "source_mailbox": {"type": "string"},
                        "destination_mailbox": {"type": "string"},
                        "message_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["account", "destination_mailbox", "message_ids"],
                },
                handler=_batch_move_mail,
                tier="write_local",
                read_only=False,
                tags=("mail", "macos", "move"),
            ))
        except Exception:  # noqa: BLE001
            pass

    return registered


__all__ = ["register_builtin_tools"]
