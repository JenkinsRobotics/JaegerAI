"""Gateway-owned Authorized Task Handling (model-independent workflows & scoped owner grants).

Separates four distinct questions on every task:
  1. What is the user trying to accomplish? (filename lookup vs. secret audit vs. connect vs. recover)
  2. What has the authenticated owner actually authorized Jaeger to do? (scoped grants; untrusted
     text from webpages, files, or tool outputs can NEVER widen permissions)
  3. What can the OS, device, or account actually do? (real verification, strict host keys, real prerequisites)
  4. Did the cloud provider decline, or did Jaeger attempt the operation and hit a real blocker?

All four workflows run directly inside the Gateway with zero cloud model required, zero file-content
egress for filename lookups, and zero private-key exposure to models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from jaeger_tools import (
    RemoteHostRegistry,
    connect_remote_host,
    discover_remote_routes,
    discover_ssh_config_hosts,
    discover_tailscale_peers,
    probe_ssh_alias,
)


VALID_GRANT_OPERATIONS = frozenset({"find_metadata", "audit_secrets", "read_content"})
_UNTRUSTED_ORIGINS = frozenset({"webpage", "file", "document", "tool_output", "external", "untrusted"})
_FORBIDDEN_GRANT_DIRS = (".ssh", ".aws", ".gnupg", ".kube")
_SKIP_WALK_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
})

# Defensive secret patterns for Workflow 2 (always masked, never exported raw)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("github_token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("api_secret_key", re.compile(r"\b(sk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{16,})\b")),
    ("slack_token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{12,})\b")),
    ("private_key_block", re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)")),
)

_PROVIDER_REFUSAL_RE = re.compile(
    r"\b(?:"
    r"i\s+(?:cannot|can't|won't|will\s+not|am\s+unable\s+to|must\s+decline)\s+(?:assist|help|search|find|locate|access|connect|provide|fulfill|comply|do\s+that)"
    r"|credential\s+harvest"
    r"|unauthorized\s+access"
    r"|cannot\s+(?:search|scan|dig|look)\s+(?:for|through).*?(?:credential|password|key|secret|file)"
    r"|against\s+my\s+(?:safety|usage|ethical)\s+(?:guidelines|policies|rules)"
    r"|unable\s+to\s+(?:assist|help)\s+with\s+(?:this|that)\s+request"
    r")\b",
    re.IGNORECASE,
)

_HOST_KEY_ERR_RE = re.compile(
    r"(?:host\s+key\s+verification\s+failed|remote\s+host\s+identification\s+has\s+changed|offending.*key|unknown\s+host\s+key)",
    re.IGNORECASE,
)


def mask_secret_value(raw: str) -> str:
    """Mask a detected secret so raw credentials never leave the audit or reach chat/models."""
    s = (raw or "").strip()
    if s.startswith("-----BEGIN"):
        return "-----BEGIN [REDACTED PRIVATE KEY]-----"
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}****{s[-4:]}"


def looks_like_provider_refusal(text: str) -> bool:
    """Detect when a cloud LLM declined a request without attempting a tool."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_PROVIDER_REFUSAL_RE.search(cleaned))


def assert_owner_origin(origin: str) -> None:
    """Enforce that untrusted text (webpages, files, documents, tool outputs) cannot grant or widen access."""
    norm = (origin or "").strip().lower()
    if norm != "owner":
        raise PermissionError(
            f"Untrusted origin {origin!r} cannot widen permissions or invoke owner-authorized operations; "
            "only direct authenticated owner requests are permitted."
        )


@dataclass(frozen=True, slots=True)
class FolderGrant:
    root: str
    operations: tuple[str, ...] = ("find_metadata", "audit_secrets")
    granted_by: str = "owner"
    granted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "operations": list(self.operations),
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedSettings:
    """Separate owner-controlled settings: Direct Chat (tone/sensitivity) & Owner Autonomy (routine grants)."""

    direct_chat: bool = True
    owner_autonomy: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskAttemptReceipt:
    """Evidence-backed receipt separating attempt, result, and exact failure/decision layer."""

    workflow: str
    status: str  # verified_success | blocked_prerequisite | attempted_failed | ambiguous_selection | denied_grant
    layer: str  # gateway | provider | jaeger_policy | os_permission | host_unreachable | device_lock
    summary: str
    attempted: list[str] = field(default_factory=list)
    verified_result: dict[str, Any] = field(default_factory=dict)
    blocker: str = ""
    unblock_step: str = ""
    used_cloud_model: bool = False
    provider_decision: str = "not_called"  # not_called | declined | fulfilled

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.status == "verified_success",
            "workflow": self.workflow,
            "status": self.status,
            "layer": self.layer,
            "summary": self.summary,
            "attempted": list(self.attempted),
            "verified_result": dict(self.verified_result),
            "blocker": self.blocker,
            "unblock_step": self.unblock_step,
            "used_cloud_model": self.used_cloud_model,
            "provider_decision": self.provider_decision,
        }

    def format_chat_report(self) -> str:
        lines = [self.summary]
        if self.provider_decision == "declined":
            lines.append("- **Provider decision:** The cloud model declined this request; Jaeger continued via its built-in local Gateway workflow (no private data was forwarded to another cloud provider).")
        if self.attempted:
            lines.append(f"- **Attempted:** {'; '.join(self.attempted)}")
        lines.append(f"- **Status:** `{self.status}` (layer: `{self.layer}`, cloud model used: `{'yes' if self.used_cloud_model else 'no'}`)")
        if self.blocker:
            lines.append(f"- **Blocker:** {self.blocker}")
        if self.unblock_step:
            lines.append(f"- **Next step:** {self.unblock_step}")
        return "\n".join(lines)


