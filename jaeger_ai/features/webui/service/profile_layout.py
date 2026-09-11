"""Hermes WebUI profile display helpers and vendor-home preparation.

Single conversation library (Grok-Bot model): one SI/home chat plus
specialist threads labeled by profile/role badges — not a second empty UI
per profile. Display names stay Hermes Agent / Jaeger / OpenClaw /
Roundtable. The vendor WebUI on :8790 uses an isolated HERMES_HOME; this
module links that home at the shared ``~/.hermes/profiles`` tree (avoiding
isolated 0-byte profile state.dbs) and ensures ``state.db`` has the
``source`` column the sidebar listing requires.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

# Canonical id → chat/profile label (matches vendor static FALLBACK maps).
PROFILE_DISPLAY_NAMES: dict[str, str] = {
    "default": "Hermes Agent",
    "jaeger": "Jaeger",
    "openclaw": "OpenClaw",
    "roundtable": "Roundtable",
}


def profile_display_name(profile_id: str | None) -> str:
    """Return the friendly label for a profile id (default → Hermes Agent)."""
    key = str(profile_id or "default").strip().lower() or "default"
    if key in PROFILE_DISPLAY_NAMES:
        return PROFILE_DISPLAY_NAMES[key]
    return key[:1].upper() + key[1:] if key else PROFILE_DISPLAY_NAMES["default"]


def library_model() -> dict[str, Any]:
    """One conversation library with profile/role badges — no empty second UI per profile.

    Includes the AgentRegistry support model so WebUI can list/switch both
    Jaeger-native agents and third-party adapter faces remotely.
    """
    badges = [
        PROFILE_DISPLAY_NAMES["default"],
        PROFILE_DISPLAY_NAMES["jaeger"],
        PROFILE_DISPLAY_NAMES["openclaw"],
        PROFILE_DISPLAY_NAMES["roundtable"],
        "ARES",
    ]
    catalog: dict[str, Any] = {}
    try:
        from jaeger_ai.core.agent_registry import AgentRegistry

        catalog = AgentRegistry().to_catalog()
    except Exception:  # noqa: BLE001 — layout helpers must stay best-effort
        catalog = {
            "jaeger_native": [],
            "third_party": [],
            "fundamentals_fee_gated": False,
        }
    return {
        "mode": "single_library",
        "empty_profile_uis": False,
        "badges": badges,
        "support_model": {
            "jaeger_native": True,
            "third_party": True,
            "fundamentals_fee_gated": False,
        },
        "agents": catalog,
    }


def _write_display_name(profile_home: Path, *, display_name: str) -> None:
    profile_home.mkdir(parents=True, exist_ok=True)
    meta = profile_home / "profile.yaml"
    existing = meta.read_text(encoding="utf-8") if meta.is_file() else ""
    lines = [ln for ln in existing.splitlines() if not ln.strip().startswith("display_name:")]
    lines = [ln for ln in lines if not ln.strip().startswith("visible:")]
    lines.insert(0, f"display_name: {display_name}")
    meta.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ensure_webui_profile_layout(hermes_home: Path | None = None) -> dict[str, Any]:
    """Ensure named-profile display names; leave other profiles visible."""
    home = (hermes_home or (Path.home() / ".hermes")).expanduser()
    profiles = home / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    _write_display_name(home, display_name=PROFILE_DISPLAY_NAMES["default"])
    written: list[str] = ["default"]
    for folder, label in PROFILE_DISPLAY_NAMES.items():
        if folder == "default":
            continue
        path = profiles / folder
        if path.is_dir():
            _write_display_name(path, display_name=label)
            written.append(folder)
    visible = sorted(
        p.name
        for p in profiles.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != "default"
    )
    return {
        "hermes_home": str(home),
        "visible_named_profiles": visible,
        "display_names": {name: PROFILE_DISPLAY_NAMES.get(name, name) for name in written},
        "archived": [],
    }


def link_shared_profiles(*, shared: Path, agent_home: Path) -> dict[str, Any]:
    """Point ``agent_home/profiles`` at the shared Hermes profile tree.

    A leftover real directory is renamed aside, not deleted. That leftover is
    what produced isolated 0-byte profile ``state.db`` files under the vendor
    HERMES_HOME; once the symlink is in place the fork writes the shared tree.
    """
    agent_home = agent_home.expanduser()
    shared = shared.expanduser()
    target = agent_home / "profiles"
    agent_home.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"linked": False, "replaced": None, "shared": str(shared)}
    if not shared.is_dir():
        result["error"] = "shared profiles missing"
        return result
    if target.is_symlink():
        try:
            if target.resolve() == shared.resolve():
                result["linked"] = True
                return result
        except OSError:
            pass
        target.unlink()
    elif target.exists():
        bak = target.with_name(f"profiles.bak-{int(time.time())}")
        target.rename(bak)
        result["replaced"] = str(bak)
    target.symlink_to(shared, target_is_directory=True)
    result["linked"] = True
    return result


def ensure_agent_state_schema(agent_home: Path) -> dict[str, Any]:
    """Guarantee ``state.db`` exists with a ``source`` column.

    ``vendor/hermes-webui/api/agent_sessions.py`` returns an empty list when
    the column is missing, which is the empty-sidebar failure on :8790.
    This does not import live Hermes history — that is the Phase 1 catalog
    import.
    """
    agent_home = agent_home.expanduser()
    agent_home.mkdir(parents=True, exist_ok=True)
    db = agent_home / "state.db"
    conn = sqlite3.connect(str(db))
    added: list[str] = []
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                model TEXT,
                cwd TEXT,
                started_at REAL,
                ended_at REAL,
                end_reason TEXT,
                parent_session_id TEXT,
                message_count INTEGER
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "source" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN source TEXT")
            added.append("source")
        conn.commit()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        return {
            "path": str(db),
            "source_column": "source" in cols,
            "added": added,
        }
    finally:
        conn.close()


def ensure_vendor_config_yaml(agent_home: Path) -> dict[str, Any]:
    """Ensure ``config.yaml`` exists under the vendor HERMES_HOME with a reachable Ollama URL.

    Missing config leaves gateway_chat / model routing half-configured and is a
    common overnight break after HERMES_HOME moved from ``~/.jaeger_ai`` to
    ``~/.jaeger``. Prefer copying an existing home config, then rewrite dead
    Tailscale / VM host IPs to loopback for the Mac-native WebUI.
    """
    agent_home = agent_home.expanduser()
    agent_home.mkdir(parents=True, exist_ok=True)
    dst = agent_home / "config.yaml"
    home = Path.home()
    candidates = [
        home / ".hermes" / "config.yaml",
        home / ".jaeger_ai" / "hermes-webui-agent" / "config.yaml",
    ]
    raw = dst.read_text(encoding="utf-8") if dst.exists() else ""
    source = str(dst) if raw else None
    if not raw:
        for c in candidates:
            if c.is_file():
                raw = c.read_text(encoding="utf-8")
                source = str(c)
                break
    if not raw:
        raw = """model:
  default: glm-5.3-flash:cloud
  provider: ollama
  base_url: http://192.168.64.1:11434/v1
