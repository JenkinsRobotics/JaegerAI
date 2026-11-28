"""jaeger-tools: ToolDef, ToolRegistry, ToolRouter, RwLock dispatcher, progressive discovery, EditEngines, RepoMap."""

from . import aider_search_replace, arg_coercion, browser_guard, builtins, evidence, pty_manager, remote_exec, router, search, tool_registry, tool_schema, web_search
from .browser_guard import (
    BrowserDomainPolicy,
    BrowserJudgement,
    BrowserRunJudge,
    DomainCheckResult,
    ScopedSecretVault,
    SiteGotchasStore,
)
from .evidence import RetainedEvidenceStore, RetainedSummary
from .web_search import web_search as run_web_search
from .aider_search_replace import RelativeIndenter, search_and_replace
from .arg_coercion import COMMON_PARAM_ALIASES, coerce_args
from .builtins import register_builtin_tools
from .pty_manager import PtySessionError, PtySessionManager
from .remote_exec import (
    ExecutionBackend,
    LocalSubprocessBackend,
    RemoteExecError,
    RemoteHostConfig,
    RemoteHostRegistry,
    SSHBackend,
    TailscalePeer,
    connect_remote_host,
    discover_remote_routes,
    discover_ssh_config_hosts,
    discover_tailscale_peers,
    find_tailscale_bin,
    probe_ssh_alias,
    probe_tailscale_ssh,
    register_tailscale_peer,
    ssh_setup_hint,
)
from .diagnostics import Diagnostic, DiagnosticReport, diagnose_file
from .editors import (
    ApplyPatchEditor,
    EditEngine,
    EditOutcome,
    SearchReplaceEditor,
    lint_guarded_edit,
)
from .registry import ToolRegistry, ToolSpec
from .repomap import build_repo_map
from .router import (
    ReadWriteToolDispatcher,
    RoutedTool,
    ToolDiscoverySession,
    ToolRouter,
    ToolVisibility,
)
from .search import CatalogEntry, search_catalog
from .tool_registry import (
    ToolConflict,
    clear_registry,
    get_tool,
    get_tools,
    has_tool,
    register_tool,
    register_tool_from_function,
    register_tool_instance,
    replace_tool_inventory,
    restore_registry,
    snapshot_registry,
    unregister_tool,
)
from .tool_schema import ToolDef, dev_mode_enabled, tool_result_failed

__all__ = [
    "ApplyPatchEditor",
    "BrowserDomainPolicy",
    "BrowserJudgement",
    "BrowserRunJudge",
    "COMMON_PARAM_ALIASES",
    "CatalogEntry",
    "Diagnostic",
    "DiagnosticReport",
    "DomainCheckResult",
    "EditEngine",
    "EditOutcome",
    "ExecutionBackend",
    "LocalSubprocessBackend",
    "PtySessionError",
    "PtySessionManager",
    "ReadWriteToolDispatcher",
    "RemoteExecError",
    "RemoteHostConfig",
    "RemoteHostRegistry",
    "RetainedEvidenceStore",
    "RetainedSummary",
    "RoutedTool",
    "SSHBackend",
    "ScopedSecretVault",
    "SearchReplaceEditor",
    "SiteGotchasStore",
    "TailscalePeer",
    "ToolConflict",
    "ToolDef",
    "ToolDiscoverySession",
    "ToolRegistry",
    "ToolRouter",
    "ToolSpec",
    "ToolVisibility",
    "arg_coercion",
    "build_repo_map",
    "builtins",
    "clear_registry",
    "coerce_args",
    "connect_remote_host",
    "dev_mode_enabled",
    "discover_remote_routes",
    "discover_ssh_config_hosts",
    "discover_tailscale_peers",
    "find_tailscale_bin",
    "probe_ssh_alias",
    "probe_tailscale_ssh",
    "register_tailscale_peer",
    "ssh_setup_hint",
    "diagnose_file",
    "get_tool",
    "get_tools",
    "has_tool",
    "lint_guarded_edit",
    "register_builtin_tools",
    "register_tool",
    "register_tool_from_function",
    "register_tool_instance",
    "replace_tool_inventory",
    "restore_registry",
    "router",
    "search",
    "search_catalog",
    "snapshot_registry",
    "tool_registry",
    "tool_result_failed",
    "tool_schema",
    "unregister_tool",
]
