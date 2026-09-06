"""Install and inspect the shared Hermes WebUI profile adapter services.

Run with ``python -m jaeger_ai.interfaces.hermes_profile_adapters.setup install``.
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

SERVICES = {
    "jaeger": ("jaeger", 8642),
    "roundtable": ("roundtable", 8643),
    "openclaw": ("openclaw", 8644),
}
SUPERVISOR_LABEL = "com.jenkinsrobotics.agent-fabric-supervisor"
SUPERVISOR_MODULE = "jaeger_ai.core.runtime.fabric_supervisor"
HOST_TOOLS_GATEWAY_LABEL = "com.jenkinsrobotics.ares-agentgateway"
DEFAULT_AGENT_MODEL = "glm-5.3-flash:cloud"
AVAILABLE_AGENT_MODELS = (DEFAULT_AGENT_MODEL, "glm-5.3:cloud")
OPENCLAW_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_OLLAMA_BASE_URL = "http://10.15.0.239:11434/v1"
JAEGER_MCP_URL = "http://192.168.64.1:8811/mcp"
JAEGER_A2A_URL = "http://192.168.64.1:8812"
HONCHO_LAN_URL = "http://10.15.0.239:8088"
HONCHO_WORKSPACE = "jenkins-robotics"
REPO_ROOT = Path(__file__).resolve().parents[3]
JAEGER_RUNTIME_ROOT = REPO_ROOT / ".jaeger_ai" / "shared"
JAEGER_INSTANCE_ROOT = REPO_ROOT / ".jaeger_ai" / "instances" / "jaeger"

WORKSPACE_IDENTITIES = ("jaeger", "hermes", "openclaw")

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
    """Add shared roots to ARES's identity-scoped host capability registry.

    Existing capabilities and identity-specific roots are preserved. Network
    roots remain registered while a share is offline and become usable again
    when macOS remounts it.
    """
    home = (home or Path.home()).expanduser().resolve()
    grants = home / ".ares" / "capabilities" / "grants.json"
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


def _configure_agent_connectivity(home: Path | None = None) -> None:
    """Publish Jaeger's MCP endpoint to every runtime using native config."""
    home = (home or Path.home()).expanduser().resolve()
    profile_homes = [home / ".hermes"] + [
        home / ".hermes" / "profiles" / profile for profile in SERVICES
    ]
    block = (
        "  jaeger-host:\n"
        f"    url: {JAEGER_MCP_URL}\n"
        "    connect_timeout: 60.0\n"
        "    headers:\n"
        "      Authorization: Bearer ${MCP_ARES_HOST_API_KEY}\n"
        "    enabled: true\n"
    )
    for profile_home in profile_homes:
        path = profile_home / "config.yaml"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # Migrate the historical label without duplicating the same endpoint.
        text = re.sub(r"(?m)^  ares-host:$", "  jaeger-host:", text)
        if not re.search(r"(?m)^  jaeger-host:$", text):
            text = text.rstrip() + ("\n" if text.strip() else "")
            text += ("mcp_servers:\n" if not re.search(r"(?m)^mcp_servers:$", text) else "")
            text += block
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")

    openclaw_path = home / ".ares" / "openclaw" / "openclaw.json"
    if openclaw_path.exists():
        document = json.loads(openclaw_path.read_text(encoding="utf-8"))
        document.setdefault("gateway", {}).pop("mcp", None)
        servers = document.setdefault("mcp", {}).setdefault("servers", {})
        servers["jaeger-host"] = {
            "url": JAEGER_MCP_URL,
            "transport": "streamable-http",
        }
        mcp_token_path = home / ".ares" / "openclaw" / "ares-mcp.token"
        host_key = ""
        if mcp_token_path.exists():
            host_key = mcp_token_path.read_text(encoding="utf-8").strip()
        else:
            secret_path = home / ".hermes" / "profiles" / "openclaw" / ".env"
            try:
                for line in secret_path.read_text(encoding="utf-8").splitlines():
                    key, separator, value = line.partition("=")
                    if separator and key.strip() == "MCP_ARES_HOST_API_KEY":
                        host_key = value.strip().strip("\"'")
                        break
            except OSError:
                pass
        if host_key:
            servers["ares-system"] = {
                "url": "http://192.168.64.1:8813/mcp",
                "transport": "streamable-http",
                "headers": {
                    "Authorization": f"Bearer {host_key}",
                    "Host": "127.0.0.1:8813",
                },
            }
        temporary = openclaw_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, openclaw_path)

    # Keep the upstream ARES checkout clean. Its unchanged capability server
    # recognizes the Hermes service identity; the Jaeger-owned deployment
    # config maps OpenClaw's authorized gateway target onto that isolated
    # service account (both identities receive the same explicit grants).
    gateway_path = home / ".ares" / "gateway" / "config.yaml"
    if gateway_path.exists():
        import yaml

        gateway = yaml.safe_load(gateway_path.read_text(encoding="utf-8")) or {}
        for target in gateway.get("mcp", {}).get("targets", []):
            if target.get("name") == "host-openclaw":
                stdio = target.setdefault("stdio", {})
                stdio["cmd"] = str(REPO_ROOT / ".venv" / "bin" / "python")
                stdio["args"] = [str(REPO_ROOT / "scripts" / "run-host-capability-server.py")]
                env = stdio.setdefault("env", {})
                env["ARES_CAPABILITY_IDENTITY"] = "hermes"
                env["OLLAMA_BASE_URL"] = "http://10.15.0.239:11434"
                env["HONCHO_WORKSPACE"] = HONCHO_WORKSPACE
                env["HONCHO_API_URL"] = HONCHO_LAN_URL
        temporary = gateway_path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(gateway, sort_keys=False), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, gateway_path)


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


