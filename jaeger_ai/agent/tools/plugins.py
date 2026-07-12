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

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.core.context import _require_layout

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
        from jaeger_ai.plugins.manifest import load_manifest
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
    from jaeger_ai.core import credentials as creds_mod
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


def _find_messaging_module(target: str) -> Any | None:
    """The discovered ``messaging``-slot :class:`ModuleSpec` named
    ``target`` (discord/telegram/imessage), or ``None``. These graduated
    from ``plugin.yaml`` to ``module.yaml`` at 0.8 M3b — no manifest
    directory for :func:`_read_manifest` to find, so callers that fell
    through the manifest path check here before giving up."""
    try:
        from jaeger_os.core.modules import discover_modules
        by_slot = discover_modules()
    except Exception:  # noqa: BLE001 — discovery must never crash a tool call
        return None
    for spec in (by_slot.get("messaging") or []):
        if spec.module == target:
            return spec
    return None


def _messaging_channel_row(spec: Any, layout: Any) -> dict[str, Any]:
    """Build a ``list_plugins()``-shaped row for a module-provided
    messaging channel (discord/telegram/imessage), using the SAME
    status vocabulary as a manifest-backed plugin row so the agent
    doesn't need two code paths to reason about readiness. Credential
    names come from ``plugins/__init__.py``'s ``_BRIDGE_SPECS`` — these
    channels have no ``plugin.yaml`` ``requires:`` block to read."""
    from jaeger_os.core.modules import module_platform_ok
    from jaeger_ai.plugins import _BRIDGE_SPECS, plugin_credential

    channel = spec.module
    bridge_spec = _BRIDGE_SPECS.get(channel) or {}
    token_name = bridge_spec.get("token")
    optional_names = [n for n in (bridge_spec.get("allow"), bridge_spec.get("admin")) if n]

    libs_ok = _library_status(list(spec.requires_libraries))
    platform_ok = module_platform_ok(spec)
    env_required = {}
    if token_name:
        env_required[token_name] = bool(plugin_credential(layout, token_name))

    all_libs = all(libs_ok.values()) if libs_ok else True
    all_env = all(env_required.values()) if env_required else True
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

    return {
        "name": channel,
        "kind": "channel",
        "version": spec.version or None,
        "description": f"Messaging channel ({channel}) — module-provided, slot=messaging.",
        "status": status,
        "libraries": libs_ok,
        "env_required": env_required,
        "env_optional": optional_names,
        "platform_ok": platform_ok,
        "platform_required": list(spec.requires_platform),
    }


def _messaging_channel_rows() -> list[dict[str, Any]]:
    """Every discovered ``messaging``-slot module (discord/telegram/
    imessage today), each as a :func:`_messaging_channel_row`. Never
    raises — discovery/credential lookups degrade to an empty list
    rather than breaking ``list_plugins()``."""
    try:
        from jaeger_os.core.modules import discover_modules
        specs = discover_modules().get("messaging") or []
    except Exception:  # noqa: BLE001
        return []
    try:
        layout = _require_layout()
    except Exception:
        layout = None
    return [_messaging_channel_row(spec, layout) for spec in specs]


def list_plugins() -> dict[str, Any]:
    """Return every bundled plugin under ``jaeger_os.plugins`` PLUS every
    module-provided messaging channel (discord/telegram/imessage — 0.8
    M3b graduated them to ``module.yaml`` and they'd been invisible here
    ever since), each annotated with library/env/credential install
    status so the agent knows what it can use, what needs setup, and
    what's blocked by the host platform. ``kind`` distinguishes a
    manifest-backed ``"plugin"`` row from a module-backed ``"channel"``
    row — both share the same status vocabulary."""
    out_plugins: list[dict[str, Any]] = []
    if _PLUGINS_ROOT.is_dir():
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
                "kind": "plugin",
                "version": manifest.get("version"),
                "description": (manifest.get("description") or "").strip(),
                "status": status,
                "libraries": libs_ok,
                "env_required": env_satisfied,
                "env_optional": env_optional,
                "platform_ok": platform_ok,
                "platform_required": platforms,
            })
    out_plugins.extend(_messaging_channel_rows())
    return {"plugins": out_plugins, "count": len(out_plugins)}


