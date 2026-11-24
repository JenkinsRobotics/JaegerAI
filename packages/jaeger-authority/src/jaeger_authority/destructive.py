"""Canonical destructive-action and parsed shell-evasion classifier.

Uses POSIX shlex pipeline parsing (not raw string regexes) so:
- Obfuscated pipelines (`c\\url ... | sh`, `curl ... | env sh`, `base64 -d | bash`)
  ARE blocked cleanly.
- Harmless prose inside arguments (`rg -n 'curl .* | sh' docs`,
  `python3 -c "print('curl ... | sh')"`, `printf '%s' 'curl ... | sh' > notes.txt`)
  is NEVER false-positive blocked.
- Python `-c` / `code_exec` catches remote exec (`urllib`/`requests` + `exec`/`eval`),
  `.git/` writes, secret-store reads, and file deletion APIs.
- `git update-ref` (any ref mutation), `awk system(...)`, and shell redirects
  into `.git/` are caught cleanly.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import tempfile
from typing import Any, Mapping

from .canonical import SHELL_TOOL_IDS, canonical_tool_id

_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS = frozenset({
    "sudo", "doas", "command", "builtin", "exec", "nohup", "time", "nice",
    "ionice", "env", "xargs", "caffeinate", "stdbuf", "chronic", "unbuffer",
})
_WRAPPER_ARG_OPTS = frozenset({"-u", "-g", "-n", "-C", "-p", "-I", "-L", "-P", "-s", "-c", "-S"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
_INTERPRETERS = _SHELLS | frozenset({"python", "python3", "perl", "ruby", "node"})
_DOWNLOADERS = frozenset({"curl", "wget", "fetch"})
_DECODERS = frozenset({"base64", "xxd", "openssl"})
_DISK = frozenset({"mkfs", "wipefs", "shred", "srm", "fdisk", "sfdisk", "parted"})
_SQL_CLI = frozenset({"sqlite3", "psql", "mysql", "mariadb", "duckdb", "clickhouse-client"})
_AWK_PROGS = frozenset({"awk", "gawk", "mawk", "nawk"})

_SQL_DROP = re.compile(
    r"(?i)\b(?:drop\s+(?:database|schema|table)|truncate\s+table\b|"
    r"truncate\s+[\w.]+\s*(?:;|[\"']|$|\b(?:cascade|restrict|restart|continue)\b))"
)
_PY_DELETE = re.compile(
    r"\b(shutil\s*\.\s*rmtree|os\s*\.\s*(remove|unlink|rmdir|removedirs)|"
    r"\.\s*(unlink|rmdir)\s*\(|send2trash|subprocess\.[a-z_]+\(\s*\[?\s*['\"](rm|rmdir)['\"])"
)
_PY_REMOTE_EXEC = re.compile(
    r"(?s)(?:urllib|requests|httpx|http\.client|socket).*?\b(?:exec|eval|compile)\s*\("
    r"|\b(?:exec|eval)\s*\(.*?(?:urllib|requests|httpx|urlopen|b64decode)",
    re.IGNORECASE,
)
_PY_GIT_PATH = re.compile(
    r"['\"](?:[^'\"]*/)?\.git(?:/[^'\"]*)?['\"]",
    re.IGNORECASE,
)
_PY_SECRET_ACCESS = re.compile(
    r"['\"][^'\"]*(?:\.ssh|\.aws|\.gnupg|\.kube|secrets\.env)[^'\"]*['\"]",
    re.IGNORECASE,
)
_AWK_SYSTEM = re.compile(r"\bsystem\s*\(", re.IGNORECASE)
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_SEP_OPS = frozenset({";", "&&", "||", "&", "(", ")", ";;", "&;"})
_PIPE_OPS = frozenset({"|", "|&"})
_REDIR_OPS = frozenset({">", ">>", ">|", "1>", "1>>", "2>", "&>"})
_HEREDOC_START = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def _scratch_roots() -> tuple[str, ...]:
    roots = {
        os.path.realpath(tempfile.gettempdir()),
        "/tmp",
        "/private/tmp",
        "/var/tmp",
        os.path.realpath("/tmp"),
    }
    return tuple(sorted(r.rstrip("/") for r in roots if r))


def _in_scratch(path: str) -> bool:
    p = str(path or "").strip()
    if not p or not os.path.isabs(os.path.expanduser(p)):
        return False
    real = os.path.realpath(os.path.expanduser(p))
    return any(real.startswith(root + "/") for root in _scratch_roots())


def _strip_heredoc_bodies(command: str) -> tuple[str, list[tuple[str, str]]]:
    lines = command.splitlines()
    shell_lines: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_START.search(line)
        shell_lines.append(line)
        if m:
            delim = m.group(1)
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                body_lines.append(lines[i])
                i += 1
            bodies.append((line, "\n".join(body_lines)))
        i += 1
    return "\n".join(shell_lines), bodies


def _normalize_prog_token(tok: str) -> str:
    """Normalize a command token (e.g. `c\\url`, `/usr/bin/rm`, `\\rm` -> `curl`, `rm`)."""
    cleaned = tok.replace("\\", "")
    return os.path.basename(cleaned)


def _program(tokens: list[str]) -> tuple[str, list[str], bool]:
    """Strip env assignments and wrappers; return (basename, args, saw_sudo)."""
    i = 0
    saw_sudo = False
    while i < len(tokens):
        tok = tokens[i]
        if _ENV_ASSIGN.match(tok):
            i += 1
            continue
        name = _normalize_prog_token(tok)
        if name in {"sudo", "doas"}:
            saw_sudo = True
        if name in _WRAPPERS or name == "timeout":
            i += 1
            if name == "timeout" and i < len(tokens) and not tokens[i].startswith("-"):
                i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                opt = tokens[i]
                i += 1
                if opt in _WRAPPER_ARG_OPTS and i < len(tokens):
                    i += 1
            continue
        return name, tokens[i + 1 :], saw_sudo
    return "", [], saw_sudo


def _flags(args: list[str]) -> set[str]:
    out: set[str] = set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            out.add(a)
        elif a.startswith("-") and len(a) > 1:
            out.update(f"-{c}" for c in a[1:])
    return out


def _operands(args: list[str]) -> list[str]:
    ops: list[str] = []
    seen_dd = False
    for a in args:
        if a == "--" and not seen_dd:
            seen_dd = True
            continue
        if seen_dd or not a.startswith("-"):
            ops.append(a)
    return ops


def _tokenize_line(line: str) -> tuple[list[str], bool]:
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()>")
        lex.whitespace_split = True
        return list(lex), True
    except ValueError:
        return [], False


def _split_pipelines(tokens: list[str]) -> list[list[list[str]]]:
    """Group tokens into sequential lists of pipelines (`[[stage1, stage2], [stage3]]`)."""
    pipelines: list[list[list[str]]] = []
    cur_pipeline: list[list[str]] = []
    cur_stage: list[str] = []

    for tok in tokens:
        if tok in _SEP_OPS:
            if cur_stage:
                cur_pipeline.append(cur_stage)
                cur_stage = []
            if cur_pipeline:
                pipelines.append(cur_pipeline)
                cur_pipeline = []
        elif tok in _PIPE_OPS:
            if cur_stage:
                cur_pipeline.append(cur_stage)
                cur_stage = []
        else:
            cur_stage.append(tok)

    if cur_stage:
        cur_pipeline.append(cur_stage)
    if cur_pipeline:
        pipelines.append(cur_pipeline)
    return pipelines


def _extract_redirection_targets(stage: list[str]) -> tuple[list[str], list[str]]:
    """Split a command stage into (clean_tokens, output_redirect_targets)."""
    clean: list[str] = []
    targets: list[str] = []
    i = 0
    while i < len(stage):
        tok = stage[i]
        if tok in _REDIR_OPS:
            if i + 1 < len(stage):
                targets.append(stage[i + 1])
                i += 2
                continue
        elif tok.startswith((">>", ">|", ">")) and len(tok) > 1:
            targets.append(tok.lstrip(">|"))
            i += 1
            continue
        clean.append(tok)
        i += 1
    return clean, targets


def _python_code_evasion(code: str) -> str | None:
    """Inspect inline Python code via AST for remote exec, secret access, or .git writes."""
    if _PY_REMOTE_EXEC.search(code):
        return "python remote code execution (network fetch + exec/eval) is blocked"
    has_git = bool(_PY_GIT_PATH.search(code))
    has_secret = bool(_PY_SECRET_ACCESS.search(code))
    if has_git or has_secret:
        try:
            tree = ast.parse(code)
            calls: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        calls.add(node.func.attr)
            if has_git and (calls & {"write", "write_text", "write_bytes", "unlink", "rename", "replace"}):
                return "python code mutating .git metadata is blocked"
            if has_secret and (calls & {"open", "read_text", "read_bytes", "Path", "listdir", "scandir", "walk", "glob"}):
                return "python code accesses protected secret/authority store"
        except SyntaxError:
            return "python code references protected .git or secret store"
    return None


def _git_reason(args: list[str]) -> str | None:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"} else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1 :]
    fl = _flags(rest)

    if sub == "reset" and "--hard" in fl | set(rest):
        return "git reset --hard discards work"
    if sub in {"switch", "reset", "rebase"}:
        return f"git {sub} changes the checkout HEAD"
    if sub == "checkout" and "--" not in rest:
        if _operands(rest) or "-b" in fl or "-B" in fl:
            return "git checkout changes the checkout HEAD"
    if sub == "worktree" and rest[:1] != ["list"]:
        return "git worktree changes repository checkout state"
    if sub == "push" and (
        {"-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d"} & fl
        or any(
            a.startswith(("--force", "+")) or (a.startswith(":") and len(a) > 1)
            for a in rest
        )
    ):
        return "git push rewrites or deletes remote history"
    if sub == "clean" and ({"-f", "--force"} & fl):
        return "git clean deletes untracked files"
    if sub == "branch" and ("-D" in fl or ({"-d", "--delete"} & fl and {"-f", "--force"} & fl)):
        return "git branch -D deletes a branch"
    if sub == "stash" and rest[:1] and rest[0] in {"drop", "clear"}:
        return "git stash drop/clear discards stashed work"
    if sub == "checkout" and ({"-f", "--force"} & fl or "--" in rest):
        return "git checkout -f / -- discards local changes"
    if sub == "restore" and not ({"--staged", "-S"} & fl and not {"--worktree", "-W"} & fl):
        return "git restore discards local changes"
    if sub in {"filter-branch", "filter-repo"}:
        return f"git {sub} rewrites history"
    if sub == "update-ref":
        return "git update-ref directly mutates repository refs"
    if sub == "reflog" and rest[:1] == ["expire"]:
        return "git reflog expire drops recovery points"
    if sub == "gc" and any(a.startswith("--prune") for a in rest):
        return "git gc --prune drops unreachable objects"
    return None


def evasion_reason(command: str, depth: int = 0) -> str | None:
    """Parsed token/pipeline check for remote pipe-to-shell, encoded exec, and Python RCE.

    Unlike raw regex scanning, this parses real shell pipelines via POSIX shlex so
    harmless prose inside `rg`, `grep`, `printf`, or `python3 -c "print(...)"` is
    not false-positive blocked, while `c\\url ... | sh` and `curl ... | env sh` ARE caught.
    """
    if depth > 4:
        return "deeply nested shell evaluation cannot be verified"
    text = str(command or "").strip()
    if not text:
        return None

    shell_only, heredocs = _strip_heredoc_bodies(text)
    for header, body in heredocs:
        if re.search(r"\bpython3?\b", header):
            py_ev = _python_code_evasion(body)
            if py_ev:
                return py_ev

    for raw_line in shell_only.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens, ok = _tokenize_line(line)
        if not ok:
            continue  # handled by fail-closed destructive check
        for pipeline in _split_pipelines(tokens):
            progs: list[tuple[str, list[str]]] = []
            for raw_stage in pipeline:
                stage, targets = _extract_redirection_targets(raw_stage)
                for t in targets:
                    norm_t = t.replace("\\", "/")
                    if norm_t == ".git" or norm_t.startswith(".git/") or "/.git/" in norm_t:
                        return f"shell redirection overwrites repository metadata ({t!r})"
                prog, args, _ = _program(stage)
                progs.append((prog, args))

            # Check adjacent pipeline stages (downloader|interpreter or decoder|interpreter)
            for idx in range(len(progs) - 1):
                left_prog = progs[idx][0]
                right_prog = progs[idx + 1][0]
                if left_prog in _DOWNLOADERS and right_prog in _INTERPRETERS:
                    return f"pipe-to-shell remote code execution ({left_prog} | {right_prog}) is blocked"
                if left_prog in _DECODERS and right_prog in _INTERPRETERS:
                    return f"encoded payload piped into interpreter ({left_prog} | {right_prog}) is blocked"

            # Inspect nested `sh -c` / `python -c` bodies
            for prog, args in progs:
                if prog in _SHELLS or prog == "eval":
                    flags_c = [
                        i for i, a in enumerate(args)
                        if a.startswith("-") and "c" in a[1:] and not a.startswith("--")
                    ]
                    body = " ".join(args[flags_c[0] + 1 :]) if flags_c else (" ".join(args) if prog == "eval" else "")
                    if body:
                        nested = evasion_reason(body, depth + 1)
                        if nested:
                            return nested
                if prog in {"python", "python3"}:
                    for i, a in enumerate(args):
                        if a == "-c" and i + 1 < len(args):
                            py_ev = _python_code_evasion(args[i + 1])
                            if py_ev:
                                return py_ev
    return None


def shell_command_reason(command: str, depth: int = 0) -> str | None:
    """Return a non-empty reason if a shell command is destructive or unverifiable."""
    if depth > 4:
        return "deeply nested shell evaluation cannot be verified"
    text = str(command or "").strip()
    if not text:
        return None

    shell_only, heredocs = _strip_heredoc_bodies(text)

    for header, body in heredocs:
        if re.search(r"\bpython3?\b", header):
            if _PY_DELETE.search(body):
                return "python heredoc deletes files"

    for m in _SUBST.finditer(shell_only):
        inner = m.group(1) or m.group(2) or ""
        if inner:
            inner_reason = shell_command_reason(inner, depth + 1)
            if inner_reason:
                return inner_reason

    for raw_line in shell_only.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens, ok = _tokenize_line(line)
        if not ok:
            return "unparseable shell syntax (fail-closed)"
        for pipeline in _split_pipelines(tokens):
            for raw_stage in pipeline:
                stage, _ = _extract_redirection_targets(raw_stage)
                reason = _command_reason(stage, depth)
                if reason:
                    return reason
    return None


def _command_reason(tokens: list[str], depth: int) -> str | None:
    name, args, saw_sudo = _program(tokens)
    if not name:
        return "privilege escalation (sudo/doas)" if saw_sudo else None

    if name in _SHELLS or name == "eval":
        flags_c = [
            i for i, a in enumerate(args)
            if a.startswith("-") and "c" in a[1:] and not a.startswith("--")
        ]
        body = (
            " ".join(args[flags_c[0] + 1 :])
            if flags_c
            else (" ".join(args) if name == "eval" else "")
        )
        if body:
            inner = shell_command_reason(body, depth + 1)
            if inner:
                return inner
        if name == "eval":
            return "dynamic eval cannot be statically verified"

    if name in _AWK_PROGS:
        if any(_AWK_SYSTEM.search(a) for a in args):
            return f"{name} system() invokes arbitrary subshell commands"

    if name in {"rm", "rmdir", "unlink", "trash"}:
        ops = _operands(args)
        if name == "rm" and ({"-r", "-R", "--recursive"} & _flags(args)):
            return "rm -r recursively deletes files"
        if ops and all(_in_scratch(o) for o in ops) and not any(ch in o for o in ops for ch in "*?[{$~"):
            return None
        return f"{name} deletes files outside scratch"

    if name == "find" and (
        "-delete" in args
        or any(
            a in {"-exec", "-execdir", "-ok"}
            and i + 1 < len(args)
            and _normalize_prog_token(args[i + 1]) in {"rm", "rmdir", "unlink", "shred"}
            for i, a in enumerate(args)
        )
    ):
        return "find -delete / -exec rm deletes files"

    if name == "git":
        git_r = _git_reason(args)
        if git_r:
            return git_r
        for i, a in enumerate(args):
            if a == "-c" and i + 1 < len(args):
                kv = args[i + 1].lower()
                if any(k in kv for k in ("core.fsmonitor", "core.sshcommand", "core.hookspath", "core.pager")):
                    return f"git -c {args[i + 1]!r} injects arbitrary hook/command execution"

    if name == "tar" and any("checkpoint-action" in a for a in args):
        return "tar --checkpoint-action executes arbitrary commands"

    if name == "dd" and any(a.startswith("of=") for a in args):
        return "dd of= overwrites a file or device"

    if name in _DISK or name.startswith("mkfs"):
        return f"{name} destroys data"

    if name == "diskutil" and args[:1] and re.match(r"(?i)(erase|zero|secureErase|partition|reformat)", args[0]):
        return "diskutil erase destroys a volume"

    if name in {"dropdb", "dropuser"}:
        return f"{name} drops a database object"

    if name == "redis-cli" and any(a.lower() in {"flushall", "flushdb"} for a in args):
        return "redis FLUSHALL/FLUSHDB drops data"

    if name in _SQL_CLI:
        joined = " ".join(args)
        if _SQL_DROP.search(joined):
            return f"{name} executes destructive SQL (DROP/TRUNCATE)"

    if name in {"python", "python3"}:
        for i, a in enumerate(args):
            if a == "-c" and i + 1 < len(args) and _PY_DELETE.search(args[i + 1]):
                return "python -c deletes files"

    if saw_sudo:
        return f"privilege escalation via sudo/doas ({name})"

    return None


def destructive_reason(tool_name: str, arguments: Mapping[str, Any]) -> str | None:
    """Canonical destructive-action check across shell, code_exec, file, and DB tools."""
    tool = canonical_tool_id(tool_name)
    args = arguments or {}

    if tool in SHELL_TOOL_IDS:
        cmd = str(args.get("command") or args.get("cmd") or "")
        return shell_command_reason(cmd)

    if tool == "delete_file":
        path = str(args.get("path") or args.get("file_path") or args.get("TargetFile") or "")
        if path and _in_scratch(path):
            return None
        return f"delete_file removes {path or 'a file'} outside scratch"

    if tool == "code_exec":
        code = str(args.get("code") or args.get("script") or "")
        py_ev = _python_code_evasion(code)
        if py_ev:
            return py_ev
        if _PY_DELETE.search(code):
            return "code execution deletes files"
        return None

    if tool == "git_push":
        if args.get("force") or args.get("force_with_lease") or args.get("delete") or args.get("mirror"):
            return "git_push rewrites or deletes remote history"
        return None

    if any(tok in tool for tok in ("drop_table", "drop_database", "truncate_table", "wipe_")):
        return f"{tool} destroys persistent data"

    return None
