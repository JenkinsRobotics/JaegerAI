"""Composable, fail-closed ToolInspector chain (goose + AutoGPT MIT + ag2 + JaegerAI)."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from jaeger_contracts import ActionProposal, AutonomyMode, DecisionKind, PolicyVerdict

from .canonical import (
    IDENTITY_TOOL_IDS,
    KNOWN_ACTION_TYPES,
    KNOWN_TIERS,
    MEMORY_WRITE_TOOL_IDS,
    OWNER_MANAGEMENT_TOOL_IDS,
    PRIVILEGED_TOOL_IDS,
    SHELL_TOOL_IDS,
    canonical_tool_id,
    is_owner_actor,
    is_untrusted_actor,
)
from .destructive import destructive_reason, evasion_reason

_SENSITIVE_HOME_DIRS = (".ssh", ".aws", ".gnupg", ".kube", ".jaeger")
_ALWAYS_DENIED_HOME_DIRS = (".ssh", ".aws", ".gnupg", ".kube")
_READ_TOOL_IDS = frozenset({
    "read_file", "read_many_files", "search_offloaded_output",
    "glob", "search_files", "list_skill_dir", "ocr_file",
})
_JAEGER_DENIED_SEGMENTS = frozenset({
    "secrets", "credentials", "caller_tokens", "config", "control", "audit",
})
_JAEGER_DENIED_SUFFIXES = (".env", ".sqlite3", ".sqlite", ".db", ".key", ".pem")
_JAEGER_DENIED_FILENAMES = frozenset({
    "permissions.json", "remote_access.json", "webui_remote_password",
    "agent-network.json", "droid.json", "mcp.json",
})
_PROTECTED_WORKSPACE_SEGMENTS = (".git/hooks", ".git/config", ".jaeger")
_SENSITIVE_SHELL_RE = re.compile(
    r"(?:~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/\.(?:ssh|aws|gnupg|kube|jaeger)\b"
    r"|(?:/etc/(?:passwd|shadow|sudoers))"
    r"|(?:\.git/(?:hooks|config)\b)",
    re.IGNORECASE,
)


class ToolInspector(Protocol):
    @property
    def name(self) -> str: ...
    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None: ...


class ControlPlaneInspector:
    """Enforces emergency GlobalStop, embodiment gate, and structural validity."""

    name = "control_plane"

    def __init__(self, *, global_stop_fn: Callable[[], bool] | None = None) -> None:
        self._global_stop_fn = global_stop_fn

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        raw_name = str(proposal.tool_name or "").strip().lower()
        if raw_name.startswith("mc_") or "minecraft" in raw_name:
            return PolicyVerdict(
                DecisionKind.DENY,
                "Embodiment is disabled until the control-plane release gate passes.",
                "embodiment_gate",
                granted_by="control_plane",
                proposal_id=proposal.proposal_id,
            )
        if self._global_stop_fn is not None and self._global_stop_fn():
            return PolicyVerdict(
                DecisionKind.DENY,
                "Global emergency stop is engaged.",
                "global_stop",
                granted_by="control_plane",
                proposal_id=proposal.proposal_id,
            )
        if not canonical_tool_id(proposal.tool_name):
            return PolicyVerdict(
                DecisionKind.DENY,
                "Missing or invalid tool name.",
                "structure",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
            )
        if proposal.action_type not in KNOWN_ACTION_TYPES:
            return PolicyVerdict(
                DecisionKind.DENY,
                f"Unknown action_type {proposal.action_type!r}.",
                "structure",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
            )
        if proposal.tier not in KNOWN_TIERS:
            return PolicyVerdict(
                DecisionKind.DENY,
                f"Unknown tier {proposal.tier!r}.",
                "structure",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
            )
        return None


class ActorTrustInspector:
    """Enforces JaegerAI actor boundaries (owner-only identity, untrusted blocks)."""

    name = "actor_trust"

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        tool = canonical_tool_id(proposal.tool_name)
        actor = proposal.actor

        if is_untrusted_actor(actor):
            if tool in PRIVILEGED_TOOL_IDS or tool in ("write_file", "delete_file"):
                return PolicyVerdict(
                    DecisionKind.DENY,
                    f"Untrusted actor {actor!r} cannot run privileged tool {tool!r}.",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )
            if tool in MEMORY_WRITE_TOOL_IDS:
                return PolicyVerdict(
                    DecisionKind.DENY,
                    f"Outside caller {actor!r} cannot mutate durable memory ({tool!r}).",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )

        if tool in IDENTITY_TOOL_IDS or tool in OWNER_MANAGEMENT_TOOL_IDS:
            if not is_owner_actor(actor):
                return PolicyVerdict(
                    DecisionKind.DENY,
                    f"Tool {tool!r} requires an authenticated owner actor (got {actor!r}).",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )
        return None


class BoundaryAndSecretsInspector:
    """Protects secret stores (~/.ssh, ~/.aws, ~/.jaeger), .git/hooks, and workspace bounds."""

    name = "boundary_and_secrets"

    def __init__(
        self,
        *,
        extra_denied_paths: Sequence[Path] = (),
        allowed_roots: Sequence[Path] = (),
        read_allowed_roots: Sequence[Path] = (),
    ) -> None:
        self._extra_denied = tuple(p.expanduser().resolve(strict=False) for p in extra_denied_paths)
        home = Path.home().resolve(strict=False)
        fs_root = Path(os.path.sep).resolve(strict=False)
        clean_allowed: list[Path] = []
        for p in allowed_roots:
            resolved = p.expanduser().resolve(strict=False)
            if resolved not in {home, fs_root}:
                clean_allowed.append(resolved)
        self._allowed_roots = tuple(clean_allowed)
        clean_read_allowed: list[Path] = []
        for p in read_allowed_roots:
            resolved = p.expanduser().resolve(strict=False)
            if resolved not in {home, fs_root}:
                clean_read_allowed.append(resolved)
        self._read_allowed_roots = tuple(clean_read_allowed)

    def _is_explicitly_readable_artifact(
        self,
        resolved: Path,
        *,
        home: Path,
        tool: str,
        tier: str,
    ) -> bool:
        if not self._read_allowed_roots:
            return False
        if tier != "read_only" and tool not in _READ_TOOL_IDS:
            return False
        for hard_dir in _ALWAYS_DENIED_HOME_DIRS:
            hard_root = (home / hard_dir).resolve(strict=False)
            if resolved == hard_root or hard_root in resolved.parents:
                return False
        if resolved.name in _JAEGER_DENIED_FILENAMES or resolved.suffix.lower() in _JAEGER_DENIED_SUFFIXES:
            return False
        if any(part in _JAEGER_DENIED_SEGMENTS for part in resolved.parts):
            return False
        return any(
            resolved == root or root in resolved.parents
            for root in self._read_allowed_roots
        )

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        ws = proposal.workspace.expanduser().resolve(strict=False)
        home = Path.home().resolve(strict=False)
        tool = canonical_tool_id(proposal.tool_name)

        candidates: list[str] = []
        if proposal.target_path:
            candidates.append(proposal.target_path)
        for key in ("path", "file_path", "TargetFile", "target", "dest", "destination"):
            val = proposal.arguments.get(key)
            if val:
                candidates.append(str(val))

        protected_roots = [
            (home / d).resolve(strict=False) for d in _SENSITIVE_HOME_DIRS
        ] + list(self._extra_denied)

        for raw in candidates:
            p = Path(os.path.expanduser(raw))
            if not p.is_absolute():
                p = ws / p
            resolved = p.resolve(strict=False)

            for root in protected_roots:
                if resolved == root or root in resolved.parents:
                    if self._is_explicitly_readable_artifact(
                        resolved, home=home, tool=tool, tier=proposal.tier,
                    ):
                        continue
                    return PolicyVerdict(
                        DecisionKind.DENY,
                        f"Access to protected secret/authority store {root} is denied.",
                        self.name,
                        proposal_id=proposal.proposal_id,
                    )

            if tool in ("write_file", "delete_file"):
                try:
                    rel = str(resolved.relative_to(ws))
                except ValueError:
                    rel = ""
                for seg in _PROTECTED_WORKSPACE_SEGMENTS:
                    if rel == seg or rel.startswith(seg + "/"):
                        return PolicyVerdict(
                            DecisionKind.REQUIRE_APPROVAL,
                            f"Modifying governance path {seg!r} requires fresh owner approval.",
                            self.name,
                            proposal_id=proposal.proposal_id,
                        )
                in_ws = resolved == ws or ws in resolved.parents
                in_tmp = str(resolved).startswith(("/tmp/", "/private/tmp/"))
                in_allowed = any(
                    resolved == root or root in resolved.parents
                    for root in self._allowed_roots
                )
                if not in_ws and not in_tmp and not in_allowed:
                    return PolicyVerdict(
                        DecisionKind.REQUIRE_APPROVAL,
                        f"Write target {resolved} escapes workspace {ws}.",
                        self.name,
                        proposal_id=proposal.proposal_id,
                    )

        if tool in SHELL_TOOL_IDS:
            cmd = str(proposal.arguments.get("command") or proposal.arguments.get("cmd") or "")
            if _SENSITIVE_SHELL_RE.search(cmd):
                return PolicyVerdict(
                    DecisionKind.DENY,
                    "Shell command references protected secret store or governance path.",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )
        return None


class DestructiveAndEvasionInspector:
    """Non-overridable destructive & shell-evasion gate (runs BEFORE standing grants)."""

    name = "destructive_action"

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        tool = canonical_tool_id(proposal.tool_name)
        if tool in SHELL_TOOL_IDS:
            cmd = str(proposal.arguments.get("command") or proposal.arguments.get("cmd") or "")
            ev = evasion_reason(cmd)
            if ev:
                return PolicyVerdict(
                    DecisionKind.DENY,
                    ev,
                    "shell_evasion",
                    proposal_id=proposal.proposal_id,
                )

        reason = destructive_reason(proposal.tool_name, proposal.arguments)
        if reason:
            return PolicyVerdict(
                DecisionKind.REQUIRE_APPROVAL,
                f"Destructive or irreversible action requires fresh owner approval: {reason}",
                self.name,
                proposal_id=proposal.proposal_id,
            )
        return None


_EGRESS_SHELL_RE = re.compile(
    r"(?:^|[;&|\n]\s*)(?:sudo\s+)?"
    r"(?:curl\b.*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--data|-d\b|-F\b|-T\b)"
    r"|scp\b|sftp\b|rsync\b.*:|git\s+push\b|npm\s+publish\b|twine\s+upload\b"
    r"|gh\s+(?:pr\s+create|issue\s+create|release\s+create)\b"
    r"|aws\s+s3\s+(?:cp|sync|mv)\b|gsutil\s+(?:cp|rsync|mv)\b|docker\s+push\b)",
    re.IGNORECASE,
)


class EgressInspector:
    """Monotonic outbound-egress inspector (Goose egress_inspector pattern).

    Detects outbound network mutations, file uploads, and package/git pushes so
    callers can enforce explicit approval even inside relaxed workspace modes.
    Never loosens an earlier DENY/REQUIRE_APPROVAL verdict.
    """

    name = "egress"

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        tool = canonical_tool_id(proposal.tool_name)
        if tool in SHELL_TOOL_IDS:
            cmd = str(proposal.arguments.get("command") or proposal.arguments.get("cmd") or "")
            if _EGRESS_SHELL_RE.search(cmd):
                return PolicyVerdict(
                    DecisionKind.REQUIRE_APPROVAL,
                    "Outbound network egress or publish command requires explicit approval.",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )
        return None


@dataclass
class PermissionRules:
    """5-tier precedence (AutoGPT MIT Forge) + source-keyed grants (ag2)."""

    agent_deny: tuple[str, ...] = ()
    workspace_deny: tuple[str, ...] = ()
    agent_allow: tuple[str, ...] = ()
    workspace_allow: tuple[str, ...] = ()
    source_grants: set[tuple[str, str]] = field(default_factory=set)


class PrecedenceAndAutonomyInspector:
    """Evaluates 5-tier allow/deny rules and sandbox-backed autonomy modes."""

    name = "precedence_and_autonomy"

    def __init__(self, rules: PermissionRules | None = None) -> None:
        self.rules = rules or PermissionRules()

    @staticmethod
    def _matches(patterns: Sequence[str], sig: str) -> bool:
        return any(fnmatch.fnmatch(sig, pat) for pat in patterns)

    def inspect(self, proposal: ActionProposal) -> PolicyVerdict | None:
        tool = canonical_tool_id(proposal.tool_name)
        arg_preview = str(
            proposal.arguments.get("command")
            or proposal.arguments.get("path")
            or ""
        )
        sig = f"{tool}({arg_preview})"

        if self._matches(self.rules.agent_deny, sig):
            return PolicyVerdict(DecisionKind.DENY, f"Blocked by agent deny rule: {sig}", self.name, proposal_id=proposal.proposal_id)
        if self._matches(self.rules.workspace_deny, sig):
            return PolicyVerdict(DecisionKind.DENY, f"Blocked by workspace deny rule: {sig}", self.name, proposal_id=proposal.proposal_id)

        if self._matches(self.rules.agent_allow, sig):
            return PolicyVerdict(DecisionKind.ALLOW, "Allowed by agent allow rule.", self.name, proposal_id=proposal.proposal_id)
        if self._matches(self.rules.workspace_allow, sig):
            return PolicyVerdict(DecisionKind.ALLOW, "Allowed by workspace allow rule.", self.name, proposal_id=proposal.proposal_id)
        if (tool, proposal.tool_source) in self.rules.source_grants:
            return PolicyVerdict(DecisionKind.ALLOW, "Allowed by source-keyed standing grant.", self.name, proposal_id=proposal.proposal_id)

        if proposal.autonomy_mode == AutonomyMode.READ_ONLY:
            if proposal.tier == "read_only" or tool == "read_file":
                return PolicyVerdict(DecisionKind.ALLOW, "Read-only action allowed.", self.name, proposal_id=proposal.proposal_id)
            return PolicyVerdict(DecisionKind.DENY, "Mutating action blocked in READ_ONLY mode.", self.name, proposal_id=proposal.proposal_id)

        if proposal.autonomy_mode == AutonomyMode.WORKSPACE_SANDBOX:
            if proposal.tier in ("read_only", "write_local") and proposal.sandboxed:
                return PolicyVerdict(
                    DecisionKind.ALLOW,
                    "Auto-approved inside OS workspace sandbox.",
                    self.name,
                    proposal_id=proposal.proposal_id,
                )
            return PolicyVerdict(
                DecisionKind.REQUIRE_APPROVAL,
                f"Action outside sandboxed local scope (tier={proposal.tier!r}, sandboxed={proposal.sandboxed}) requires approval.",
                self.name,
                proposal_id=proposal.proposal_id,
            )

        if proposal.autonomy_mode == AutonomyMode.ASK_ON_WRITE:
            if proposal.tier == "read_only":
                return PolicyVerdict(DecisionKind.ALLOW, "Read-only action allowed.", self.name, proposal_id=proposal.proposal_id)
            return PolicyVerdict(DecisionKind.REQUIRE_APPROVAL, "Write/exec requires approval in ASK_ON_WRITE mode.", self.name, proposal_id=proposal.proposal_id)

        return PolicyVerdict(DecisionKind.ALLOW, "Authorized.", self.name, proposal_id=proposal.proposal_id)
