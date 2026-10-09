"""Canonical detection of destructive or irreversible actions.

Constitution rule (system engineer decision 2026-10-09): deleting data,
discarding work, rewriting shared history or dropping a database needs a
FRESH owner approval for that call. Standing "always" grants, autonomy
modes, commissioning policy and operator hooks cannot waive it.

Detection is canonical, not textual: tool names go through
``canonical_tool_id`` (terminal / bash / run_shell / exec ... are one
``shell``), and a command line is split into simple commands, each with
wrappers (sudo, env, xargs, nohup, command, time, ...) and paths
(``/bin/rm``, ``\\rm``) stripped, and ``sh -c``/``eval`` bodies re-parsed.
A command that cannot be parsed is judged on its raw text, never waved
through.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from typing import Any, Mapping

_SPLIT = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\)")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS = {"sudo", "doas", "command", "builtin", "exec", "nohup", "time", "nice",
             "ionice", "env", "xargs", "caffeinate", "stdbuf", "chronic", "unbuffer"}
_WRAPPER_ARG_OPTS = {"-u", "-g", "-n", "-C", "-p", "-I", "-L", "-P", "-s", "-c"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_SQL_DROP = re.compile(r"(?i)\b(drop\s+(database|schema|table)|truncate\s+(table\s+)?\w)")
_DISK = {"mkfs", "wipefs", "shred", "srm", "fdisk", "sfdisk", "parted"}
_PY_DELETE = re.compile(
    r"\b(shutil\s*\.\s*rmtree|os\s*\.\s*(remove|unlink|rmdir|removedirs)|"
    r"\.\s*(unlink|rmdir)\s*\(|send2trash|subprocess\.[a-z_]+\(\s*\[?\s*['\"](rm|rmdir)['\"])")


def _scratch_roots() -> tuple[str, ...]:
    roots = {os.path.realpath(tempfile.gettempdir()), "/tmp", "/private/tmp", "/var/tmp",
             os.path.realpath("/tmp")}
    return tuple(sorted(r.rstrip("/") for r in roots if r))


def _in_scratch(path: str) -> bool:
    p = str(path or "").strip()
    if not p or not os.path.isabs(os.path.expanduser(p)):
        return False
    real = os.path.realpath(os.path.expanduser(p))
    return any(real.startswith(root + "/") for root in _scratch_roots())


def _program(tokens: list[str]) -> tuple[str, list[str]]:
    """Strip env assignments and wrappers; return (basename, args)."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _ENV_ASSIGN.match(tok):
            i += 1
            continue
        name = os.path.basename(tok.lstrip("\\"))
        if name in _WRAPPERS or name == "timeout":
            i += 1
            if name == "timeout" and i < len(tokens) and not tokens[i].startswith("-"):
                i += 1  # the duration
            while i < len(tokens) and tokens[i].startswith("-"):
                opt = tokens[i]
                i += 1
                if opt in _WRAPPER_ARG_OPTS and i < len(tokens):
                    i += 1
            continue
        return name, tokens[i + 1:]
    return "", []


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
    ops, seen_dd = [], False
    for a in args:
        if a == "--" and not seen_dd:
            seen_dd = True
            continue
        if seen_dd or not a.startswith("-"):
            ops.append(a)
    return ops


def _git_reason(args: list[str]) -> str | None:
    # skip global options (-C dir, -c k=v, --git-dir=...)
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-C", "-c"} else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    fl = _flags(rest)
    if sub == "reset" and "--hard" in fl | set(rest):
        return "git reset --hard discards work"
    if sub == "push" and ({"-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d"} & fl
                          or any(a.startswith(("--force", "+")) or (a.startswith(":") and len(a) > 1)
                                 for a in rest)):
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
    if sub == "update-ref" and "-d" in fl:
        return "git update-ref -d deletes a ref"
    if sub == "reflog" and rest[:1] == ["expire"]:
        return "git reflog expire drops recovery points"
    if sub == "gc" and any(a.startswith("--prune") for a in rest):
        return "git gc --prune drops unreachable objects"
    return None


