"""ToolRegistry with cached reachability probes, progressive discovery, and Policy/Sandbox gating.

Harvested from:
- hermes-agent (`tools/registry.py`, `tools/tool_search.py`): cached `check_fn`
  availability probes + progressive disclosure for large MCP catalogs.
- MetaGPT (`tool_recommend.py`): token-overlap/BM25-style tool ranking by query.
- openai-codex (`tools/parallel.rs`): explicit `read_only` flag enabling safe
  read/write lock-partitioned parallel tool execution in `jaeger-loop`.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from jaeger_contracts import (
    ActionProposal,
    AutonomyMode,
    DecisionKind,
    PolicyPort,
    SandboxPort,
    SandboxProfile,
    ToolResult,
)

ToolHandler = Callable[[Mapping[str, Any]], ToolResult]


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: Mapping[str, Any]
    handler: ToolHandler
    tier: str = "write_local"
    read_only: bool = False
    source: str = "builtin"
    check_fn: Callable[[], bool] | None = None
    tags: tuple[str, ...] = ()
    _available_cache: bool | None = field(default=None, init=False, repr=False)

    def is_available(self, *, refresh: bool = False) -> bool:
        if self.check_fn is None:
            return True
        if refresh or self._available_cache is None:
            try:
                self._available_cache = bool(self.check_fn())
            except Exception:
                self._available_cache = False
        return self._available_cache


class ToolRegistry:
    """Composable ToolPort implementation with progressive search and authority gating."""

    def __init__(
        self,
        *,
        workspace: Path,
        policy: PolicyPort | None = None,
        sandbox: SandboxPort | None = None,
        autonomy_mode: AutonomyMode = AutonomyMode.WORKSPACE_SANDBOX,
        name: str = "jaeger_tools",
    ) -> None:
        self._name = name
        self._workspace = workspace.expanduser().resolve()
        self._policy = policy
        self._sandbox = sandbox
        self._autonomy_mode = autonomy_mode
        self._tools: dict[str, ToolSpec] = {}

    @property
    def name(self) -> str:
        return self._name

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get_spec(self, tool_name: str) -> ToolSpec | None:
        return self._tools.get(tool_name)

    def is_read_only(self, tool_name: str) -> bool:
        spec = self._tools.get(tool_name)
        return bool(spec.read_only) if spec is not None else False

    def list_tools(self, *, query: str | None = None, limit: int = 64) -> Sequence[Mapping[str, Any]]:
        available = [t for t in self._tools.values() if t.is_available()]
        if query:
            q_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))

            def _score(t: ToolSpec) -> int:
                hay = f"{t.name} {t.description} {' '.join(t.tags)}".lower()
                return sum(2 if tok in t.name.lower() else 1 for tok in q_tokens if tok in hay)

            scored = [(s, t) for t in available if (s := _score(t)) > 0]
            scored.sort(key=lambda pair: (-pair[0], pair[1].name))
            available = [t for _, t in scored[:limit]]

        return [
            {
                "name": t.name,
                "description": t.description,
                "schema": dict(t.schema),
                "tier": t.tier,
                "read_only": t.read_only,
                "source": t.source,
            }
            for t in available[:limit]
        ]

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        actor: str = "owner:local",
        session_id: str = "default",
    ) -> ToolResult:
        spec = self._tools.get(tool_name)
        if spec is None or not spec.is_available():
            return ToolResult(tool_name=tool_name, ok=False, error=f"Unknown or unavailable tool: {tool_name!r}")

        args = dict(arguments)
        if self._policy is not None:
            proposal = ActionProposal(
                tool_name=spec.name,
                arguments=args,
                workspace=self._workspace,
                actor=actor,
                session_id=session_id,
                tier=spec.tier,
                autonomy_mode=self._autonomy_mode,
                tool_source=spec.source,
                sandboxed=self._sandbox is not None,
            )
            verdict = self._policy.evaluate(proposal)
            if not verdict.is_authorized:
                return ToolResult(
                    tool_name=tool_name,
                    ok=False,
                    error=f"[{verdict.decision.value}] {verdict.reason}",
                    metadata={"decision": verdict.decision.value, "policy_name": verdict.policy_name},
                )
            if verdict.decision == DecisionKind.MODIFY and verdict.authorized_arguments is not None:
                args = dict(verdict.authorized_arguments)

        try:
            return spec.handler(args)
        except Exception as exc:
            return ToolResult(tool_name=tool_name, ok=False, error=f"{type(exc).__name__}: {exc}")

    def register_shell_tool(self, *, allow_network: bool = False, timeout_s: float = 30.0) -> None:
        """Register a Policy+Sandbox-gated shell tool."""
        def _run_shell(args: Mapping[str, Any]) -> ToolResult:
            cmd = str(args.get("command") or "")
            argv: list[str] = ["/bin/sh", "-c", cmd]
            if self._sandbox is not None:
                profile = SandboxProfile(workspace=self._workspace, allow_network=allow_network)
                spec = self._sandbox.prepare(argv, profile)
                argv = list(spec.argv)
            proc = subprocess.run(
                argv,
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
            return ToolResult(
                tool_name="shell",
                ok=proc.returncode == 0,
                output=out.strip(),
                error=None if proc.returncode == 0 else f"exit code {proc.returncode}",
                metadata={"returncode": proc.returncode},
            )

        self.register(ToolSpec(
            name="shell",
            description="Execute a shell command inside the workspace sandbox.",
            schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            handler=_run_shell,
            tier="write_local",
            read_only=False,
            tags=("bash", "terminal", "exec", "pytest", "git"),
        ))