providers:
  only_configured: false
webui:
  host: 0.0.0.0
  port: 8790
  session_save_mode: deferred
"""
        source = "builtin-default"
    # Locked overnight spine: Ollama at http://192.168.64.1:11434 (Gateway health).
    # Only rewrite known-dead hosts; never touch 192.168.64.1.
    locked_ollama = "http://192.168.64.1:11434"
    for bad in (
        "http://100.78.245.49:11434",
        "http://192.168.65.1:11434",
    ):
        raw = raw.replace(bad + "/v1", locked_ollama + "/v1")
        raw = raw.replace(bad, locked_ollama)
    if "webui:" not in raw:
        raw += """
webui:
  host: 0.0.0.0
  port: 8790
  session_save_mode: deferred
"""
    dst.write_text(raw, encoding="utf-8")
    try:
        dst.chmod(0o600)
    except OSError:
        pass
    return {"path": str(dst), "source": source, "bytes": dst.stat().st_size}


def ensure_profile_state_schemas(agent_home: Path, shared_profiles: Path | None = None) -> dict[str, Any]:
    """Ensure every profile ``state.db`` has the ``source`` column WebUI requires."""
    fixed: list[str] = []
    roots = [agent_home.expanduser()]
    if shared_profiles is not None:
        roots.append(shared_profiles.expanduser())
    seen: set[Path] = set()
    for root in roots:
        dbs = [root / "state.db"]
        profiles = root / "profiles"
        if profiles.is_dir():
            dbs.extend(sorted(profiles.glob("*/state.db")))
        for db in dbs:
            try:
                real = db.resolve()
            except OSError:
                real = db
            if real in seen or not db.exists():
                continue
            seen.add(real)
            before = ensure_agent_state_schema(db.parent)
            if before.get("added"):
                fixed.append(str(db))
    return {"fixed": fixed, "checked": len(seen)}


def prepare_vendor_webui_home(
    agent_home: Path | None = None,
    *,
    hermes_home: Path | None = None,
) -> dict[str, Any]:
    """Ready the :8790 vendor HERMES_HOME: names, shared profile link, state.db schema.

    ``HERMES_HOME`` for the host WebUI is ``~/.jaeger/hermes-webui-agent``.
    That directory is the ``default`` profile, so it needs ``profile.yaml`` with
    ``display_name: Hermes Agent``. Named profiles live under the shared
    ``~/.hermes/profiles`` tree (symlinked in) so the single-library model never
    spawns empty second UIs / 0-byte profile state.dbs.
    """
    home = Path.home()
    hermes = (hermes_home or (home / ".hermes")).expanduser()
    agent = (agent_home or (home / ".jaeger" / "hermes-webui-agent")).expanduser()
    layout = ensure_webui_profile_layout(hermes)
    linked = link_shared_profiles(shared=hermes / "profiles", agent_home=agent)
    # Vendor HERMES_HOME itself is the default/root profile for :8790.
    _write_display_name(agent, display_name=PROFILE_DISPLAY_NAMES["default"])
    # If the symlink is live, refresh labels on named profiles via the shared tree.
    agent_profiles = agent / "profiles"
    named_written: dict[str, str] = {"default": PROFILE_DISPLAY_NAMES["default"]}
    if agent_profiles.is_dir():
        for folder, label in PROFILE_DISPLAY_NAMES.items():
            if folder == "default":
                continue
            path = agent_profiles / folder
            if path.is_dir():
                _write_display_name(path, display_name=label)
                named_written[folder] = label
    schema = ensure_agent_state_schema(agent)
    config = ensure_vendor_config_yaml(agent)
    schemas = ensure_profile_state_schemas(agent, shared_profiles=hermes / "profiles")
    return {
        "agent_home": str(agent),
        "layout": layout,
        "profiles": linked,
        "display_names": named_written,
        "state_db": schema,
        "config": config,
        "profile_schemas": schemas,
        "library": library_model(),
    }