def _command_reason(tokens: list[str], depth: int) -> str | None:
    name, args = _program(tokens)
    if not name:
        return None
    if name in _SHELLS or name == "eval":
        flags_c = [i for i, a in enumerate(args) if a.startswith("-") and "c" in a[1:] and not a.startswith("--")]
        body = " ".join(args[flags_c[0] + 1:]) if flags_c else (" ".join(args) if name == "eval" else "")
        return shell_command_reason(body, depth + 1) if body else None
    if name in {"rm", "rmdir", "unlink", "trash"}:
        ops = _operands(args)
        if name == "rm" and ({"-r", "-R", "--recursive"} & _flags(args)):
            return "rm -r recursively deletes files"
        if ops and all(_in_scratch(o) for o in ops) and not any(ch in o for o in ops for ch in "*?[{$~"):
            return None  # deleting inside the task scratch dir
        return f"{name} deletes files outside the task scratch dir"
    if name == "find" and ("-delete" in args or any(
            a in {"-exec", "-execdir", "-ok"} and i + 1 < len(args)
            and os.path.basename(args[i + 1]) in {"rm", "rmdir", "unlink", "shred"}
            for i, a in enumerate(args))):
        return "find -delete / -exec rm deletes files"
    if name == "git":
        return _git_reason(args)
    if name == "dd" and any(a.startswith("of=") for a in args):
        return "dd of= overwrites a file or device"
    if name in _DISK or name.startswith("mkfs"):
        return f"{name} destroys data"
    if name == "diskutil" and args[:1] and re.match(r"(?i)(erase|zero|secureErase|partition|reformat)", args[0]):
        return "diskutil erase destroys a volume"
    if name in {"dropdb", "dropuser"}:
        return f"{name} drops a database object"
    if name in {"redis-cli"} and any(a.lower() in {"flushall", "flushdb"} for a in args):
        return "redis FLUSHALL/FLUSHDB drops data"
    return None


_CONTROL = {";", "&&", "||", "|", "&", "(", ")", ";;", "|&", "&;"}
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _simple_commands(line: str) -> list[list[str]]:
    """Quote-aware split of one line into simple commands."""
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:  # unbalanced quotes: judge the raw words, never wave through
        toks = []
        for part in _SPLIT.split(line):
            toks += [t.strip("'\"") for t in part.split()] + [";"]
    out, cur = [], []
    for t in toks:
        if t in _CONTROL or (t and set(t) <= set(";&|()")):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def shell_command_reason(command: str, depth: int = 0) -> str | None:
    """Why ``command`` is destructive, or None."""
    text = str(command or "")
    if not text.strip() or depth > 4:
        return None
    if _SQL_DROP.search(text):
        return "SQL DROP/TRUNCATE drops data"
    for m in _SUBST.finditer(text):  # $(...) and `...`, quoted or not
        reason = shell_command_reason(m.group(1) or m.group(2) or "", depth + 1)
        if reason:
            return reason
    for line in re.split(r"[\n\r]+", text):
        for tokens in _simple_commands(line):
            reason = _command_reason(tokens, depth)
            if reason:
                return reason
    return None


_COMMAND_KEYS = ("command", "CommandLine", "cmd", "commandline", "script")
_PATH_KEYS = ("path", "file", "target", "TargetFile", "file_path", "filepath")


def destructive_reason(tool_name: Any, arguments: Mapping[str, Any] | None) -> str | None:
    """Why this tool call is destructive/irreversible (needs fresh owner
    approval), or None. ``tool_name`` may be any alias."""
    from jaeger_ai.core.authority.kernel import canonical_tool_id

    args = dict(arguments or {})
    cid = canonical_tool_id(tool_name)
    raw = str(tool_name or "").strip().lower()
    if cid in {"shell", "remote_shell"}:
        cmd = next((args[k] for k in _COMMAND_KEYS if args.get(k)), "")
        if isinstance(cmd, (list, tuple)):
            cmd = shlex.join(str(c) for c in cmd)
        reason = shell_command_reason(str(cmd))
        return f"{reason} ({raw or cid})" if reason else None
    if cid == "delete_file" or raw in {"remove_file", "delete_path", "delete_dir", "remove_dir", "rmtree"}:
        target = next((args[k] for k in _PATH_KEYS if args.get(k)), "")
        if target and _in_scratch(str(target)):
            return None
        return "deleting a file outside the task scratch dir"
    if cid == "code_exec":
        code = str(args.get("code") or args.get("source") or args.get("script") or "")
        if _PY_DELETE.search(code):
            return "code that deletes files"
        if _SQL_DROP.search(code):
            return "code that drops database data"
        return None
    if cid == "git_push":
        flat = " ".join(f"{k}={v}" for k, v in args.items()).lower()
        if args.get("force") or "--force" in flat or "--delete" in flat:
            return "git push rewrites or deletes remote history"
        return None
    if re.match(r"^(drop|truncate)_(database|db|table|schema)s?$", raw) or raw in {"dropdb", "drop_collection"}:
        return f"{raw} drops database data"
    if raw.startswith("git_") and raw[4:] in {"reset_hard", "force_push", "clean", "branch_delete"}:
        return f"{raw} discards or rewrites git state"
    return None
