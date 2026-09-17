"""Install and inspect the shared Hermes WebUI profile adapter services.

Run with ``python -m jaeger_ai.core.frameworks.setup install``.
The adapters remain package-owned; only generated launchd definitions and
machine-specific Hermes profile state are written outside the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from jaeger_ai.contract.frameworks import DEFAULT_AGENT_MODEL, SOLO_RUNTIMES
from jaeger_ai.contract.ports import (
    A2A_CONTAINER_GATEWAY_URL,
    A2A_GATEWAY_URL,
    A2A_URL,
    CONTAINER_HOST,
    MCP_CONTAINER_GATEWAY_URL,
    MCP_GATEWAY_URL,
    MCP_HTTP_URL,
    OLLAMA_OPENAI_URL,
)
from jaeger_ai.core.instance.instance import operator_state_root

SERVICES = {
    "jaeger": ("jaeger_ai.core.frameworks.jaeger", 8642),
    "roundtable": ("jaeger_ai.features.roundtable.roundtable", 8643),
    "openclaw": ("jaeger_ai.core.frameworks.openclaw", 8644),
}
SUPERVISOR_LABEL = "com.jenkinsrobotics.agent-fabric-supervisor"
SUPERVISOR_MODULE = "jaeger_ai.core.runtime.fabric_supervisor"
AVAILABLE_AGENT_MODELS = (DEFAULT_AGENT_MODEL, "glm-5.3:cloud")
OPENCLAW_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
HONCHO_LAN_URL = "http://10.15.0.239:8088"
HONCHO_WORKSPACE = "jenkins-robotics"

REPO_ROOT = Path(__file__).resolve().parents[3]
JAEGER_RUNTIME_ROOT = operator_state_root() / "shared"
JAEGER_INSTANCE_ROOT = operator_state_root() / "instances" / "jaeger"

#: Frameworks that answer on their own and therefore need their own
#: workspace. Roundtable is excluded by construction — it delegates.
WORKSPACE_IDENTITIES = SOLO_RUNTIMES

WEBUI_WORKSPACES = (
    ("/workspace", "General"),
    ("/mnt/host/GitHub/JaegerAI", "JaegerAI (live Mac repo)"),
    ("/mnt/host/GitHub", "GitHub"),
    ("/mnt/host/Desktop", "Desktop"),
    ("/mnt/host/Documents", "Documents"),
    ("/mnt/nas/Jenkins_Robotics", "Jenkins Robotics NAS"),
    ("/mnt/nas/Personal-Drive", "Personal Drive NAS"),
)


def _shared_workspace_roots(home: Path | None = None) -> list[Path]:
    """Return the explicit host roots shared with the three agent identities."""
    home = (home or Path.home()).expanduser().resolve()
    return [
        home / "workspace",
        home / "GitHub",
        home / "Desktop",
        home / "Documents",
        Path("/Volumes/Jenkins_Robotics"),
        Path("/Volumes/Personal-Drive"),
    ]


def _configure_workspace_roots(home: Path | None = None) -> Path:
    """Add shared roots to the identity-scoped host capability registry.

    Existing capabilities and identity-specific roots are preserved. Network
    roots remain registered while a share is offline and become usable again
    when macOS remounts it.
    """
    home = (home or Path.home()).expanduser().resolve()
    grants = home / ".jaeger" / "capabilities" / "grants.json"
    grants.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    document = (
        json.loads(grants.read_text(encoding="utf-8"))
        if grants.exists()
        else {"version": 1, "identities": {}}
    )
    if document.get("version") != 1 or not isinstance(document.get("identities"), dict):
        raise ValueError(f"Unsupported host capability registry: {grants}")
    shared = {str(path) for path in _shared_workspace_roots(home)}
    for identity in WORKSPACE_IDENTITIES:
        entry = document["identities"].setdefault(identity, {})
        existing = entry.get("roots", [])
        if not isinstance(existing, list):
            raise ValueError(f"Malformed roots for identity {identity}: {grants}")
        entry["roots"] = sorted({str(root) for root in existing} | shared)
        entry.setdefault("capabilities", [])
    if grants.exists():
        backup = grants.with_suffix(".json.previous")
        shutil.copy2(grants, backup)
        backup.chmod(0o600)
    temporary = grants.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, grants)
    return grants


def _configure_webui_workspaces(home: Path | None = None) -> list[Path]:
    """Publish the shared container paths in every profile's workspace tab."""
    home = (home or Path.home()).expanduser().resolve()
    written: list[Path] = []
    profile_homes = [home / ".hermes"] + [home / ".hermes" / "profiles" / profile for profile in SERVICES]
    for profile_home in profile_homes:
        # This deployment sets HERMES_WEBUI_STATE_DIR to the default home.
        # Only named profiles use a webui_state subdirectory.
        state_dir = profile_home if profile_home == home / ".hermes" else profile_home / "webui_state"
        path = state_dir / "workspaces.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            raise ValueError(f"Malformed WebUI workspace catalog: {path}")
        by_path = {
            str(item.get("path")): item
            for item in existing
            if isinstance(item, dict) and item.get("path")
        }
        for workspace_path, name in WEBUI_WORKSPACES:
            by_path.setdefault(workspace_path, {"path": workspace_path, "name": name})
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(list(by_path.values()), indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        written.append(path)
    return written


def _profile_config(profile: str) -> Path:
    return Path.home() / ".hermes" / "profiles" / profile / "config.yaml"


def _set_yaml_section_value(path: Path, section: str, key: str, value: str) -> None:
    """Set one top-level YAML mapping value without rewriting unrelated config."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    section_start = next((i for i, line in enumerate(lines) if line == f"{section}:"), None)
    if section_start is None:
        lines.extend(([""] if lines else []) + [f"{section}:", f"  {key}: {value}"])
    else:
        section_end = next(
            (i for i in range(section_start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "\t"))),
            len(lines),
        )
        key_index = next(
            (i for i in range(section_start + 1, section_end) if re.match(rf"^\s+{re.escape(key)}\s*:", lines[i])),
            None,
        )
        if key_index is None:
            lines.insert(section_start + 1, f"  {key}: {value}")
        else:
            indent = lines[key_index][:len(lines[key_index]) - len(lines[key_index].lstrip())]
            lines[key_index] = f"{indent}{key}: {value}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _replace_yaml_mapping_entry(
    text: str, section: str, names: set[str], block: list[str]
) -> str:
    """Replace selected second-level YAML entries without rewriting the file."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"{section}:"), None)
    if start is None:
        lines.extend(([""] if lines else []) + [f"{section}:", *block])
        return "\n".join(lines).rstrip() + "\n"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "\t"))),
        len(lines),
    )
    kept: list[str] = []
    i = start + 1
    while i < end:
        match = re.match(r"^  ([^:#]+):\s*$", lines[i])
        if match and match.group(1) in names:
            i += 1
            while i < end and not re.match(r"^  [^ :#][^:]*:\s*$", lines[i]):
                i += 1
            continue
        kept.append(lines[i])
        i += 1
    lines[start + 1:end] = [*kept, *block]
    return "\n".join(lines).rstrip() + "\n"


