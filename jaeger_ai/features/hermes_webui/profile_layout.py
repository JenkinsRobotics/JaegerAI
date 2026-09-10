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
    """One conversation library with profile/role badges — no empty second UI per profile."""
    badges = [
        PROFILE_DISPLAY_NAMES["default"],
        PROFILE_DISPLAY_NAMES["jaeger"],
        PROFILE_DISPLAY_NAMES["openclaw"],
        PROFILE_DISPLAY_NAMES["roundtable"],
        "ARES",
    ]
    return {
        "mode": "single_library",
        "empty_profile_uis": False,
        "badges": badges,
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


def prepare_vendor_webui_home(
    agent_home: Path | None = None,
    *,
    hermes_home: Path | None = None,
) -> dict[str, Any]:
    """Ready the :8790 vendor HERMES_HOME: names, shared profile link, state.db schema.

    ``HERMES_HOME`` for the host WebUI is ``~/.jaeger_ai/hermes-webui-agent``.
    That directory is the ``default`` profile, so it needs ``profile.yaml`` with
    ``display_name: Hermes Agent``. Named profiles live under the shared
    ``~/.hermes/profiles`` tree (symlinked in) so the single-library model never
    spawns empty second UIs / 0-byte profile state.dbs.
    """
    home = Path.home()
    hermes = (hermes_home or (home / ".hermes")).expanduser()
    agent = (agent_home or (home / ".jaeger_ai" / "hermes-webui-agent")).expanduser()
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
    return {
        "agent_home": str(agent),
        "layout": layout,
        "profiles": linked,
        "display_names": named_written,
        "state_db": schema,
        "library": library_model(),
    }
