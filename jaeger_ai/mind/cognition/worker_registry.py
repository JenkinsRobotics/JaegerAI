"""
ARES SI — Worker Registry.

Data-driven registry of all available workers.
No provider-specific code — workers register themselves.
"""

from __future__ import annotations

from .types import (
    WorkerRecord,
    WorkerCapability,
    PrivacyClass,
    CostEstimate,
    LatencyProfile,
)


# ── Built-in worker definitions ────────────────────────────────────────
# These are the known workers. The registry can be extended at runtime
# via discover_adapters() which detects what's installed on this machine.

_BUILTIN_WORKERS: dict[str, WorkerRecord] = {
    "jaeger_local": WorkerRecord(
        worker_id="jaeger_local",
        provider="jaeger",
        display_name="Jaeger AI (local)",
        capabilities=[
            WorkerCapability("code_generation", "Write, edit, and debug code", 0.95),
            WorkerCapability("terminal", "Execute shell commands", 1.0),
            WorkerCapability("file_operations", "Read, write, and manage files", 1.0),
            WorkerCapability("research", "Web search and information retrieval", 0.85),
            WorkerCapability("conversation", "General conversation and reasoning", 0.9),
        ],
        privacy_class=PrivacyClass.LOCAL_ONLY,
        data_location="local",
        context_limit=None,
        supports_streaming=True,
        supports_files=True,
        supports_images=True,
    ),
    "claude_local": WorkerRecord(
        worker_id="claude_local",
        provider="anthropic",
        display_name="Claude Code (local)",
        capabilities=[
            WorkerCapability("code_generation", "Write, edit, and debug code", 0.95),
            WorkerCapability("research", "Reasoning and analysis", 0.9),
            WorkerCapability("conversation", "General conversation and reasoning", 0.9),
        ],
        privacy_class=PrivacyClass.APPROVED_PROVIDER,
        data_location="cloud",
        context_limit=200000,
        supports_streaming=True,
        supports_files=True,
        supports_images=True,
    ),
    "gemini_antigravity": WorkerRecord(
        worker_id="gemini_antigravity",
        provider="google",
        display_name="Gemini (Antigravity IDE)",
        capabilities=[
            WorkerCapability("research", "Long-context research and analysis", 0.85),
            WorkerCapability("code_generation", "Code generation and debugging", 0.85),
            WorkerCapability("conversation", "General conversation", 0.85),
        ],
        privacy_class=PrivacyClass.APPROVED_PROVIDER,
        data_location="cloud",
        context_limit=1000000,
        supports_streaming=True,
        supports_files=True,
        supports_images=True,
    ),
    "grok_local": WorkerRecord(
        worker_id="grok_local",
        provider="xai",
        display_name="Grok",
        capabilities=[
            WorkerCapability("research", "Real-time information and analysis", 0.8),
            WorkerCapability("conversation", "General conversation", 0.8),
        ],
        privacy_class=PrivacyClass.EXTERNAL_PROVIDER,
        data_location="cloud",
        context_limit=128000,
        supports_streaming=True,
        supports_files=False,
        supports_images=True,
    ),
    "ollama_local": WorkerRecord(
        worker_id="ollama_local",
        provider="local",
        display_name="Ollama (local model)",
        capabilities=[
            WorkerCapability("conversation", "Local private conversation", 0.7),
            WorkerCapability("code_generation", "Local code generation", 0.6),
        ],
        privacy_class=PrivacyClass.LOCAL_ONLY,
        data_location="local",
        context_limit=None,
        supports_streaming=True,
        supports_files=False,
        supports_images=False,
    ),
    "codex_local": WorkerRecord(
        worker_id="codex_local",
        provider="openai",
        display_name="Codex (local)",
        capabilities=[
            WorkerCapability("code_generation", "Autonomous code tasks", 0.9),
        ],
        privacy_class=PrivacyClass.APPROVED_PROVIDER,
        data_location="cloud",
        context_limit=128000,
        supports_streaming=False,
        supports_files=True,
        supports_images=False,
    ),
}


class WorkerRegistry:
    """Data-driven registry of all available workers.

    Workers register themselves. The SI queries the registry to find
    workers with matching capabilities, privacy eligibility, and availability.
    """

    def __init__(self) -> None:
        self._workers: dict[str, WorkerRecord] = dict(_BUILTIN_WORKERS)
        self._availability: dict[str, bool] = {}

    def register(self, worker: WorkerRecord) -> None:
        """Register a new worker or update an existing one."""
        self._workers[worker.worker_id] = worker

    def unregister(self, worker_id: str) -> None:
        """Remove a worker from the registry."""
        self._workers.pop(worker_id, None)
        self._availability.pop(worker_id, None)

    def get(self, worker_id: str) -> WorkerRecord | None:
        """Get a worker record by ID."""
        return self._workers.get(worker_id)

    def list_all(self) -> list[WorkerRecord]:
        """List all registered workers."""
        return list(self._workers.values())

    def find_by_capability(self, capability: str) -> list[WorkerRecord]:
        """Find all workers that have a given capability."""
        results = []
        for w in self._workers.values():
            if any(c.capability_id == capability for c in w.capabilities):
                results.append(w)
        return results

    def find_eligible(
        self,
        capability: str,
        data_sensitivity: str = "personal",
        require_local: bool = False,
    ) -> list[WorkerRecord]:
        """Find workers that can handle a task with the given sensitivity.

        Rules:
        - SECRET data: no worker (handled by SI directly, never sent out)
        - SENSITIVE data: only LOCAL_ONLY workers with user approval
        - PRIVATE data: only LOCAL_ONLY workers
        - PERSONAL data: LOCAL_ONLY or APPROVED_PROVIDER workers
        - PUBLIC data: any worker
        """
        if data_sensitivity == "secret":
            return []  # Secret data never leaves the device

        candidates = self.find_by_capability(capability)

        if require_local:
            candidates = [w for w in candidates if w.data_location == "local"]

        # Filter by privacy eligibility
        eligible = []
        for w in candidates:
            if data_sensitivity == "sensitive":
                if w.privacy_class == PrivacyClass.LOCAL_ONLY:
                    eligible.append(w)
            elif data_sensitivity == "private":
                if w.privacy_class in (PrivacyClass.LOCAL_ONLY,):
                    eligible.append(w)
            elif data_sensitivity == "personal":
                if w.privacy_class in (
                    PrivacyClass.LOCAL_ONLY,
                    PrivacyClass.APPROVED_PROVIDER,
                ):
                    eligible.append(w)
            else:  # public
                eligible.append(w)

        return eligible

    def set_availability(self, worker_id: str, available: bool) -> None:
        """Update a worker's availability status."""
        self._availability[worker_id] = available

    def is_available(self, worker_id: str) -> bool:
        """Check if a worker is currently available."""
        return self._availability.get(worker_id, False)


# Global singleton
_registry = WorkerRegistry()


def get_registry() -> WorkerRegistry:
    """Get the global worker registry."""
    return _registry