def _configure_agent_models(home: Path | None = None) -> None:
    """Apply the cloud default to WebUI profiles and native agent runtimes."""
    home = (home or Path.home()).expanduser().resolve()
    profile_homes = [home / ".hermes"] + [home / ".hermes" / "profiles" / name for name in SERVICES]
    for profile_home in profile_homes:
        path = profile_home / "config.yaml"
        _set_yaml_section_value(path, "model", "provider", "ollama")
        _set_yaml_section_value(path, "model", "base_url", DEFAULT_OLLAMA_BASE_URL)
        text = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^ollama_hosts:", text):
            text += (
                "ollama_hosts:\n"
                "  rack:\n    label: Rack PC\n"
                f"    base_url: {DEFAULT_OLLAMA_BASE_URL}\n"
                "  mac:\n    label: Mac\n    base_url: http://192.168.64.1:11434/v1\n"
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
        "external_model", "base_url", DEFAULT_OLLAMA_BASE_URL,
    )

    openclaw_path = home / ".ares" / "openclaw" / "openclaw.json"
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
        # OpenClaw 2026.7.x stores search configuration on the agent defaults.
        # Its newer documentation has moved this to top-level ``memory.search``;
        # keep the deployed runtime's schema valid until that binary is upgraded.
        document.pop("memory", None)
        memory_search = document.setdefault("agents", {}).setdefault("defaults", {}).setdefault(
            "memorySearch", {},
        )
        memory_search.update({
            "provider": "ollama",
            "model": OPENCLAW_EMBEDDING_MODEL,
            "remote": {"baseUrl": "http://10.15.0.239:11434"},
        })
        document.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})["primary"] = (
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
        "ProgramArguments": [sys.executable, "-m", module],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            "PATH": f"{Path.home()}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StandardOutPath": str(logs / f"{label}.log"),
        "StandardErrorPath": str(logs / f"{label}.err.log"),
    })


def _host_tools_gateway_plist() -> bytes:
    logs = JAEGER_RUNTIME_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return plistlib.dumps({
        "Label": HOST_TOOLS_GATEWAY_LABEL,
        "ProgramArguments": ["/bin/zsh", str(REPO_ROOT / "scripts" / "run-host-tools-gateway.sh")],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / f"{HOST_TOOLS_GATEWAY_LABEL}.log"),
        "StandardErrorPath": str(logs / f"{HOST_TOOLS_GATEWAY_LABEL}.err.log"),
    })


def install(bridge_host: str) -> int:
    grants = _configure_workspace_roots()
    print(f"workspace access: updated {grants}")
    catalogs = _configure_webui_workspaces()
    print(f"workspace tabs: updated {len(catalogs)} profiles")
    _configure_agent_models()
    print(f"agent model default: {DEFAULT_AGENT_MODEL}")
    _configure_agent_connectivity()
    print(f"agent network: MCP {JAEGER_MCP_URL}; A2A {JAEGER_A2A_URL}")
    honcho_configs = _configure_honcho()
    print(f"agent memory: {len(honcho_configs)} Honcho profiles via {HONCHO_LAN_URL}")
    domain = f"gui/{os.getuid()}"
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    host_gateway_path = agents / f"{HOST_TOOLS_GATEWAY_LABEL}.plist"
    host_gateway_path.write_bytes(_host_tools_gateway_plist())
    subprocess.run(["/bin/launchctl", "bootout", domain, str(host_gateway_path)], capture_output=True)
    result = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(host_gateway_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print(f"host tools gateway: launch failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print("host tools gateway: installed from JaegerAI")
    for profile, (module_name, port) in SERVICES.items():
        label = f"com.jenkinsrobotics.{profile}-hermes-adapter"
        module = f"jaeger_ai.interfaces.hermes_profile_adapters.{module_name}"
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
