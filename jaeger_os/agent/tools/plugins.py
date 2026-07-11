"""Plugin awareness tools — the agent's view of what integrations exist.

  • list_plugins()         — enumerate every bundled plugin with status
  • setup_plugin(name)     — return a step-by-step setup guide

These are read-only / advisory. Actually *applying* setup (writing env
vars, storing tokens) goes through the existing credentials tool plus
the user editing their shell profile — we deliberately don't auto-edit
the user's environment from inside the agent.
"""

from __future__ import annotations

import importlib
import os
import pathlib
from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from jaeger_os.core.context import _require_layout

try:
    import yaml as _yaml  # PyYAML is already a hard dep
except Exception:  # noqa: BLE001
    _yaml = None  # type: ignore[assignment]


_PLUGINS_ROOT = pathlib.Path(__file__).resolve().parents[2] / "plugins"


def _read_manifest(plugin_dir: pathlib.Path) -> dict[str, Any] | None:
    """Parse the plugin's ``plugin.yaml`` through the validated
    :class:`PluginManifest` schema. Returns the dict-shaped manifest
    (preserving the legacy caller contract) or ``None`` on missing /
    malformed input.

    The schema validation surfaces structural bugs (typo'd
    ``requireds:`` etc.) at doctor time via
    :func:`jaeger_os.plugins.manifest.audit_plugin_dir`; this
    function stays permissive — a malformed manifest still parses
    here so the caller can degrade gracefully."""
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.is_file() or _yaml is None:
        return None
    try:
        from jaeger_os.plugins.manifest import load_manifest
        manifest = load_manifest(manifest_path)
        return manifest.model_dump()
    except Exception:  # noqa: BLE001 — fall back to raw YAML on schema fail
        try:
            with manifest_path.open("r", encoding="utf-8") as fh:
                data = _yaml.safe_load(fh)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(data, dict):
            return None
        return data


def _library_status(libraries: list[str]) -> dict[str, bool]:
    """Check whether each named library imports. We deliberately *try*
    the import here rather than relying on ``importlib.util.find_spec``
    because some packages (e.g. ``discord.py``) install under a different
    module name than the distribution name."""
    out: dict[str, bool] = {}
    for lib in libraries or []:
        # discord.py installs as ``discord``; python-telegram-bot installs
        # as ``telegram``. Strip everything after a separator to get the
        # importable name. This is a best-effort heuristic — manifests
        # with unusual install/import name pairs can be patched here.
        import_name = lib.split(".")[0] if "." in lib else lib
        aliases = {
            "discord.py": "discord",
            "python-telegram-bot": "telegram",
            "webrtcvad-wheels": "webrtcvad",
            "pywhispercpp": "pywhispercpp",
        }
        candidate = aliases.get(lib, import_name)
        try:
            importlib.import_module(candidate)
            out[lib] = True
        except Exception:  # noqa: BLE001
            out[lib] = False
    return out


def _env_status(env_names: list[str]) -> dict[str, bool]:
    """For each env-var name, check whether it's set AND non-empty. We
    treat empty string as "not configured" — many users export a blank
    placeholder while wiring things up."""
    out: dict[str, bool] = {}
    for name in env_names or []:
        out[name] = bool(os.environ.get(name, "").strip())
    return out


def _credential_status(env_names: list[str]) -> dict[str, bool]:
    """For each name, check whether a credential of the same lowercase
    name exists in the instance's credentials store. Plugins commonly
    pull from both env vars and the credentials store — either counts
    as "configured" for status purposes."""
    out: dict[str, bool] = {}
    try:
        layout = _require_layout()
    except Exception:
        return {name: False for name in env_names or []}
    from jaeger_os.core import credentials as creds_mod
    try:
        # Case-insensitive: credentials are saved under the env-var name
        # (TELEGRAM_BOT_TOKEN, uppercase, as set_credential / the manifest use),
        # so compare both sides lowercased — otherwise a saved token reads as
        # "needs_credentials" even though get_credential resolves it.
        stored = {s.lower() for s in creds_mod.list_credentials(layout)}
    except Exception:
        stored = set()
    for name in env_names or []:
        out[name] = name.lower() in stored
    return out


def _platform_ok(platforms: list[str]) -> bool:
    """``platforms`` is the manifest's ``requires.platform`` list — empty
    means "any". When set, the current sys.platform must appear in it."""
    if not platforms:
        return True
    import sys
    current = sys.platform  # "darwin", "linux", "win32", ...
    return any(current.startswith(p) for p in platforms)


