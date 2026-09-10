"""Small, read-only Mac inventory; no model, network scan, or secret lookup."""
from datetime import UTC, datetime
import os
import platform
from pathlib import Path


def snapshot(roots: list[str]) -> dict:
    return {
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "evidence": "live host process observation",
        "host": {"hostname": platform.node(), "os": platform.system(),
                 "os_version": platform.mac_ver()[0] or platform.release(),
                 "architecture": platform.machine(), "logical_cpus": os.cpu_count()},
        "container_host_address": "192.168.64.1",
        "canonical_repo": str(Path(__file__).resolve().parents[3]),
        "container_repo": "/mnt/host/GitHub/JaegerAI",
        "approved_roots": roots,
        "access_note": "Grants are configuration, not proof of a successful file write. Probe the target before claiming access.",
        "execution_note": "Agent terminal tools run in Linux containers. macOS operations require authorized host MCP tools.",
    }
