"""Per-app adapter specs and the host primitives they use (all injectable for tests)."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HOME = Path.home()
AS = HOME / "Library/Application Support"


@dataclass(frozen=True)
class ConfigSpec:
    path: Path
    fmt: str                         # json | jsonc | toml | plist
    allow: tuple[str, ...] = ()      # editable dotted keys ("x.*" = anything under x)
    rewritten_by_app: bool = False   # app rewrites the file while running -> refuse writes then
    vendor_cli: str | None = None    # "claude" -> use `claude mcp add-json/remove` for mcpServers.*


@dataclass(frozen=True)
class AppSpec:
    id: str
    name: str
    kind: str                                  # macapp | cli | launchd
    bundle_id: str | None = None
    app_path: Path | None = None
    binary: str | None = None
    label: str | None = None                   # launchd label
    configs: tuple[ConfigSpec, ...] = ()
    invoke: dict[str, list[str]] = field(default_factory=dict)   # action -> argv template ({prompt})
    surfaces: tuple[str, ...] = ()
    self_service: bool = False                 # Jaeger's own gateway/webui/mcp: stop refused
    notes: str = ""

    @property
    def actions(self) -> list[str]:
        acts = []
        if self.kind in ("macapp", "launchd"):
            acts += ["restart"] if self.self_service else ["start", "stop", "restart"]
        acts += [f"invoke:{a}" for a in self.invoke]
        return acts


def _app(id, name, bid, path, **kw):
    return AppSpec(id, name, "macapp", bundle_id=bid, app_path=Path(path), **kw)


def _ld(name, label, **kw):
    return AppSpec(name, name, "launchd", label=label, **kw)


MCP = ("mcp_servers.*",)


def default_specs() -> list[AppSpec]:
    specs = [
        _app("muse", "Muse", "com.meta.endo", "/Applications/Muse.app",
             surfaces=("url:hatch", "url:endo-window", "jaeger muse-bridge"), notes="Opaque store; status/start/stop only."),
        _app("codex_app", "Codex app (ChatGPT)", "com.openai.codex", "/Applications/ChatGPT.app",
             configs=(ConfigSpec(HOME / ".codex/config.toml", "toml", ("mcp_servers.*", "model", "model_reasoning_effort"), rewritten_by_app=True),),
             surfaces=("mcp client", "mcp server")),
        AppSpec("codex_cli", "Codex CLI", "cli", binary="codex",
                configs=(ConfigSpec(HOME / ".codex/config.toml", "toml", ("mcp_servers.*", "model", "model_reasoning_effort"), rewritten_by_app=True),),
                invoke={"exec": ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "{prompt}"]},
                surfaces=("codex exec", "mcp client", "codex mcp-server"),
                notes="Shares config.toml with the Codex app; writes refused while the app runs."),
        _app("claude_desktop", "Claude desktop", "com.anthropic.claudefordesktop", "/Applications/Claude.app",
             configs=(ConfigSpec(AS / "Claude/claude_desktop_config.json", "json", ("mcpServers.*",), rewritten_by_app=True),),
             surfaces=("mcp client (stdio)", "url:claude")),
        AppSpec("claude_code", "Claude Code", "cli", binary="claude",
                configs=(ConfigSpec(HOME / ".claude.json", "json", ("mcpServers.*",), vendor_cli="claude"),
                         ConfigSpec(HOME / ".claude/settings.json", "json", ("model",))),
                invoke={"prompt": ["claude", "-p", "{prompt}"]},
                surfaces=("claude -p", "claude mcp serve", "url:claude-cli")),
        _app("gemini_desktop", "Gemini desktop", "com.google.GeminiMacOS", "/Applications/Gemini.app",
             surfaces=("mcp client (stdio launcher ~/.jaeger/bin)", "url:googlegemini"), notes="Settings in an internal DB; no config edits."),
        AppSpec("gemini_cli", "Gemini CLI", "cli", binary="gemini",
                configs=(ConfigSpec(HOME / ".gemini/settings.json", "json", ("mcpServers.*", "model.name")),),
                invoke={"prompt": ["gemini", "-p", "{prompt}"]}, surfaces=("gemini -p", "mcp client")),
        _app("copilot", "Copilot", "com.copilot.production", "/Applications/Copilot.app",
             configs=(ConfigSpec(HOME / ".copilot/config.json", "json", ()),), surfaces=("url:copilot",)),
        _app("opencode", "OpenCode", "ai.opencode.desktop", "/Applications/OpenCode.app",
             configs=(ConfigSpec(HOME / ".config/opencode/opencode.jsonc", "jsonc", ("mcp.*", "model")),), surfaces=("mcp client", "url:opencode")),
        _app("antigravity", "Antigravity", "com.google.antigravity", "/Applications/Antigravity.app",
             configs=(ConfigSpec(AS / "Antigravity/User/settings.json", "jsonc", (), rewritten_by_app=True),), surfaces=("mcp client", "url:antigravity")),
        _app("antigravity_ide", "Antigravity IDE", "com.google.antigravity-ide", "/Applications/Antigravity IDE.app",
             configs=(ConfigSpec(AS / "Antigravity IDE/User/settings.json", "jsonc", (), rewritten_by_app=True),), surfaces=("mcp client", "url:antigravity-ide")),
        _app("cursor", "Cursor", "com.todesktop.230313mzl4w4u92", "/Applications/Cursor.app",
             configs=(ConfigSpec(HOME / ".cursor/mcp.json", "json", ("mcpServers.*",)),), surfaces=("mcp client", "cursor cli", "url:cursor")),
        _app("vscode", "VS Code", "com.microsoft.VSCode", "/Applications/Visual Studio Code.app",
             configs=(ConfigSpec(AS / "Code/User/mcp.json", "jsonc", ("servers.*",)),
                      ConfigSpec(AS / "Code/User/settings.json", "jsonc", (), rewritten_by_app=True)),
             surfaces=("mcp client", "code cli", "url:vscode")),
        _app("homeclaw", "HomeClaw", "com.shahine.homeclaw", "/Applications/HomeClaw.app", notes="Opaque store."),
        _app("cuadriver", "CuaDriver", "com.trycua.driver", "/Applications/CuaDriver.app",
             notes="Screen control. Invoke disabled; start/stop need Matthew's approval."),
        _app("sam", "SAM", "com.fewtarius.syntheticautonomicmind", "/Applications/SAM.app", notes="Opaque store."),
        AppSpec("openclaw", "OpenClaw", "cli", binary="openclaw",
                configs=(ConfigSpec(HOME / ".openclaw/openclaw.json", "json", ("mcp.servers.*",)),), surfaces=("cli", "mcp client")),
        _app("ollama", "Ollama", "com.electron.ollama", "/Applications/Ollama.app", surfaces=("http 127.0.0.1:11434",),
             notes="Generation goes through jaeger.generate."),
        _ld("n8n", "com.jenkinsrobotics.jaeger-n8n", configs=(ConfigSpec(HOME / ".n8n/config", "json", ()),),
            surfaces=("http 127.0.0.1:5678", "webhooks")),
    ]
    for svc in ("a2a", "ares-worker", "bridge", "colima", "docs-indexer", "gateway", "jobs", "mcp-http",
                "muse-bridge", "rackpc-tunnel", "webui", "ollama-bridge", "hermes-webui-adapter"):
        specs.append(_ld(f"jaeger-{svc}", f"com.jenkinsrobotics.jaeger-{svc}",
                         self_service=svc in ("gateway", "webui", "mcp-http")))
    return specs


# ── host primitives ────────────────────────────────────────────────────

Runner = Callable[..., subprocess.CompletedProcess]


def run(argv: list[str], timeout: float = 30, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input, check=False)


class Host:
    """Everything that touches the real Mac. Tests pass a fake."""

    def __init__(self, runner: Runner = run, which: Callable[[str], str | None] = shutil.which, uid: int | None = None):
        self.runner, self.which, self.uid = runner, which, os.getuid() if uid is None else uid

    def app_running(self, spec: AppSpec) -> bool:
        if spec.kind == "launchd":
            return self.launchd_pid(spec.label) is not None
        if spec.kind != "macapp" or not spec.app_path:
            return False
        r = self.runner(["pgrep", "-f", f"{spec.app_path}/Contents/MacOS/"], timeout=5)
        return r.returncode == 0

    def app_version(self, spec: AppSpec) -> str | None:
        if spec.kind == "macapp" and spec.app_path:
            try:
                with open(spec.app_path / "Contents/Info.plist", "rb") as f:
                    return str(plistlib.load(f).get("CFBundleShortVersionString") or "") or None
            except (OSError, ValueError, plistlib.InvalidFileException):
                return None
        return None

    def installed(self, spec: AppSpec) -> bool:
        if spec.kind == "macapp":
            return bool(spec.app_path and spec.app_path.exists())
        if spec.kind == "cli":
            return bool(spec.binary and self.which(spec.binary))
        return self.launchd_loaded(spec.label) or self.plist_path(spec.label).exists()

    def plist_path(self, label: str | None) -> Path:
        return HOME / "Library/LaunchAgents" / f"{label}.plist"

    def _print(self, label):
        return self.runner(["launchctl", "print", f"gui/{self.uid}/{label}"], timeout=5)

    def launchd_loaded(self, label) -> bool:
        return self._print(label).returncode == 0

    def launchd_pid(self, label) -> int | None:
        r = self._print(label)
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("pid = "):
                try:
                    return int(line[6:])
                except ValueError:
                    return None
        return None

    def start(self, spec: AppSpec) -> subprocess.CompletedProcess:
        if spec.kind == "macapp":
            return self.runner(["open", "-b", spec.bundle_id], timeout=20)
        if not self.launchd_loaded(spec.label):
            r = self.runner(["launchctl", "bootstrap", f"gui/{self.uid}", str(self.plist_path(spec.label))], timeout=20)
            if r.returncode != 0:
                return r
        return self.runner(["launchctl", "kickstart", f"gui/{self.uid}/{spec.label}"], timeout=20)

    def stop(self, spec: AppSpec) -> subprocess.CompletedProcess:
        if spec.kind == "macapp":
            return self.runner(["osascript", "-e", f'quit app id "{spec.bundle_id}"'], timeout=30)
        return self.runner(["launchctl", "bootout", f"gui/{self.uid}/{spec.label}"], timeout=30)

    def restart_launchd(self, spec: AppSpec) -> subprocess.CompletedProcess:
        return self.runner(["launchctl", "kickstart", "-k", f"gui/{self.uid}/{spec.label}"], timeout=30)
