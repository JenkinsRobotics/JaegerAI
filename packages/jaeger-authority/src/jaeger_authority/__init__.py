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
from .destructive import destructive_reason, evasion_reason, shell_command_reason
from .engine import PolicyEngine
from .inspectors import (
    ActorTrustInspector,
    BoundaryAndSecretsInspector,
    ControlPlaneInspector,
    DestructiveAndEvasionInspector,
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
    "BoundaryAndSecretsInspector",
    "ContainerSandbox",
    "ControlPlaneInspector",
    "DestructiveAndEvasionInspector",
    "IDENTITY_TOOL_IDS",
    "LinuxBwrapSandbox",
    "MEMORY_WRITE_TOOL_IDS",
    "MacOsSeatbeltSandbox",
    "OWNER_MANAGEMENT_TOOL_IDS",
    "PRIVILEGED_TOOL_IDS",
    "PermissionRules",
    "PolicyEngine",
    "PrecedenceAndAutonomyInspector",
    "SHELL_TOOL_IDS",
    "ToolInspector",
    "UnconfinedSandbox",
    "canonical_tool_id",
    "default_os_sandbox",
    "destructive_reason",
    "evasion_reason",
    "is_owner_actor",
    "is_untrusted_actor",
    "shell_command_reason",
]