def _configure_codex_mcp(home: Path, url: str) -> Path | None:
    path = home / ".codex" / "config.toml"
    if not path.exists() and not path.parent.exists():
        return None
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    prefixes = ("[mcp_servers.ares-system]", "[mcp_servers.jaeger-local]")
    output: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("["):
            skipping = any(line.startswith(prefix[:-1]) for prefix in prefixes)
        if not skipping:
            output.append(line)
    output.extend([
        "",
        "[mcp_servers.jaeger-local]",
        f"url = {json.dumps(url)}",
        "startup_timeout_sec = 30",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text("\n".join(output).strip() + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def _configure_claude_mcp(home: Path, url: str) -> Path | None:
    path = home / ".claude.json"
    if not path.exists() and not (home / ".claude").exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    servers = document.setdefault("mcpServers", {})
    servers.pop("ares-system", None)
    servers["jaeger-local"] = {"type": "http", "url": url}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def _write_agent_network_manifest(home: Path) -> Path:
    path = home / ".jaeger" / "agent-network.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    proxy_token_file = home / ".jaeger" / "gateway" / "mcp.token"
    proxy_auth = {"scheme": "bearer", "token_file": str(proxy_token_file)}
    document = {
        "version": 1,
        "authority": "jaeger",
        "mcp": {
            "host": MCP_HTTP_URL,
            "container": MCP_CONTAINER_GATEWAY_URL,
            "transport": "streamable-http",
            "optional_proxy": MCP_GATEWAY_URL,
            "container_auth": proxy_auth,
        },
        "a2a": {
            "host": A2A_URL,
            "container": A2A_CONTAINER_GATEWAY_URL,
            "agent_card": "/.well-known/agent-card.json",
            "transport": "JSONRPC",
            "optional_proxy": A2A_GATEWAY_URL,
            "container_auth": proxy_auth,
        },
        "frameworks": {
            "codex": "jaeger-local",
            "claude-code": "jaeger-local",
            "hermes-agent": "jaeger-host",
            "openclaw": "jaeger-host",
        },
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def _configure_hermes_cli(home: Path) -> Path | None:
    """Expose the installed Hermes Agent CLI on Jaeger's supervisor PATH."""
    source_root = Path(
        os.environ.get("JAEGER_HERMES_AGENT_SRC", str(home / "GitHub" / "hermes-agent"))
    ).expanduser()
    source = next(
        (
            candidate
            for candidate in (
                source_root / ".venv" / "bin" / "hermes",
                source_root / "venv" / "bin" / "hermes",
            )
            if candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if source is None:
        return None
    destination = home / "bin" / "hermes"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() and destination.resolve(strict=False) == source.resolve():
        return destination
    if destination.exists() and not destination.is_symlink():
        return None
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(source)
    os.replace(temporary, destination)
    return destination


def _configure_agent_connectivity(home: Path | None = None) -> list[Path]:
    """Publish Jaeger's MCP/A2A endpoints to every supported local runtime."""
    home = (home or Path.home()).expanduser().resolve()
    written: list[Path] = []
    profile_homes = [home / ".hermes"] + [
        home / ".hermes" / "profiles" / profile for profile in SERVICES
    ]
    block = [
        "  jaeger-host:",
        f"    url: {MCP_HTTP_URL}",
        "    connect_timeout: 60.0",
        "    enabled: true",
    ]
    for profile_home in profile_homes:
        path = profile_home / "config.yaml"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        text = _replace_yaml_mapping_entry(
            text, "mcp_servers", {"ares-host", "mac-host", "jaeger-host"}, block
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)

    openclaw_path = home / ".jaeger" / "openclaw" / "openclaw.json"
    if openclaw_path.exists():
        document = json.loads(openclaw_path.read_text(encoding="utf-8"))
        document.setdefault("gateway", {}).pop("mcp", None)
        servers = document.setdefault("mcp", {}).setdefault("servers", {})
        servers["jaeger-host"] = {
            "url": MCP_CONTAINER_GATEWAY_URL,
            "transport": "streamable-http",
        }
        token_file = home / ".jaeger" / "gateway" / "mcp.token"
        if token_file.is_file():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                servers["jaeger-host"]["headers"] = {
                    "Authorization": f"Bearer {token}",
                }
        # OpenClaw runs in an Apple Container, so it crosses the loopback
        # boundary through Jaeger's Agentgateway proxy.
        servers.pop("ares-system", None)
        servers.pop("mac-host", None)
        temporary = openclaw_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, openclaw_path)
        written.append(openclaw_path)

    # The old ARES host-tools gateway was retired with the standalone ARES
    # install. All supported frameworks now discover Jaeger under one name.
    for configured in (
        _configure_codex_mcp(home, MCP_HTTP_URL),
        _configure_claude_mcp(home, MCP_HTTP_URL),
        _configure_hermes_cli(home),
    ):
        if configured is not None:
            written.append(configured)
    written.append(_write_agent_network_manifest(home))
    return written



def _configure_honcho(home: Path | None = None) -> list[Path]:
    """Configure persistent, profile-isolated peers on the rack LAN Honcho."""
    home = (home or Path.home()).expanduser().resolve()
    identities = {"hermes": "hermes", **{name: name for name in SERVICES}}
    written: list[Path] = []
    for profile, ai_peer in identities.items():
        profile_home = (
            home / ".hermes"
            if profile == "hermes"
            else home / ".hermes" / "profiles" / profile
        )
        host_key = "hermes" if profile == "hermes" else f"hermes.{profile}"
        document = {
            "baseUrl": HONCHO_LAN_URL,
            "hosts": {
                host_key: {
                    "peerName": "Matthew",
                    "aiPeer": ai_peer,
                    "workspace": HONCHO_WORKSPACE,
                    "enabled": True,
                    "recallMode": "hybrid",
                    "writeFrequency": "async",
                    "observationMode": "directional",
                    "sessionStrategy": "profile",
                    "dialecticCadence": 3,
                    "saveMessages": True,
                    "observation": True,
                },
            },
        }
        path = profile_home / "honcho.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        _set_yaml_section_value(profile_home / "config.yaml", "memory", "provider", "honcho")
        written.append(path)
    return written


def _configure_agent_models(
    home: Path | None = None, *, container_host: str = CONTAINER_HOST
) -> None:
    """Apply the cloud default to WebUI profiles and native agent runtimes."""
    home = (home or Path.home()).expanduser().resolve()
    container_ollama_url = f"http://{container_host}:11434/v1"
    profile_homes = [home / ".hermes"] + [home / ".hermes" / "profiles" / name for name in SERVICES]
    for profile_home in profile_homes:
        path = profile_home / "config.yaml"
        _set_yaml_section_value(path, "model", "provider", "ollama")
        _set_yaml_section_value(path, "model", "base_url", container_ollama_url)
        text = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^ollama_hosts:", text):
            text += (
                "ollama_hosts:\n"
                "  rack:\n    label: Rack PC\n"
                f"    base_url: {container_ollama_url}\n"
                f"  mac:\n    label: Mac\n    base_url: {container_ollama_url}\n"
            )
            path.write_text(text, encoding="utf-8")
    for profile in SERVICES:
        _set_yaml_section_value(
            home / ".hermes" / "profiles" / profile / "config.yaml",
            "model", "default", DEFAULT_AGENT_MODEL,
        )
    _set_yaml_section_value(
        home / ".hermes" / "config.yaml",
        "model", "default", DEFAULT_AGENT_MODEL,
    )
    _set_yaml_section_value(
        JAEGER_INSTANCE_ROOT / "config.yaml" if home == Path.home().resolve() else home / ".jaeger_ai" / "instances" / "jaeger" / "config.yaml",
        "external_model", "provider", "ollama",
    )
    _set_yaml_section_value(
        JAEGER_INSTANCE_ROOT / "config.yaml" if home == Path.home().resolve() else home / ".jaeger_ai" / "instances" / "jaeger" / "config.yaml",
        "external_model", "model", DEFAULT_AGENT_MODEL,
    )
    _set_yaml_section_value(
        JAEGER_INSTANCE_ROOT / "config.yaml" if home == Path.home().resolve() else home / ".jaeger_ai" / "instances" / "jaeger" / "config.yaml",
        "external_model", "base_url", OLLAMA_OPENAI_URL,
    )

    openclaw_path = home / ".jaeger" / "openclaw" / "openclaw.json"
    if openclaw_path.exists():
        document = json.loads(openclaw_path.read_text(encoding="utf-8"))
        provider_name = "ollama-cloud-via-host"
        provider = document.setdefault("models", {}).setdefault("providers", {}).setdefault(provider_name, {})
        models = provider.setdefault("models", [])
        for model_id in AVAILABLE_AGENT_MODELS:
            if not any(item.get("id") == model_id for item in models if isinstance(item, dict)):
                models.append({
                    "id": model_id,
                    "name": model_id,
                    "input": ["text", "image"],
                    "reasoning": True,
                    "contextWindow": 1_000_000,
                    "maxTokens": 32_768,
                })
        if not any(
            item.get("id") == OPENCLAW_EMBEDDING_MODEL
            for item in models
            if isinstance(item, dict)
        ):
            models.append({
                "id": OPENCLAW_EMBEDDING_MODEL,
                "name": "Qwen3 Embedding 0.6B",
                "input": ["text"],
                "reasoning": False,
            })
        # The pinned Apple-container runtime is OpenClaw 2026.7.1, whose
        # accepted schema keeps search on the agent defaults. Upgrade this
        # producer together with the pinned image, never from the host CLI's
        # independently newer schema.
        document.pop("memory", None)
        defaults = document.setdefault("agents", {}).setdefault("defaults", {})
        memory_search = defaults.setdefault("memorySearch", {})
        memory_search.update({
            "provider": "ollama",
            "model": OPENCLAW_EMBEDDING_MODEL,
            "remote": {"baseUrl": container_ollama_url.removesuffix("/v1")},
        })
        defaults.setdefault("model", {})["primary"] = (
            f"{provider_name}/{DEFAULT_AGENT_MODEL}"
        )
        temporary = openclaw_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, openclaw_path)


def _set_gateway_url(profile: str, port: int, bridge_host: str) -> None:
    path = _profile_config(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    value = f"http://{bridge_host}:{port}"
    line = f"webui_gateway_base_url: {value}"
    if re.search(r"(?m)^webui_gateway_base_url:.*$", text):
        text = re.sub(r"(?m)^webui_gateway_base_url:.*$", line, text)
    else:
        text = text.rstrip() + ("\n" if text.strip() else "") + line + "\n"
    if not re.search(r"(?m)^webui_chat_backend:.*$", text):
        text += "webui_chat_backend: gateway\n"
    path.write_text(text, encoding="utf-8")


def _plist(label: str, module: str) -> bytes:
    logs = JAEGER_RUNTIME_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [sys.executable, "-B", "-m", module],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(Path.home() / ".cache" / "jaeger" / "pycache"),
            "OPENCLAW_ADAPTER_NATIVE_RUNS": "1",
            "ROUNDTABLE_NATIVE_RUNS": "1",
            "PATH": f"{Path.home()}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StandardOutPath": str(logs / f"{label}.log"),
        "StandardErrorPath": str(logs / f"{label}.err.log"),
    })


def install(bridge_host: str) -> int:
    grants = _configure_workspace_roots()
    print(f"workspace access: updated {grants}")
    catalogs = _configure_webui_workspaces()
    print(f"workspace tabs: updated {len(catalogs)} profiles")
    _configure_agent_models()
    print(f"agent model default: {DEFAULT_AGENT_MODEL}")
    _configure_agent_connectivity()
    print(f"agent network: MCP {MCP_HTTP_URL}; A2A {A2A_URL}")
    honcho_configs = _configure_honcho()
    print(f"agent memory: {len(honcho_configs)} Honcho profiles via {HONCHO_LAN_URL}")
    domain = f"gui/{os.getuid()}"
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    for profile, (module, port) in SERVICES.items():
        label = f"com.jenkinsrobotics.{profile}-hermes-adapter"
        path = agents / f"{label}.plist"
        path.write_bytes(_plist(label, module))
        _set_gateway_url(profile, port, bridge_host)
        subprocess.run(["/bin/launchctl", "bootout", domain, str(path)], capture_output=True)
        result = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if result.returncode:
            print(f"{profile}: launch failed: {result.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"{profile}: installed on {bridge_host}:{port}")
    supervisor_path = agents / f"{SUPERVISOR_LABEL}.plist"
    supervisor_path.write_bytes(_plist(SUPERVISOR_LABEL, SUPERVISOR_MODULE))
    subprocess.run(
        ["/bin/launchctl", "bootout", domain, str(supervisor_path)],
        capture_output=True,
    )
    result = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(supervisor_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print(f"supervisor: launch failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print("supervisor: installed")
    return 0


def status() -> int:
    listing = subprocess.run(["/bin/launchctl", "list"], capture_output=True, text=True).stdout
    failed = False
    for profile in SERVICES:
        label = f"com.jenkinsrobotics.{profile}-hermes-adapter"
        running = label in listing
        print(f"{profile}: {'running' if running else 'stopped'}")
        failed |= not running
    supervisor_running = SUPERVISOR_LABEL in listing
    print(f"supervisor: {'running' if supervisor_running else 'stopped'}")
    failed |= not supervisor_running
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status"))
    parser.add_argument("--bridge-host", default="192.168.64.1")
    args = parser.parse_args()
    return install(args.bridge_host) if args.action == "install" else status()


if __name__ == "__main__":
    raise SystemExit(main())