class AuthorizedGrantStore:
    """Persists owner-scoped folder/operation grants and Direct Chat / Owner Autonomy settings."""

    def __init__(self, state_dir: Path, *, default_workspace: Path | None = None) -> None:
        self._path = Path(state_dir).expanduser().resolve() / "authorized_grants.json"
        self._default_workspace = Path(default_workspace).expanduser().resolve() if default_workspace else None
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def _default_payload(self) -> dict[str, Any]:
        grants: list[dict[str, Any]] = []
        if self._default_workspace is not None:
            grants.append(
                FolderGrant(
                    root=str(self._default_workspace),
                    operations=("find_metadata", "audit_secrets"),
                ).to_dict()
            )
        return {
            "settings": AuthorizedSettings().to_dict(),
            "folder_grants": grants,
        }

    def _read_raw(self) -> dict[str, Any]:
        if not self._path.is_file():
            return self._default_payload()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return self._default_payload()

    def _write_raw(self, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f".{self._path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

    def get_settings(self) -> AuthorizedSettings:
        with self._lock:
            raw = self._read_raw().get("settings") or {}
            return AuthorizedSettings(
                direct_chat=bool(raw.get("direct_chat", True)),
                owner_autonomy=bool(raw.get("owner_autonomy", True)),
            )

    def update_settings(
        self,
        *,
        direct_chat: bool | None = None,
        owner_autonomy: bool | None = None,
        origin: str = "owner",
    ) -> AuthorizedSettings:
        assert_owner_origin(origin)
        with self._lock:
            payload = self._read_raw()
            cur = self.get_settings()
            updated = AuthorizedSettings(
                direct_chat=cur.direct_chat if direct_chat is None else bool(direct_chat),
                owner_autonomy=cur.owner_autonomy if owner_autonomy is None else bool(owner_autonomy),
            )
            payload["settings"] = updated.to_dict()
            self._write_raw(payload)
            return updated

    def list_folder_grants(self) -> list[FolderGrant]:
        with self._lock:
            rows = self._read_raw().get("folder_grants") or []
            out: list[FolderGrant] = []
            for row in rows:
                if not isinstance(row, Mapping) or not row.get("root"):
                    continue
                ops = tuple(op for op in (row.get("operations") or ()) if op in VALID_GRANT_OPERATIONS)
                if not ops:
                    continue
                out.append(
                    FolderGrant(
                        root=str(Path(str(row["root"])).expanduser().resolve(strict=False)),
                        operations=ops,
                        granted_by=str(row.get("granted_by") or "owner"),
                        granted_at=float(row.get("granted_at") or 0.0),
                    )
                )
            return out

    def grant_folder(
        self,
        root: str | Path,
        *,
        operations: Sequence[str] = ("find_metadata",),
        origin: str = "owner",
    ) -> FolderGrant:
        assert_owner_origin(origin)
        resolved = Path(os.path.expanduser(str(root))).resolve(strict=False)
        home = Path.home().resolve(strict=False)
        fs_root = Path(os.path.sep).resolve(strict=False)
        if resolved in {home, fs_root}:
            raise PermissionError("Grants must be scoped to a specific folder, not the entire home or root filesystem.")
        for forbidden in _FORBIDDEN_GRANT_DIRS:
            froot = (home / forbidden).resolve(strict=False)
            if resolved == froot or froot in resolved.parents:
                raise PermissionError(f"Secret directory {froot} cannot be granted for direct scanning.")
        jaeger_secrets = (home / ".jaeger" / "secrets").resolve(strict=False)
        if resolved == jaeger_secrets or jaeger_secrets in resolved.parents:
            raise PermissionError("Jaeger secrets directory cannot be granted for direct scanning.")
        clean_ops = tuple(sorted({op for op in operations if op in VALID_GRANT_OPERATIONS}))
        if not clean_ops:
            raise ValueError(f"operations must include at least one of {sorted(VALID_GRANT_OPERATIONS)}")

        grant = FolderGrant(root=str(resolved), operations=clean_ops, granted_by="owner", granted_at=time.time())
        with self._lock:
            payload = self._read_raw()
            existing = [
                g for g in (payload.get("folder_grants") or [])
                if isinstance(g, Mapping) and str(Path(str(g.get("root") or "")).expanduser().resolve(strict=False)) != str(resolved)
            ]
            existing.append(grant.to_dict())
            payload["folder_grants"] = existing
            self._write_raw(payload)
        return grant

    def revoke_folder(self, root: str | Path, *, origin: str = "owner") -> bool:
        assert_owner_origin(origin)
        target = str(Path(os.path.expanduser(str(root))).resolve(strict=False))
        with self._lock:
            payload = self._read_raw()
            before = list(payload.get("folder_grants") or [])
            after = [
                g for g in before
                if not (isinstance(g, Mapping) and str(Path(str(g.get("root") or "")).expanduser().resolve(strict=False)) == target)
            ]
            if len(after) == len(before):
                return False
            payload["folder_grants"] = after
            self._write_raw(payload)
            return True

    def check_folder_grant(self, target_path: Path, operation: str) -> FolderGrant | None:
        resolved = target_path.expanduser().resolve(strict=False)
        for g in self.list_folder_grants():
            if operation not in g.operations:
                continue
            groot = Path(g.root).resolve(strict=False)
            if resolved == groot or groot in resolved.parents:
                return g
        return None


class AuthorizedTaskEngine:
    """Executes Jaeger's 4 Gateway-owned authorized workflows directly (zero cloud model needed)."""

    def __init__(
        self,
        *,
        grants: AuthorizedGrantStore,
        remote_hosts: RemoteHostRegistry,
        workspace: Path,
        ssh_config_path: Path | str | None = None,
        tailscale_bin: str | None = None,
        ssh_bin: str = "ssh",
    ) -> None:
        self.grants = grants
        self.remote_hosts = remote_hosts
        self.workspace = Path(workspace).expanduser().resolve()
        self._ssh_config_path = ssh_config_path
        self._tailscale_bin = tailscale_bin
        self._ssh_bin = ssh_bin

    # ------------------------------------------------------------------
    # Workflow 1: Find a file (filename & metadata only; NEVER opens file)
    # ------------------------------------------------------------------
    def find_file(
        self,
        filename: str,
        *,
        root: str | Path | None = None,
        origin: str = "owner",
        max_results: int = 25,
    ) -> TaskAttemptReceipt:
        try:
            assert_owner_origin(origin)
        except PermissionError as exc:
            return TaskAttemptReceipt(
                workflow="find_file",
                status="denied_grant",
                layer="jaeger_policy",
                summary=f"Blocked untrusted request to search files (origin={origin!r}).",
                attempted=[f"origin_check({origin})"],
                blocker=str(exc),
                unblock_step="Only direct authenticated owner requests can invoke file lookup.",
            )

        query = (filename or "").strip()
        if not query or len(query) > 260:
            return TaskAttemptReceipt(
                workflow="find_file",
                status="attempted_failed",
                layer="gateway",
                summary="A non-empty filename or search pattern (1-260 chars) is required.",
                attempted=["validate_query"],
                blocker="invalid_filename_query",
            )

        search_roots: list[tuple[Path, str]] = []
        if root is not None and str(root).strip():
            req_path = Path(os.path.expanduser(str(root))).resolve(strict=False)
            grant = self.grants.check_folder_grant(req_path, "find_metadata")
            if grant is None:
                return TaskAttemptReceipt(
                    workflow="find_file",
                    status="denied_grant",
                    layer="jaeger_policy",
                    summary=f"Folder `{req_path}` has not been granted for filename lookup (`find_metadata`).",
                    attempted=[f"check_folder_grant({req_path}, find_metadata)"],
                    blocker="folder_grant_missing",
                    unblock_step=f"Grant `find_metadata` access to `{req_path}` via POST /v1/authorized/grants, then retry.",
                )
            search_roots.append((req_path, grant.root))
        else:
            for g in self.grants.list_folder_grants():
                if "find_metadata" in g.operations:
                    p = Path(g.root)
                    if p.is_dir():
                        search_roots.append((p, g.root))
            if not search_roots:
                return TaskAttemptReceipt(
                    workflow="find_file",
                    status="denied_grant",
                    layer="jaeger_policy",
                    summary="No folders are currently granted for filename lookup (`find_metadata`).",
                    attempted=["list_folder_grants(find_metadata)"],
                    blocker="no_granted_folders",
                    unblock_step="Grant at least one folder (e.g. ~/Documents) via POST /v1/authorized/grants.",
                )

        q_low = query.lower()
        matches: list[dict[str, Any]] = []
        os_errors: list[str] = []
        attempted: list[str] = []
        cap = max(1, min(int(max_results or 25), 100))

        for sroot, grant_root in search_roots:
            attempted.append(f"metadata_scan({sroot})")
            if not sroot.exists():
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(sroot, followlinks=False):
                    dirnames[:] = [d for d in dirnames if d not in _SKIP_WALK_DIRS and not d.startswith(".")]
                    for fname in filenames:
                        if q_low in fname.lower():
                            fpath = Path(dirpath) / fname
                            try:
                                st = fpath.lstat()
                                matches.append({
                                    "name": fname,
                                    "path": str(fpath),
                                    "size_bytes": st.st_size,
                                    "modified_at": st.st_mtime,
                                    "grant_root": grant_root,
                                })
                            except OSError as exc:
                                os_errors.append(f"{fpath}: {exc}")
                            if len(matches) >= cap:
                                break
                    if len(matches) >= cap:
                        break
            except PermissionError as exc:
                os_errors.append(f"macOS/OS denied directory read on {sroot}: {exc}")
                return TaskAttemptReceipt(
                    workflow="find_file",
                    status="blocked_prerequisite",
                    layer="os_permission",
                    summary=f"The OS denied directory access while scanning `{sroot}`.",
                    attempted=attempted,
                    blocker=str(exc),
                    unblock_step=f"Grant macOS folder access for `{sroot}` in System Settings -> Privacy & Security -> Files and Folders.",
                )

        matches.sort(key=lambda m: (m["name"].lower() != q_low, len(m["path"])))
        if matches:
            top = matches[0]["path"]
            return TaskAttemptReceipt(
                workflow="find_file",
                status="verified_success",
                layer="gateway",
                summary=f"Found {len(matches)} match(es) for `{query}` locally without opening file contents (top match: `{top}`).",
                attempted=attempted,
                verified_result={
                    "query": query,
                    "matches": matches,
                    "count": len(matches),
                    "content_opened": False,
                    "sent_to_cloud": False,
                    "os_errors": os_errors,
                },
            )
        return TaskAttemptReceipt(
            workflow="find_file",
            status="attempted_failed",
            layer="gateway",
            summary=f"Searched {len(search_roots)} granted folder(s) for `{query}` (metadata only, no files opened) and found 0 matches.",
            attempted=attempted,
            verified_result={
                "query": query,
                "matches": [],
                "count": 0,
                "searched_roots": [str(r) for r, _ in search_roots],
                "content_opened": False,
                "sent_to_cloud": False,
                "os_errors": os_errors,
            },
            blocker="file_not_found_in_granted_folders",
            unblock_step="Grant the folder where the file lives (e.g. ~/Documents or ~/Desktop) or check the filename.",
        )

    # ------------------------------------------------------------------
    # Workflow 2: Handle credentials by purpose (defensive masked audit)
    # ------------------------------------------------------------------
    def credential_audit(
        self,
        root: str | Path | None = None,
        *,
        origin: str = "owner",
        max_files: int = 400,
    ) -> TaskAttemptReceipt:
        try:
            assert_owner_origin(origin)
        except PermissionError as exc:
            return TaskAttemptReceipt(
                workflow="credential_audit",
                status="denied_grant",
                layer="jaeger_policy",
                summary=f"Blocked untrusted request to audit secrets (origin={origin!r}).",
                attempted=[f"origin_check({origin})"],
                blocker=str(exc),
            )

        target_root = Path(os.path.expanduser(str(root))).resolve(strict=False) if root else self.workspace
        grant = self.grants.check_folder_grant(target_root, "audit_secrets")
        if grant is None:
            return TaskAttemptReceipt(
                workflow="credential_audit",
                status="denied_grant",
                layer="jaeger_policy",
                summary=f"Folder `{target_root}` has not been granted for defensive secret auditing (`audit_secrets`).",
                attempted=[f"check_folder_grant({target_root}, audit_secrets)"],
                blocker="folder_grant_missing",
                unblock_step=f"Grant `audit_secrets` on `{target_root}` via POST /v1/authorized/grants.",
            )

        findings: list[dict[str, Any]] = []
        scanned = 0
        cap = max(1, min(int(max_files or 400), 2000))
        for dirpath, dirnames, filenames in os.walk(target_root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_WALK_DIRS]
            for fname in filenames:
                if scanned >= cap:
                    break
                fpath = Path(dirpath) / fname
                try:
                    st = fpath.lstat()
                    if st.st_size > 262_144 or st.st_size == 0:
                        continue
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                scanned += 1
                for line_no, line in enumerate(text.splitlines(), start=1):
                    for kind, pat in _SECRET_PATTERNS:
                        for m in pat.finditer(line):
                            findings.append({
                                "kind": kind,
                                "path": str(fpath),
                                "line": line_no,
                                "masked_value": mask_secret_value(m.group(1)),
                            })
            if scanned >= cap:
                break

        remediation = [
            "Rotate any exposed token/key immediately with its provider.",
            "Move credentials out of project files into environment variables or OS Keychain.",
            "Add secret filenames (.env, *.pem, *.key) to .gitignore and scrub committed history with `git filter-repo` if already pushed.",
        ]
        return TaskAttemptReceipt(
            workflow="credential_audit",
            status="verified_success",
            layer="gateway",
            summary=(
                f"Defensive audit scanned {scanned} file(s) in `{target_root}`: "
                f"found {len(findings)} potential secret(s) (all values masked; raw credentials never exported)."
            ),
            attempted=[f"defensive_secret_scan({target_root}, files={scanned})"],
            verified_result={
                "root": str(target_root),
                "files_scanned": scanned,
                "finding_count": len(findings),
                "findings": findings[:100],
                "raw_secrets_exported": False,
                "remediation_steps": remediation,
            },
        )

    # ------------------------------------------------------------------
    # Workflow 3: Connect to an existing device (registered + ~/.ssh/config + Tailscale)
    # ------------------------------------------------------------------
    def connect_device(
        self,
        target: str,
        *,
        origin: str = "owner",
        alias: str = "",
        user: str = "",
        probe: bool = True,
        ssh_config_path: Path | str | None = None,
        tailscale_bin: str | None = None,
        ssh_bin: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> TaskAttemptReceipt:
        try:
            assert_owner_origin(origin)
        except PermissionError as exc:
            return TaskAttemptReceipt(
                workflow="connect_device",
                status="denied_grant",
                layer="jaeger_policy",
                summary=f"Blocked untrusted request to connect to remote device (origin={origin!r}).",
                attempted=[f"origin_check({origin})"],
                blocker=str(exc),
            )

        q = (target or "").strip()
        if not q:
            return TaskAttemptReceipt(
                workflow="connect_device",
                status="attempted_failed",
                layer="gateway",
                summary="A target device name, SSH alias, or Tailscale peer is required.",
                attempted=["validate_target"],
                blocker="missing_target",
            )

        cfg_path = ssh_config_path if ssh_config_path is not None else self._ssh_config_path
        ts_bin = tailscale_bin if tailscale_bin is not None else self._tailscale_bin
        s_bin = ssh_bin or self._ssh_bin
        attempted = [
            f"check_registered_hosts({self.remote_hosts.path.name})",
            "discover_ssh_config_profiles(~/.ssh/config)",
            "discover_tailscale_peers",
        ]

        # Check for genuine ambiguity across DISTINCT machines in ~/.ssh/config
        ssh_disc = discover_ssh_config_hosts(cfg_path)
        ssh_hosts = list(ssh_disc.get("hosts") or ())
        q_low = q.lower()
        q_tokens = [w for w in re.findall(r"[a-z0-9]+", q_low) if w not in {"my", "the", "to", "device", "computer", "machine", "pc"}]
        if q_tokens and not any(str(h.get("alias") or "").lower() == q_low for h in ssh_hosts):
            matched_profiles = [
                h for h in ssh_hosts
                if all(t in str(h.get("alias") or "").lower() or t in str(h.get("hostname") or "").lower() for t in q_tokens)
            ]
            # Group by logical device stem (e.g. rackpc / rack-pc-lan / rack-pc-overlay -> "rackpc")
            stems = {re.split(r"[-_]", str(h.get("alias") or "").lower())[0] for h in matched_profiles}
            if len(stems) > 1:
                return TaskAttemptReceipt(
                    workflow="connect_device",
                    status="ambiguous_selection",
                    layer="gateway",
                    summary=f"Multiple saved SSH devices match `{q}`: {[h['alias'] for h in matched_profiles]}. Which one should Jaeger connect to?",
                    attempted=attempted,
                    verified_result={"candidates": matched_profiles},
                    blocker="multiple_matching_devices",
                    unblock_step=f"Specify one exact alias from {[h['alias'] for h in matched_profiles]}.",
                )

        res = connect_remote_host(
            self.remote_hosts,
            q,
            alias=alias,
            user=user,
            probe=probe,
            ssh_config_path=cfg_path,
            tailscale_bin=ts_bin,
            ssh_bin=s_bin,
            runner=runner,
        )

        # Check specifically for unknown/changed host key failure (must NEVER produce false success!)
        all_stderrs = []
        if isinstance(res.get("ssh_probe"), Mapping):
            all_stderrs.append(str(res["ssh_probe"].get("stderr") or res["ssh_probe"].get("error") or ""))
        for att in (res.get("ssh_config_attempts") or ()):
            if isinstance(att, Mapping):
                all_stderrs.append(str(att.get("stderr") or att.get("error") or ""))
        joined_err = "\n".join(all_stderrs)
        if _HOST_KEY_ERR_RE.search(joined_err):
            return TaskAttemptReceipt(
                workflow="connect_device",
                status="blocked_prerequisite",
                layer="os_permission",
                summary=f"Refused connection to `{q}`: SSH host key verification failed (unknown or changed host key).",
                attempted=[*attempted, f"ssh_host_key_verify({q})"],
                verified_result={"attempts": res.get("ssh_config_attempts") or [], "raw_result": res},
                blocker="unknown_or_changed_host_key",
                unblock_step="Verify the target machine's SSH fingerprint and add/update it in `~/.ssh/known_hosts`, then retry.",
            )

        if res.get("ok") and res.get("connected"):
            remote_name = str(res.get("remote_hostname") or q)
            via = str(res.get("via") or "ssh")
            return TaskAttemptReceipt(
                workflow="connect_device",
                status="verified_success",
                layer="gateway",
                summary=f"Connected to **{remote_name}** via `{via}` (authenticated via OS SSH; private keys were never exposed to any model).",
                attempted=[*attempted, f"ssh_verify_hostname({via}) -> {remote_name}"],
                verified_result=res,
            )

        # Registered via Tailscale but SSH daemon not enabled yet on target
        if res.get("ok") and not res.get("connected"):
            probe_info = res.get("ssh_probe") if isinstance(res.get("ssh_probe"), Mapping) else {}
            return TaskAttemptReceipt(
                workflow="connect_device",
                status="blocked_prerequisite",
                layer="host_unreachable",
                summary=f"Found `{q}` on Tailscale and registered it, but SSH is not reachable yet.",
                attempted=[*attempted, "ssh_probe_tailscale_peer"],
                verified_result=res,
                blocker=str(probe_info.get("stderr") or probe_info.get("error") or "ssh_unreachable"),
                unblock_step=str(probe_info.get("setup_hint") or "Enable SSH or Tailscale SSH on the target machine."),
            )

        return TaskAttemptReceipt(
            workflow="connect_device",
            status="attempted_failed",
            layer="host_unreachable",
            summary=f"Checked registered hosts, `~/.ssh/config`, and Tailscale peers — no reachable authorized route matched `{q}`.",
            attempted=attempted,
            verified_result=res,
            blocker=str(res.get("error") or "no_matching_authorized_route"),
            unblock_step="Add the machine to your Tailscale network or configure an SSH profile in `~/.ssh/config`, then retry.",
        )

    # ------------------------------------------------------------------
    # Workflow 4: Recover access (authorized route check + data-preserving vs erasing options)
    # ------------------------------------------------------------------
    def recover_access(
        self,
        target: str,
        *,
        scenario: str = "auto",  # auto | forgot_passcode | connect_remotely
        os_hint: str = "",
        origin: str = "owner",
        ssh_config_path: Path | str | None = None,
        tailscale_bin: str | None = None,
        ssh_bin: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> TaskAttemptReceipt:
        try:
            assert_owner_origin(origin)
        except PermissionError as exc:
            return TaskAttemptReceipt(
                workflow="recover_access",
                status="denied_grant",
                layer="jaeger_policy",
                summary=f"Blocked untrusted recovery request (origin={origin!r}).",
                attempted=[f"origin_check({origin})"],
                blocker=str(exc),
            )

        low_target = f"{target} {os_hint}".lower()
        detected_os = os_hint.strip().lower()
        if not detected_os:
            if any(k in low_target for k in ("iphone", "ipad", "ios")):
                detected_os = "ios"
            elif any(k in low_target for k in ("mac", "macbook", "imac", "studio", "macos")):
                detected_os = "macos"
            elif any(k in low_target for k in ("win", "rackpc", "desktop", "pc")):
                detected_os = "windows"
            elif any(k in low_target for k in ("linux", "ubuntu", "pi", "debian")):
                detected_os = "linux"
            else:
                detected_os = "macos"

        attempted = [f"classify_access_scenario({scenario}, os={detected_os})"]
        # First check whether an existing authorized remote connection is already available!
        if scenario != "forgot_passcode" and target.strip():
            conn_receipt = self.connect_device(
                target,
                origin=origin,
                probe=True,
                ssh_config_path=ssh_config_path,
                tailscale_bin=tailscale_bin,
                ssh_bin=ssh_bin,
                runner=runner,
            )
            attempted.extend(conn_receipt.attempted)
            if conn_receipt.status == "verified_success":
                return TaskAttemptReceipt(
                    workflow="recover_access",
                    status="verified_success",
                    layer="gateway",
                    summary=f"An existing authorized connection already works: {conn_receipt.summary}",
                    attempted=attempted,
                    verified_result={
                        "mode": "existing_authorized_connection",
                        "connection": conn_receipt.verified_result,
                        "recovery_options": [],
                    },
                )

        options = _official_recovery_options(detected_os, target=target or detected_os)
        preserving = [o["method"] for o in options if o["preserves_data"]]
        erasing = [o["method"] for o in options if not o["preserves_data"]]
        prereq = options[0]["prerequisite"] if options else "Owner account sign-in or physical recovery key."
        return TaskAttemptReceipt(
            workflow="recover_access",
            status="blocked_prerequisite",
            layer="device_lock",
            summary=(
                f"No active authorized connection is available for `{target or detected_os}` (scenario: `{scenario}`, OS: `{detected_os}`). "
                f"Data-preserving recovery options: {', '.join(preserving) or 'none'}. "
                f"Data-erasing fallbacks: {', '.join(erasing) or 'none'}."
            ),
            attempted=attempted,
            verified_result={
                "target": target,
                "os": detected_os,
                "scenario": scenario,
                "recovery_options": options,
            },
            blocker="device_requires_owner_recovery_prerequisite",
            unblock_step=prereq,
        )

    # ------------------------------------------------------------------
    # Intent inference & Cloud Provider Refusal Recovery
    # ------------------------------------------------------------------
    @staticmethod
    def infer_workflow(prompt: str) -> tuple[str, dict[str, Any]] | None:
        """Infer a Gateway-owned authorized workflow from a plain owner prompt."""
        raw = (prompt or "").strip()
        if not raw:
            return None
        low = raw.lower()

        # 1. Find a file (explicit filename or "find/locate ... file")
        m_file = re.search(
            r"\b(?:find|locate|where\s+is|search\s+for)\b.*?(?:file\s+)?[`'\"]?([A-Za-z0-9._-]+\.[A-Za-z0-9]{1,10})[`'\"]?",
            raw,
            re.IGNORECASE,
        )
        if m_file:
            return ("find_file", {"filename": m_file.group(1)})

        # 2. Defensive credential audit
        if re.search(
            r"\b(?:audit|scan|check)\b.*?\b(?:committed\s+tokens?|leaked\s+(?:tokens?|secrets?|keys?)|accidental(?:ly)?\s+committed|secret\s+scan)\b",
            low,
        ):
            return ("credential_audit", {})

        # 3. Forgot passcode / locked out recovery
        if re.search(r"\b(?:forgot|lost|locked\s+out|reset)\b.*?\b(?:passcode|password|pin|lock|filevault|bitlocker|access)\b", low):
            m_dev = re.search(r"\b(?:my|the|to|on|for)\s+([A-Za-z0-9 _-]{2,32}?)(?:\s*$|[?.!,])", raw, re.IGNORECASE)
            target = m_dev.group(1).strip() if m_dev else raw[:40]
            return ("recover_access", {"target": target, "scenario": "forgot_passcode"})

        # 4. Connect to an existing device
        m_conn = re.search(
            r"\b(?:connect|ssh|remote)\s+(?:to|into)\s+(?:my\s+|the\s+)?([A-Za-z0-9._ -]{2,40})",
            raw,
            re.IGNORECASE,
        )
        if m_conn:
            target = re.split(r"[.,?!;\n]|(?:\s+(?:and|then|to\s+start|unless)\b)", m_conn.group(1), maxsplit=1)[0].strip()
            if target:
                return ("connect_device", {"target": target})

        return None

    def run_workflow(
        self,
        workflow: str,
        params: Mapping[str, Any] | None = None,
        *,
        origin: str = "owner",
        provider_decision: str = "not_called",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> TaskAttemptReceipt:
        p = dict(params or {})
        wf = (workflow or "").strip().lower()
        if wf == "find_file":
            rec = self.find_file(
                str(p.get("filename") or p.get("query") or ""),
                root=p.get("root"),
                origin=origin,
                max_results=int(p.get("max_results") or 25),
            )
        elif wf == "credential_audit":
            rec = self.credential_audit(
                root=p.get("root"),
                origin=origin,
                max_files=int(p.get("max_files") or 400),
            )
        elif wf == "connect_device":
            rec = self.connect_device(
                str(p.get("target") or ""),
                origin=origin,
                alias=str(p.get("alias") or ""),
                user=str(p.get("user") or ""),
                probe=bool(p.get("probe", True)),
                runner=runner,
            )
        elif wf == "recover_access":
            rec = self.recover_access(
                str(p.get("target") or ""),
                scenario=str(p.get("scenario") or "auto"),
                os_hint=str(p.get("os_hint") or ""),
                origin=origin,
                runner=runner,
            )
        else:
            rec = TaskAttemptReceipt(
                workflow=wf or "unknown",
                status="attempted_failed",
                layer="gateway",
                summary=f"Unsupported authorized workflow: {workflow!r}",
                attempted=["validate_workflow"],
                blocker="unsupported_workflow",
            )
        rec.provider_decision = provider_decision
        return rec

    def recover_from_provider_refusal(
        self,
        prompt: str,
        provider_reply: str,
        *,
        tool_calls_count: int = 0,
        origin: str = "owner",
    ) -> TaskAttemptReceipt | None:
        """If a cloud provider declined a benign authorized request without running tools, run the built-in workflow locally."""
        if tool_calls_count > 0 or not looks_like_provider_refusal(provider_reply):
            return None
        inferred = self.infer_workflow(prompt)
        if inferred is None:
            return None
        wf, params = inferred
        return self.run_workflow(wf, params, origin=origin, provider_decision="declined")


def _official_recovery_options(os_name: str, *, target: str) -> list[dict[str, Any]]:
    low = (os_name or "macos").lower()
    if low == "ios":
        return [
            {
                "method": "iOS Passcode Reset (72-hour previous passcode window)",
                "preserves_data": True,
                "prerequisite": "Physical access to the device within 72 hours of changing the passcode + previous passcode.",
                "steps": "Tap 'Forgot Passcode?' -> 'Try Passcode Reset' -> enter previous passcode to set a new one.",
            },
            {
                "method": "iCloud / Finder Backup Verification before Restore",
                "preserves_data": True,
                "prerequisite": "Apple Account sign-in + an existing recent iCloud or Mac Finder/iTunes backup.",
                "steps": "Sign into iCloud.com or check Mac Finder backups to confirm data is backed up before erasing.",
            },
            {
                "method": "Recovery Mode Erase & Restore via Mac/PC",
                "preserves_data": False,
                "prerequisite": "Physical USB connection to Mac/PC + Apple Account password (for Activation Lock).",
                "steps": "Put device into Recovery Mode, restore via Finder/Apple Devices app, then restore from backup.",
            },
        ]
    if low == "windows":
        return [
            {
                "method": "Microsoft Account Online Password Reset / Windows Hello Reset",
                "preserves_data": True,
                "prerequisite": "Owner sign-in to account.live.com/password/reset with registered 2FA method.",
                "steps": "Reset password at account.live.com, ensure PC has network connectivity, and sign in with the new password.",
            },
            {
                "method": "BitLocker Recovery Key (Microsoft Account / AD / MDM Escrow)",
                "preserves_data": True,
                "prerequisite": "48-digit BitLocker Recovery Key from account.microsoft.com/devices/recoverykey or printed backup.",
                "steps": "Retrieve the 48-digit recovery key matching the Key ID shown on screen to unlock the drive intact.",
            },
            {
                "method": "Windows Recovery Environment (WinRE) Reset this PC — Keep my files",
                "preserves_data": True,
                "prerequisite": "Physical access at boot (Shift + Restart -> Troubleshoot -> Reset this PC -> Keep my files).",
                "steps": "Reinstalls Windows while preserving personal files (removes installed apps/settings).",
            },
            {
                "method": "Full Clean Reinstall (Remove Everything)",
                "preserves_data": False,
                "prerequisite": "Physical access + Windows installation USB media.",
                "steps": "Wipes the drive and performs a clean Windows install (erases all local data).",
            },
        ]
    if low == "linux":
        return [
            {
                "method": "Console / Local Admin sudo Account or Escrowed LUKS Recovery Key",
                "preserves_data": True,
                "prerequisite": "Physical console access or backup LUKS passphrase/recovery key.",
                "steps": "Unlock volume with backup LUKS key or sign in with another local sudo user to reset the account password.",
            },
            {
                "method": "Live USB Backup + Clean Reinstall",
                "preserves_data": False,
                "prerequisite": "Physical boot access (note: encrypted LUKS volumes cannot be read without a valid key).",
                "steps": "Copy any unencrypted data to external storage, then reinstall the OS.",
            },
        ]
    # Default: macOS
    return [
        {
            "method": "macOS Recovery Assistant with FileVault Personal Recovery Key or Apple Account",
            "preserves_data": True,
            "prerequisite": "Physical access at startup (hold Power button on Apple Silicon) + Apple Account sign-in OR 24-character FileVault Recovery Key.",
            "steps": "Boot into macOS Recovery -> select 'Forgot all passwords?' or Terminal `resetpassword` -> unlock with Apple Account or FileVault Recovery Key.",
        },
        {
            "method": "MDM Escrowed FileVault Institutional / Personal Recovery Key",
            "preserves_data": True,
            "prerequisite": "Device enrolled in MDM + administrator access to retrieve the escrowed FileVault key.",
            "steps": "Retrieve escrowed key from MDM console and enter it at the FileVault unlock prompt.",
        },
        {
            "method": "Time Machine / External Backup Restore after Erase Mac",
            "preserves_data": False,
            "prerequisite": "Physical access + Apple Account password (for Activation Lock); erases all local disk data not in backup.",
            "steps": "In Recovery Assistant menu bar -> choose 'Erase Mac' -> reinstall macOS -> restore from Time Machine backup if available.",
        },
    ]


__all__ = [
    "AuthorizedGrantStore",
    "AuthorizedSettings",
    "AuthorizedTaskEngine",
    "FolderGrant",
    "TaskAttemptReceipt",
    "VALID_GRANT_OPERATIONS",
    "assert_owner_origin",
    "looks_like_provider_refusal",
    "mask_secret_value",
]