def _setup_messaging_channel(target: str, spec: Any) -> dict[str, Any]:
    """:func:`setup_plugin`'s guide for a module-provided messaging
    channel (discord/telegram/imessage) — no ``plugin.yaml`` exists for
    these (0.8 M3b), so the steps come from the module.yaml spec's
    ``requires_libraries``/``requires_platform`` plus the credential
    names ``plugins/__init__.py``'s ``_BRIDGE_SPECS`` declares for it."""
    from jaeger_os.core.modules import module_platform_ok
    from jaeger_ai.plugins import _BRIDGE_SPECS, plugin_credential

    description = f"Messaging channel ({target}) — module-provided, slot=messaging."
    if not module_platform_ok(spec):
        import sys
        return {
            "plugin": target, "kind": "channel",
            "manifest_description": description,
            "blocked": True,
            "steps": [
                f"This channel requires platform(s) {list(spec.requires_platform)}; "
                f"current is {sys.platform!r}. Setup not possible on this host."
            ],
        }

    steps: list[str] = []
    libs_ok = _library_status(list(spec.requires_libraries))
    missing_libs = [lib for lib, ok in libs_ok.items() if not ok]
    if missing_libs:
        steps.append(f"Install Python libraries: `pip install {' '.join(missing_libs)}`.")

    bridge_spec = _BRIDGE_SPECS.get(target) or {}
    token_name = bridge_spec.get("token")
    try:
        layout = _require_layout()
    except Exception:
        layout = None
    env_status: dict[str, str] = {}
    if token_name:
        have = bool(plugin_credential(layout, token_name))
        env_status[token_name] = "credential" if have else "missing"
        if not have:
            steps.append(
                f"Provide credential `{token_name}`. Store it with "
                f"`set_credential` (CLI: `python -m jaeger_os --set-credential "
                f"{token_name.lower()}`)."
            )
    optional_names = [n for n in (bridge_spec.get("allow"), bridge_spec.get("admin")) if n]
    if optional_names:
        steps.append(
            "Optional allowlist/admin env vars (unset = open to everyone / no "
            "admin): " + ", ".join(f"`{n}`" for n in optional_names)
        )
    if not steps:
        steps.append(
            f'All requirements satisfied — call activate_plugin("{target}") to '
            "bring it live (persists to this instance's autostart list)."
        )
    return {
        "plugin": target, "kind": "channel", "version": spec.version or None,
        "manifest_description": description,
        "blocked": False, "steps": steps,
        "library_status": libs_ok, "env_status": env_status,
    }


def setup_plugin(name: str) -> dict[str, Any]:
    """Return a step-by-step setup guide for the named plugin OR
    module-provided messaging channel (discord/telegram/imessage). Does
    NOT perform the setup — the agent surfaces these steps to the user,
    who runs the install commands and stores the credentials themselves.

    The guide includes: pip install commands for missing libraries, env
    var / credential names that need values, and pointers to the
    existing ``set_credential`` flow for token storage."""
    target = (name or "").strip().lower()
    if not target:
        return {"plugin": name, "error": "plugin name required"}
    plugin_dir = _PLUGINS_ROOT / target
    manifest = _read_manifest(plugin_dir) if plugin_dir.is_dir() else None
    if manifest is None:
        # 0.8.1 item 10: discord/telegram/imessage graduated to
        # module.yaml (plugin.yaml deleted at 0.8 M3b) — fall back to
        # the messaging-slot module spec before reporting unknown/broken.
        channel_spec = _find_messaging_module(target)
        if channel_spec is not None:
            return _setup_messaging_channel(target, channel_spec)
        if not plugin_dir.is_dir():
            return {
                "plugin": name,
                "error": f"unknown plugin {target!r}; run list_plugins() for the catalog",
            }
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
    """Enumerate every bundled jaeger_os plugin (homeassistant, ai_gen,
    mcp) AND every module-provided messaging channel (discord, telegram,
    imessage) with install + credential status for each. Use this when
    the user asks what integrations are available, or before suggesting
    a feature you'd need a plugin/channel for. Each row's ``kind`` is
    ``"plugin"`` (manifest-backed) or ``"channel"`` (module-backed —
    discord/telegram/imessage graduated to the ``messaging`` module
    slot at 0.8 M3b; 0.8.1 item 10 re-surfaced them here after they'd
    gone invisible). ``status`` is one of ready / needs_install /
    needs_credentials / needs_install_and_credentials /
    unsupported_on_this_platform. (kokoro_tts/whisper_stt/animation
    stay module-internal, not listed — they have no user-facing
    credential or install step; only genuinely settable integrations
    show up here.)"""
    return list_plugins()


@register_tool_from_function(name="setup_plugin")
def _t_setup_plugin(name: str) -> dict:
    """Return step-by-step setup instructions for the named plugin or
    messaging channel (e.g. ``discord``, ``telegram``, ``imessage``,
    ``mcp``, ``homeassistant``). Surfaces missing libraries to ``pip
    install`` and required env vars or credentials that need values.
    For a messaging channel, the flow after this is: set_credential the
    named token, then ``activate_plugin(name)`` (which also persists it
    to this instance's autostart so it survives a restart). Does NOT
    modify the user's environment — the user runs the install commands
    and stores credentials themselves."""
    return setup_plugin(name=name)
