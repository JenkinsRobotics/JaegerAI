"""Verification Layer Contract (UPAA Principle 14 & Invariant 7).

Core Invariant:
    ATTEMPTED ACTION ≠ VERIFIED SUCCESS
    TOOL SUCCESS ≠ OBJECTIVE VERIFIED
    EFFECT RECORDED ≠ OBJECTIVE VERIFIED

Explicitly separates:
1. Execution Attempted (tool call dispatched)
2. Tool Returned Success (exit code 0 / successful tool response)
3. Effect Recorded (EffectLedger CAS / checkpoint accounting)
4. Objective Verified (ground-truth real-world state inspection confirming target goal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Sequence

logger = logging.getLogger("jaeger.entity.verification")


class VerificationStatus(str, Enum):
    ATTEMPTED = "attempted"
    TOOL_SUCCESS = "tool_success"
    EFFECT_RECORDED = "effect_recorded"
    OBJECTIVE_VERIFIED = "objective_verified"
    OBJECTIVE_UNVERIFIED = "objective_unverified"
    OBJECTIVE_FAILED = "objective_failed"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    target_objective: str
    evidence: str
    verifier: str
    verified_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status == VerificationStatus.OBJECTIVE_VERIFIED


class VerificationContract:
    """Evaluates and records ground-truth assertions verifying real-world outcomes."""

    @staticmethod
    def verify_disk_state(
        path: Path | str,
        *,
        must_exist: bool = True,
        content_predicate: Callable[[str], bool] | None = None,
        objective: str = "Verify disk state",
    ) -> VerificationResult:
        """Inspect the real-world filesystem state independently of tool return claims."""
        target = Path(path).resolve()
        exists = target.exists()

        if must_exist and not exists:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} does not exist on disk",
                verifier="disk_probe",
                error="FileNotFound",
            )
        if not must_exist and exists:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} unexpectedly exists on disk",
                verifier="disk_probe",
                error="FileExists",
            )

        if must_exist and content_predicate is not None:
            try:
                content = target.read_text(encoding="utf-8")
                if not content_predicate(content):
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_FAILED,
                        target_objective=objective,
                        evidence=f"Content predicate failed for {target}",
                        verifier="content_predicate",
                        error="ContentMismatch",
                    )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Failed reading {target}: {exc}",
                    verifier="content_predicate",
                    error=str(exc),
                )

        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_VERIFIED,
            target_objective=objective,
            evidence=f"Verified real-world filesystem state at {target}",
            verifier="disk_probe",
        )

    @staticmethod
    def verify_filesystem_write(
        target_path: Path | str | None,
        expected_content: str | None = None,
        objective: str = "Verify filesystem write",
    ) -> VerificationResult:
        """Verify ground-truth outcome of a file modification or creation."""
        if not target_path:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_UNVERIFIED,
                target_objective=objective,
                evidence="No target path provided to verify",
                verifier="none",
            )
        pred = (lambda c: expected_content in c) if expected_content is not None else None
        return VerificationContract.verify_disk_state(
            target_path,
            must_exist=True,
            content_predicate=pred,
            objective=objective,
        )

    @staticmethod
    def evaluate_tool_consequence(
        tool_name: str,
        tool_return: Any,
        *,
        objective: str = "",
        external_verifier: Callable[[Any], bool] | None = None,
    ) -> VerificationResult:
        """Distinguish raw tool success from independent objective verification."""
        is_tool_ok = False
        if isinstance(tool_return, dict):
            is_tool_ok = bool(tool_return.get("ok", True)) and not tool_return.get("error")
        elif tool_return is not None:
            is_tool_ok = True

        if not is_tool_ok:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective or f"Execute tool {tool_name}",
                evidence=f"Tool {tool_name} reported execution error",
                verifier=f"tool:{tool_name}",
                error=str(tool_return.get("error") if isinstance(tool_return, dict) else "Tool error"),
            )

        # Tool returned success; check if an independent verifier validates the objective
        if external_verifier is not None:
            try:
                verified = external_verifier(tool_return)
                if verified:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_VERIFIED,
                        target_objective=objective or f"Verified outcome of {tool_name}",
                        evidence="Independent verifier confirmed objective state",
                        verifier="external_verifier",
                    )
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective or f"Outcome of {tool_name}",
                    evidence="Tool reported success, but external verifier found target objective unfulfilled",
                    verifier="external_verifier",
                    error="ObjectiveVerificationFailed",
                )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective or f"Outcome of {tool_name}",
                    evidence=f"External verifier threw an exception: {exc}",
                    verifier="external_verifier",
                    error=str(exc),
                )

        # Without an independent validator, success is only tool-syntactic, not objective-verified
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_UNVERIFIED,
            target_objective=objective or f"Execute tool {tool_name}",
            evidence=f"Tool {tool_name} returned success (syntactic confirmation only; no independent objective validator)",
            verifier=f"tool:{tool_name}",
        )


ActionVerifierFn = Callable[[str, Any, Any, Any], VerificationResult]


class VerificationRegistry:
    """Action-specific verification dispatch and registry.

    Dispatches ground-truth verification assertions to action-specific probes.
    Guarantees:
    - Never defaults an unknown task to filesystem verification.
    - Explicitly evaluates file writes, file deletions, git commits, processes,
      HTTP mutations, read-only tools, and message receipts.
    - Unknown actions strictly return OBJECTIVE_UNVERIFIED.
    """

    def __init__(self) -> None:
        self._verifiers: dict[str, ActionVerifierFn] = {}
        self._register_builtins()

    def register(self, action_type: str, verifier: ActionVerifierFn) -> None:
        self._verifiers[action_type.lower()] = verifier

    def _register_builtins(self) -> None:
        self.register("file_write", self._verify_file_write)
        self.register("file_delete", self._verify_file_delete)
        self.register("git_commit", self._verify_git_commit)
        self.register("process_start", self._verify_process_start)
        self.register("http_mutation", self._verify_http_mutation)
        self.register("read_only", self._verify_read_only)
        self.register("message_send", self._verify_message_send)

    @staticmethod
    def _verify_file_write(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        act_dict = dict(action) if isinstance(action, (dict, list)) else {}
        path = act_dict.get("path") or act_dict.get("target_path") or (result.get("path") if isinstance(result, dict) else None)
        if not path:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence="File write verification failed: no target path specified",
                verifier="file_write_verifier",
                error="MissingPath",
            )
        expected = act_dict.get("expected_content") or (result.get("expected_content") if isinstance(result, dict) else None)
        target = Path(path).resolve()
        if not target.exists():
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} does not exist after write",
                verifier="file_write_verifier",
                error="FileNotFound",
            )
        if expected is not None:
            try:
                content = target.read_text(encoding="utf-8")
                if expected not in content:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_FAILED,
                        target_objective=objective,
                        evidence=f"File {target} content does not contain expected substring",
                        verifier="file_write_verifier",
                        error="ContentMismatch",
                    )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Failed to read file {target}: {exc}",
                    verifier="file_write_verifier",
                    error=str(exc),
                )
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_VERIFIED,
            target_objective=objective,
            evidence=f"Verified file write at {target}",
            verifier="file_write_verifier",
        )

    @staticmethod
    def _verify_file_delete(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        act_dict = dict(action) if isinstance(action, (dict, list)) else {}
        path = act_dict.get("path") or act_dict.get("target_path") or (result.get("path") if isinstance(result, dict) else None)
        if not path:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence="File delete verification failed: no target path specified",
                verifier="file_delete_verifier",
                error="MissingPath",
            )
        target = Path(path).resolve()
        if target.exists():
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} still exists after delete",
                verifier="file_delete_verifier",
                error="FileStillExists",
            )
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_VERIFIED,
            target_objective=objective,
            evidence=f"Verified file deletion of {target} (does not exist)",
            verifier="file_delete_verifier",
        )

    @staticmethod
    def _verify_git_commit(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        act_dict = dict(action) if isinstance(action, (dict, list)) else {}
        ctx_dict = dict(context) if isinstance(context, (dict, list)) else {}
        repo_path = act_dict.get("repo_path") or ctx_dict.get("repo_path") or "."
        expected_msg = act_dict.get("commit_message") or act_dict.get("expected_message")
        import subprocess
        try:
            cmd = ["git", "log", "-1", "--pretty=format:%H %s"]
            proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                sha, _, msg = proc.stdout.strip().partition(" ")
                if expected_msg and expected_msg not in msg:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_FAILED,
                        target_objective=objective,
                        evidence=f"Last commit {sha[:8]} message {msg!r} does not match expected {expected_msg!r}",
                        verifier="git_commit_verifier",
                        error="CommitMismatch",
                    )
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_VERIFIED,
                    target_objective=objective,
                    evidence=f"Verified git commit {sha[:8]}: {msg}",
                    verifier="git_commit_verifier",
                )
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"Git log failed: {proc.stderr}",
                verifier="git_commit_verifier",
                error="GitLogFailed",
            )
        except Exception as exc:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"Git commit verification probe exception: {exc}",
                verifier="git_commit_verifier",
                error=str(exc),
            )

    @staticmethod
    def _verify_process_start(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        act_dict = dict(action) if isinstance(action, (dict, list)) else {}
        res_dict = dict(result) if isinstance(result, dict) else {}
        port = act_dict.get("port") or res_dict.get("port")
        pid = act_dict.get("pid") or res_dict.get("pid")
        if port is not None:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            try:
                res = sock.connect_ex(("127.0.0.1", int(port)))
                sock.close()
                if res == 0:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_VERIFIED,
                        target_objective=objective,
                        evidence=f"Verified process listening on 127.0.0.1:{port}",
                        verifier="process_probe",
                    )
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Socket connection refused on 127.0.0.1:{port}",
                    verifier="process_probe",
                    error="ConnectionRefused",
                )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Socket probe error on port {port}: {exc}",
                    verifier="process_probe",
                    error=str(exc),
                )
        if pid is not None:
            import os
            try:
                os.kill(int(pid), 0)
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_VERIFIED,
                    target_objective=objective,
                    evidence=f"Verified process PID {pid} is running",
                    verifier="process_probe",
                )
            except OSError:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Process PID {pid} is not running",
                    verifier="process_probe",
                    error="NoSuchProcess",
                )
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_UNVERIFIED,
            target_objective=objective,
            evidence="Neither port nor PID specified for process verification",
            verifier="process_probe",
        )

    @staticmethod
    def _verify_http_mutation(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        act_dict = dict(action) if isinstance(action, (dict, list)) else {}
        query_url = act_dict.get("verify_url") or act_dict.get("url")
        if not query_url:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_UNVERIFIED,
                target_objective=objective,
                evidence="HTTP mutation has no verification query endpoint; indeterminate",
                verifier="http_mutation_verifier",
            )
        import urllib.request
        try:
            req = urllib.request.Request(query_url, headers={"User-Agent": "Jaeger-Verifier"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_VERIFIED,
                        target_objective=objective,
                        evidence=f"HTTP verification GET {query_url} returned status {resp.status}",
                        verifier="http_mutation_verifier",
                    )
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"HTTP verification GET {query_url} returned non-2xx status {resp.status}",
                    verifier="http_mutation_verifier",
                    error="HttpError",
                )
        except Exception as exc:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"HTTP verification GET {query_url} failed: {exc}",
                verifier="http_mutation_verifier",
                error=str(exc),
            )

    @staticmethod
    def _verify_read_only(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        is_err = isinstance(result, dict) and (result.get("ok") is False or result.get("error"))
        if is_err:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"Read-only tool reported execution failure: {result.get('error')}",
                verifier="read_only_verifier",
                error=str(result.get("error")),
            )
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_VERIFIED,
            target_objective=objective,
            evidence="Read-only operation completed with intact result integrity; no state mutation required",
            verifier="read_only_verifier",
        )

    @staticmethod
    def _verify_message_send(objective: str, action: Any, result: Any, context: Any) -> VerificationResult:
        receipt = None
        if isinstance(result, dict):
            receipt = result.get("message_id") or result.get("receipt") or result.get("delivery_id")
        if receipt:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_VERIFIED,
                target_objective=objective,
                evidence=f"Verified message send receipt: {receipt}",
                verifier="message_send_verifier",
            )
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_UNVERIFIED,
            target_objective=objective,
            evidence="Message send completed without provider delivery receipt; indeterminate objective state",
            verifier="message_send_verifier",
        )

    def verify(
        self,
        objective: str,
        action: Any,
        result: Any,
        context: Any = None,
    ) -> VerificationResult:
        ctx = dict(context) if isinstance(context, dict) else {}
        act_dict = dict(action) if isinstance(action, dict) else {}
        act_type = str(act_dict.get("action_type") or act_dict.get("type") or "").lower()
        tool_name = str(act_dict.get("tool") or act_dict.get("tool_name") or "").lower()

        # Direct registration lookup
        verifier = self._verifiers.get(act_type)
        if verifier is None and tool_name:
            verifier = self._verifiers.get(tool_name)

        # Heuristic classification for standard tools when action_type is omitted
        if verifier is None:
            if act_type in ("file_write", "write_file") or any(k in tool_name for k in ("write", "create_file", "append")):
                verifier = self._verifiers.get("file_write")
            elif act_type in ("file_delete", "delete_file") or any(k in tool_name for k in ("delete", "remove", "unlink")):
                verifier = self._verifiers.get("file_delete")
            elif "git" in act_type or "commit" in act_type or "commit" in tool_name:
                verifier = self._verifiers.get("git_commit")
            elif any(k in act_type or k in tool_name for k in ("process", "server", "daemon", "listen")):
                verifier = self._verifiers.get("process_start")
            elif any(k in act_type or k in tool_name for k in ("http", "api", "post", "patch", "put")):
                verifier = self._verifiers.get("http_mutation")
            elif any(k in act_type or k in tool_name for k in ("read", "view", "grep", "search", "list", "cat", "get")):
                verifier = self._verifiers.get("read_only")
            elif any(k in act_type or k in tool_name for k in ("send_message", "notify", "mail")):
                verifier = self._verifiers.get("message_send")

        if verifier is not None:
            return verifier(objective, act_dict, result, ctx)

        # UNKNOWN ACTION -> strictly OBJECTIVE_UNVERIFIED, NEVER default to filesystem!
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_UNVERIFIED,
            target_objective=objective,
            evidence=f"No action-specific verifier registered for action {act_type or tool_name or 'unknown'!r}",
            verifier="unverified_default",
        )


# ── Turn-level action derivation (independent of last tool-name string) ──

_ABS_PATH = re.compile(r"(/(?:tmp|private|Users|home|var|opt)/[^\s'\"`]+)")
_REL_FILE = re.compile(
    r"\b((?:workspace/|sandbox/|skills/)?[\w./-]+\.[A-Za-z0-9]{1,8})\b"
)
_GIT_C = re.compile(r"git\s+-C\s+(\S+)")
_CD_GIT = re.compile(r"cd\s+(\S+)\s+&&\s+git\b")


def _workspace_roots(context: Any) -> list[Path]:
    roots: list[Path] = []
    ctx = dict(context) if isinstance(context, dict) else {}
    for key in ("workspace", "workspace_path", "cwd"):
        val = ctx.get(key)
        if val:
            roots.append(Path(str(val)))
    env_ws = os.environ.get("JAEGER_WORKSPACE")
    if env_ws:
        roots.append(Path(env_ws))
    roots.append(Path.cwd())
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        s = str(r)
        if s not in seen:
            seen.add(s)
            out.append(r)
    return out


def _resolve_existing_or_candidate(path: str, context: Any) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    for root in _workspace_roots(context):
        cand = (root / path).resolve()
        if cand.exists() or cand.parent.exists():
            return cand
    return (Path.cwd() / path).resolve()


def _tool_records(tool_events: Sequence[Any]) -> list[dict[str, Any]]:
    by_call: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for evt in tool_events:
        payload = getattr(evt, "payload", None)
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("tool") or payload.get("tool_name") or "").strip()
        if not name:
            continue
        call_id = str(payload.get("call_id") or "")
        rec = by_call.get(call_id) if call_id else None
        if rec is None:
            rec = {
                "tool": name,
                "arguments": {},
                "result": None,
                "error": None,
                "failed": False,
            }
            ordered.append(rec)
            if call_id:
                by_call[call_id] = rec
        rec["tool"] = name or rec["tool"]
        if payload.get("arguments"):
            rec["arguments"] = payload["arguments"]
        if "result" in payload:
            rec["result"] = payload.get("result")
        if payload.get("error"):
            rec["error"] = payload.get("error")
            rec["failed"] = True
        etype = str(getattr(evt, "event_type", ""))
        if etype.endswith("failed"):
            rec["failed"] = True
    return ordered


def derive_verification_action(
    objective: str,
    cog_result: Any,
    tool_events: Sequence[Any] | None = None,
    *,
    strategy: str = "",
    context: Any = None,
) -> dict[str, Any]:
    """Build a structured action dict from the turn's real tool consequences.

    Never treats a display string like ``complete_task(... Wrote ...)`` as a
    tool name. Mutating tools in the turn win over ledger/complete_task.
    """
    records = _tool_records(tool_events or ())
    result = cog_result if isinstance(cog_result, dict) else {}
    if not records and isinstance(result.get("tool_records"), list):
        records = [r for r in result["tool_records"] if isinstance(r, dict)]

    writes: list[dict[str, Any]] = []
    deletes: list[dict[str, Any]] = []
    git_commits: list[dict[str, Any]] = []

    for rec in records:
        name = rec["tool"]
        args = rec.get("arguments") if isinstance(rec.get("arguments"), dict) else {}
        res = rec.get("result") if isinstance(rec.get("result"), dict) else {}
        if name in {"write_file", "append_file", "patch"}:
            path = args.get("path") or res.get("path")
            content = args.get("content") or args.get("expected_content")
            if path:
                writes.append({"path": path, "expected_content": content})
        elif name in {"delete_file"}:
            path = args.get("path") or res.get("path")
            if path:
                deletes.append({"path": path})
        elif name == "terminal":
            cmd = str(args.get("command") or "")
            if re.search(r"\bgit\b.*\bcommit\b", cmd):
                repo = None
                m = _GIT_C.search(cmd) or _CD_GIT.search(cmd)
                if m:
                    repo = m.group(1).strip("'\"")
                msg_m = re.search(r'-m\s+[\'"]([^\'"]+)[\'"]', cmd)
                git_commits.append({
                    "repo_path": repo,
                    "commit_message": msg_m.group(1) if msg_m else None,
                })
            rm = re.search(r"\brm(?:\s+-[rf]+)*\s+(\S+)", cmd)
            if rm:
                deletes.append({"path": rm.group(1).strip("'\"")})
            redir = re.search(r"(?:printf|echo|cat)\b.*>\s*(\S+)", cmd)
            if redir and "git" not in cmd:
                writes.append({"path": redir.group(1).strip("'\""), "expected_content": None})

    obj = objective or ""
    obj_l = obj.lower()
    wants_delete = bool(re.search(r"\b(delete|remove|rm)\b", obj_l))
    wants_commit = bool(re.search(r"\b(git\s+commit|commit)\b", obj_l))
    wants_write = bool(re.search(r"\b(create|write|save)\b", obj_l)) and not wants_delete

    if wants_commit and git_commits:
        chosen = git_commits[-1]
        repo = chosen.get("repo_path")
        if not repo:
            abs_paths = _ABS_PATH.findall(obj)
            repo = abs_paths[0] if abs_paths else "."
        return {
            "action_type": "git_commit",
            "repo_path": repo,
            "commit_message": chosen.get("commit_message"),
            "tool": "terminal",
        }

    if wants_delete and deletes:
        path = deletes[-1]["path"]
        return {
            "action_type": "file_delete",
            "path": str(_resolve_existing_or_candidate(path, context)),
            "tool": "delete_file",
        }

    if writes and (wants_write or not wants_delete):
        with_content = [w for w in writes if w.get("expected_content")]
        chosen = with_content[-1] if with_content else writes[-1]
        abs_obj = [p.rstrip(".,;\"'") for p in _ABS_PATH.findall(obj)]
        raw_path = str(chosen["path"])
        if abs_obj and Path(abs_obj[0]).exists():
            path = abs_obj[0]
        elif Path(raw_path).is_absolute():
            path = raw_path
        else:
            path = str(_resolve_existing_or_candidate(raw_path, context))
            if abs_obj:
                path = abs_obj[0]
        expected = chosen.get("expected_content")
        if not expected:
            quoted = re.search(r"['\"]([^'\"]{2,120})['\"]", obj)
            if quoted:
                expected = quoted.group(1)
            else:
                q = re.search(r"containing(?: exactly)?(?: the words)?\s+(.+?)(?:\.|$)", obj, re.I)
                if q:
                    expected = q.group(1).strip().strip("'\"")
        if isinstance(expected, str):
            expected = re.sub(r"\s+Then stop\.?\s*$", "", expected, flags=re.I).strip()
        return {
            "action_type": "file_write",
            "path": path,
            "expected_content": expected,
            "tool": "write_file",
        }

    if strategy == "direct_response" or not records:
        return {"action_type": "unknown", "tool": ""}

    if records and all(r["tool"] in {"work_ledger", "complete_task", "read_file", "list_skill_dir", "memory"} for r in records):
        return {"action_type": "read_only", "tool": records[-1]["tool"]}

    abs_paths = [p.rstrip(".,;\"'") for p in _ABS_PATH.findall(obj)]
    expected = None
    quoted = re.search(r"['\"]([^'\"]{2,120})['\"]", obj)
    if quoted:
        expected = quoted.group(1)
    if wants_delete and abs_paths:
        return {"action_type": "file_delete", "path": abs_paths[0], "tool": "delete_file"}
    if wants_write and abs_paths:
        return {
            "action_type": "file_write",
            "path": abs_paths[0],
            "expected_content": expected,
            "tool": "write_file",
        }
    if wants_commit and abs_paths:
        return {
            "action_type": "git_commit",
            "repo_path": abs_paths[0],
            "commit_message": expected,
            "tool": "terminal",
        }

    return {"action_type": "unknown", "tool": records[-1]["tool"] if records else ""}
