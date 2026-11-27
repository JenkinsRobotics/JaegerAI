"""jaeger-authority: standalone fail-closed PolicyEngine & swappable SandboxPort backends."""

from .canonical import (
    IDENTITY_TOOL_IDS,
    MEMORY_WRITE_TOOL_IDS,
    OWNER_MANAGEMENT_TOOL_IDS,
    PRIVILEGED_TOOL_IDS,
    SHELL_TOOL_IDS,
    canonical_tool_id,
    is_owner_actor,
    is_untrusted_actor,
)
from . import guardrails, profiles
from .profiles import (
    list_seatbelt_profiles,
    load_codex_sbpl,
    load_gemini_policy_rules,
    load_gemini_sb,
)
from .destructive import (
    BANNED_STANDING_GRANT_PREFIXES,
    destructive_reason,
    evasion_reason,
    is_banned_standing_grant,
    shell_command_reason,
)
from .engine import PolicyEngine
from .guardrails import GuardrailResult
from .privacy import (
    DataSensitivity,
    PrivacyDecision,
    classify_sensitivity,
    evaluate_cloud_egress,
    filter_items_for_egress,
)
from .redact import SENSITIVE_QUERY_PARAMS, redact_object, redact_text
from .inspectors import (
    ActorTrustInspector,
    BoundaryAndSecretsInspector,
    ControlPlaneInspector,
    DestructiveAndEvasionInspector,
    EgressInspector,
    PermissionRules,
    PrecedenceAndAutonomyInspector,
    ToolInspector,
)
from .sandbox import (
    ContainerSandbox,
    LinuxBwrapSandbox,
    MacOsSeatbeltSandbox,
    UnconfinedSandbox,
    default_os_sandbox,
)

__all__ = [
    "ActorTrustInspector",
    "BANNED_STANDING_GRANT_PREFIXES",
    "BoundaryAndSecretsInspector",
    "ContainerSandbox",
    "ControlPlaneInspector",
    "DataSensitivity",
    "DestructiveAndEvasionInspector",
    "EgressInspector",
    "GuardrailResult",
    "IDENTITY_TOOL_IDS",
    "LinuxBwrapSandbox",
    "MEMORY_WRITE_TOOL_IDS",
    "MacOsSeatbeltSandbox",
    "OWNER_MANAGEMENT_TOOL_IDS",
    "PRIVILEGED_TOOL_IDS",
    "PermissionRules",
    "PolicyEngine",
    "PrecedenceAndAutonomyInspector",
    "PrivacyDecision",
    "SENSITIVE_QUERY_PARAMS",
    "SHELL_TOOL_IDS",
    "ToolInspector",
    "UnconfinedSandbox",
    "canonical_tool_id",
    "classify_sensitivity",
    "default_os_sandbox",
    "destructive_reason",
    "evaluate_cloud_egress",
    "evasion_reason",
    "filter_items_for_egress",
    "guardrails",
    "is_banned_standing_grant",
    "is_owner_actor",
    "is_untrusted_actor",
    "redact_object",
    "redact_text",
    "shell_command_reason",
]