def list_plugins() -> dict[str, Any]:
    """Return every bundled plugin under ``jaeger_os.plugins``, each
    annotated with library/env/credential install status so the agent
    knows what it can use, what needs setup, and what's blocked by the
    host platform."""
    if not _PLUGINS_ROOT.is_dir():
        return {"plugins": [], "error": "plugins directory not found"}
    out_plugins: list[dict[str, Any]] = []
    for child in sorted(_PLUGINS_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        manifest = _read_manifest(child)
        if manifest is None:
            continue
        requires = manifest.get("requires") or {}
        libraries = list(requires.get("libraries") or [])
        env_required = list(requires.get("env") or [])
        env_optional = list(requires.get("env_optional") or [])
        platforms = list(requires.get("platform") or [])
        libs_ok = _library_status(libraries)
        env_present = _env_status(env_required)
        cred_present = _credential_status(env_required)
        # A required env var counts as "satisfied" if it's set in env
        # OR stored as a credential.
        env_satisfied = {
            name: env_present.get(name, False) or cred_present.get(name, False)
            for name in env_required
        }
        all_libs = all(libs_ok.values()) if libs_ok else True
        all_env = all(env_satisfied.values()) if env_satisfied else True
        platform_ok = _platform_ok(platforms)
        if not platform_ok:
            status = "unsupported_on_this_platform"
        elif all_libs and all_env:
            status = "ready"
        elif not all_libs and not all_env:
            status = "needs_install_and_credentials"
        elif not all_libs:
            status = "needs_install"
        else:
            status = "needs_credentials"
        out_plugins.append({
            "name": manifest.get("name") or child.name,
            "version": manifest.get("version"),
            "description": (manifest.get("description") or "").strip(),
            "status": status,
            "libraries": libs_ok,
            "env_required": env_satisfied,
            "env_optional": env_optional,
            "platform_ok": platform_ok,
            "platform_required": platforms,
        })
    return {"plugins": out_plugins, "count": len(out_plugins)}


def setup_plugin(name: str) -> dict[str, Any]:
    """Return a step-by-step setup guide for the named plugin. Does NOT
    perform the setup — the agent surfaces these steps to the user, who
    runs the install commands and stores the credentials themselves.

    The guide includes: pip install commands for missing libraries, env
    var names that need values, and pointers to the existing
    ``set_credential`` flow for token storage."""
    target = (name or "").strip().lower()
    if not target:
        return {"plugin": name, "error": "plugin name required"}
    plugin_dir = _PLUGINS_ROOT / target
    if not plugin_dir.is_dir():
        return {
            "plugin": name,
            "error": f"unknown plugin {target!r}; run list_plugins() for the catalog",
        }
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        return {"plugin": name, "error": "plugin manifest missing or invalid"}
    requires = manifest.get("requires") or {}
    libraries = list(requires.get("libraries") or [])
    env_required = list(requires.get("env") or [])
    env_optional = list(requires.get("env_optional") or [])
    platforms = list(requires.get("platform") or [])

    libs_ok = _library_status(libraries)
    env_ok = _env_status(env_required)
    cred_ok = _credential_status(env_required)

    steps: list[str] = []
    if platforms and not _platform_ok(platforms):
        import sys
        steps.append(
            f"This plugin requires platform(s) {platforms}; current is "
            f"{sys.platform!r}. Setup not possible on this host."
        )
        return {
            "plugin": name,
            "manifest_description": (manifest.get("description") or "").strip(),
            "blocked": True,
            "steps": steps,
        }

    missing_libs = [lib for lib, ok in libs_ok.items() if not ok]
    if missing_libs:
        joined = " ".join(missing_libs)
        steps.append(
            f"Install Python libraries: `pip install {joined}`. If they "
            f"belong to an optional-extra group (see pyproject.toml), use "
            f"e.g. `pip install -e \".[jaeger]\"` instead of plain pip."
        )

    unsatisfied_env: list[str] = []
    for var in env_required:
        if env_ok.get(var) or cred_ok.get(var):
            continue
        unsatisfied_env.append(var)
    for var in unsatisfied_env:
        steps.append(
            f"Provide credential `{var}`. Either: (a) export it in your "
            f"shell (`export {var}=...`), OR (b) store it in the instance "
            f"credentials store with `set_credential` (CLI: "
            f"`python -m jaeger_os --set-credential {var.lower()}`)."
        )
    if env_optional:
        steps.append(
            "Optional environment variables (defaults apply if unset): "
            + ", ".join(f"`{e}`" for e in env_optional)
        )
    if not steps:
        steps.append("All requirements satisfied — plugin is ready to use.")
    return {
        "plugin": manifest.get("name") or target,
        "version": manifest.get("version"),
        "manifest_description": (manifest.get("description") or "").strip(),
        "blocked": False,
        "steps": steps,
        "library_status": libs_ok,
        "env_status": {
            name: ("env" if env_ok.get(name) else
                   "credential" if cred_ok.get(name) else
                   "missing")
            for name in env_required
        },
    }


# ---------------------------------------------------------------------------
# Agent-facing tool wrappers (migrated from main._register_builtins).
# ---------------------------------------------------------------------------
@register_tool_from_function(name="list_plugins", side_effect="read")
def _t_list_plugins() -> dict:
    """Enumerate the bundled jaeger_os plugins (homeassistant, ai_gen,
    mcp) with install + credential status for each. Use this when the
    user asks what integrations are available, or before suggesting a
    feature you'd need a plugin for. (kokoro_tts and whisper_stt
    graduated from plugins to core engine-modules at 0.8 M1 / M2b;
    discord/telegram/imessage graduated the same way at 0.8 M3b as the
    ``messaging`` module slot — none of them are listed here anymore,
    they're always present / gated on module discovery instead.)"""
    return list_plugins()


@register_tool_from_function(name="setup_plugin")
def _t_setup_plugin(name: str) -> dict:
    """Return step-by-step setup instructions for the named plugin
    (e.g. ``discord``, ``telegram``, ``mcp``). Surfaces
    missing libraries to ``pip install`` and required env vars or
    credentials that need values. Does NOT modify the user's
    environment — the user runs the install commands and stores
    credentials themselves."""
    return setup_plugin(name=name)
