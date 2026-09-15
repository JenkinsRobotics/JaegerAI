"""Every session store Jaeger writes to, in one place, correctly attributed.

Conversations land in more than one database depending on who created them,
and until now none of them agreed on whose conversation it was:

* ``~/.jaeger/gateway_sessions.sqlite3`` — the Jaeger Gateway's own store. It
  stamped ``profile="jaeger"`` on every row by default, so a live store held
  65 sessions all claiming to be Jaeger's, Hermes' and OpenClaw's included.
* ``~/.hermes/state.db`` — written by the Hermes agent itself. It records a
  ``source`` (webui / cli / api_server) but leaves ``profile_name`` NULL,
  because Hermes knows nothing about Jaeger profiles.
* ``<HERMES_HOME>/state.db`` — the vendored WebUI's own home.
* ``~/.ares/openclaw/agents/<agent>/sessions/*.jsonl`` — OpenClaw keeps a file
  per conversation, not a database. It is bind-mounted out of the container, so
  the host path is readable directly. Missing this is why OpenClaw showed zero
  conversations while holding 121.
* ``~/.hermes/profiles/<name>/state.db`` — one store per named profile, which
  is where that framework's **terminal** conversations land. Missing these was
  why Jaeger appeared to have no CLI history at all: its 88 terminal sessions
  sit in ``profiles/jaeger/state.db``, not in any store listed above.

This module reads all of them, repairs attribution from the session id (see
:mod:`jaeger_ai.contract.sessions`), and answers the question the sidebar
actually asks: *for this framework, which conversations were started in the
browser and which in a terminal?*

Reads are non-destructive. :func:`prune_sessions` is the only writer and it
requires an explicit cutoff.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from jaeger_ai.contract.frameworks import FRAMEWORKS, display_name
from jaeger_ai.contract.sessions import Attribution, attribute


@dataclass(frozen=True)
class SessionRow:
    """One conversation, wherever it was stored."""

    session_id: str
    store: str
    runtime: str | None
    surface: str | None
    title: str
    message_count: int | None
    """Messages in the conversation, or ``None`` when the store does not record
    one. ``None`` is not zero: the Gateway store has no message-count column at
    all, so treating its rows as empty would mark every Gateway conversation as
    junk. Anything that decides an action on emptiness must check for ``None``
    first."""

    updated_at: float

    @property
    def badge(self) -> str:
        return display_name(self.runtime) if self.runtime else "Unattributed"

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.updated_at) / 86400.0)


@dataclass
class Endpoint:
    """A session database and how to read it."""

    name: str
    path: Path
    kind: str = "sqlite"
    """``sqlite`` for a database, ``jsonl`` for a directory of session files."""

    table: str = "sessions"
    id_col: str = "session_id"
    profile_col: str | None = "profile"
    source_col: str | None = None
    title_col: str = "title"
    count_col: str | None = None
    time_col: str = "updated_at"
    default_runtime: str | None = None
    """Whose conversations this database holds when a row says nothing else.

    Hermes writes its own ``state.db`` with ids that predate Jaeger's naming
    and ``profile_name`` NULL — but every row in it is still a Hermes
    conversation. That is where the row lives, not a guess about it."""
    extra: dict[str, Any] = field(default_factory=dict)

    def exists(self) -> bool:
        return self.path.is_dir() if self.kind == "jsonl" else self.path.is_file()


def _openclaw_home() -> Path:
    """Where OpenClaw keeps its home — the container's bind-mount source."""
    return _state_root() / "openclaw"


def _state_root() -> Path:
    for var in ("JAEGER_STATE_DIR", "JAEGER_HOME"):
        value = os.environ.get(var, "").strip()
        if value:
            return Path(value).expanduser()
    return Path.home() / ".jaeger"


def endpoints() -> list[Endpoint]:
    """Every store this machine might hold conversations in."""
    root = _state_root()
    hermes_home = Path(os.environ.get("HERMES_HOME", "").strip() or Path.home() / ".hermes")
    return [
        Endpoint("gateway", root / "gateway_sessions.sqlite3",
                 profile_col="profile", title_col="title",
                 time_col="updated_at", extra={"meta_col": "metadata_json"}),
        Endpoint("hermes", hermes_home / "state.db",
                 id_col="id", profile_col="profile_name", source_col="source",
                 title_col="title", count_col="message_count",
                 time_col="last_activity_at", default_runtime="hermes"),
        Endpoint("webui-home", root / "hermes-webui-agent" / "state.db",
                 id_col="id", profile_col=None, source_col="source",
                 title_col="title", count_col="message_count",
                 time_col="started_at", default_runtime="hermes"),
        *_profile_endpoints(hermes_home),
        *_openclaw_endpoints(),
    ]


def _openclaw_endpoints() -> list[Endpoint]:
    """OpenClaw's conversations, one JSONL file each.

    OpenClaw's home is the container's bind-mount source, under Jaeger's state
    root. It lived at ``~/.ares/openclaw`` only because that is where the mount
    was pointed when ARES was installed; nothing about it was ARES state, and
    it moved with the rest of the install. Note it is NOT ``~/.openclaw``,
    which is a separate empty host install — looking there is what made
    OpenClaw appear to have no history at all.
    """
    base = _openclaw_home() / "agents"
    if not base.is_dir():
        return []
    return [
        Endpoint(f"openclaw:{agent.name}", agent / "sessions",
                 kind="jsonl", default_runtime="openclaw")
        for agent in sorted(base.iterdir())
        if (agent / "sessions").is_dir()
    ]


def _profile_endpoints(hermes_home: Path) -> list[Endpoint]:
    """One endpoint per ``~/.hermes/profiles/<name>/state.db``.

    The folder name IS the framework — that is how Hermes partitions profile
    state — so these rows are attributed by where they live even though the
    schema carries no profile column. Enumerated rather than hardcoded so an
    operator-created profile is picked up too.
    """
    base = hermes_home / "profiles"
    if not base.is_dir():
        return []
    out: list[Endpoint] = []
    for folder in sorted(base.iterdir()):
        store = folder / "state.db"
        if not store.is_file():
            continue
        out.append(Endpoint(
            f"profile:{folder.name}", store,
            id_col="id", profile_col=None, source_col="source",
            title_col="title", count_col="message_count",
            time_col="started_at", default_runtime=folder.name,
        ))
    return out


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _read_jsonl(endpoint: Endpoint) -> Iterator[SessionRow]:
    """One conversation per ``<uuid>.jsonl``.

    The sibling ``.trajectory.jsonl`` and ``.trajectory-path.json`` files are
    the same conversation's internal trace, not separate conversations — three
    files per session is why a naive count reported 363 instead of 121.

    The first line is a ``session`` header carrying the id and start time; the
    remaining lines are the turn log, so the line count minus that header is a
    usable message count. Read without loading the file: these run to hundreds
    of kilobytes each.
    """
    for path in sorted(endpoint.path.glob("*.jsonl")):
        if path.name.endswith(".trajectory.jsonl"):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                header = handle.readline()
                lines = sum(1 for _ in handle)
        except OSError:
            continue
        title = ""
        try:
            title = str((json.loads(header) or {}).get("cwd") or "")
        except (json.JSONDecodeError, TypeError):
            pass
        yield SessionRow(
            session_id=path.stem,
            store=endpoint.name,
            runtime=endpoint.default_runtime,
            surface=None,
            title=title[:70],
            message_count=lines,
            updated_at=path.stat().st_mtime,
        )


def _read(endpoint: Endpoint) -> Iterator[SessionRow]:
    if not endpoint.exists():
        return
    if endpoint.kind == "jsonl":
        yield from _read_jsonl(endpoint)
        return
    conn = sqlite3.connect(f"file:{endpoint.path}?mode=ro", uri=True)
    try:
        have = _columns(conn, endpoint.table)
        if not have:
            return
        want = {"sid": endpoint.id_col, "title": endpoint.title_col}
        for key, col in (("profile", endpoint.profile_col),
                         ("source", endpoint.source_col),
                         ("count", endpoint.count_col),
                         ("time", endpoint.time_col),
                         ("meta", endpoint.extra.get("meta_col"))):
            if col and col in have:
                want[key] = col
        select = ", ".join(f"{col} AS {alias}" for alias, col in want.items())
        for row in conn.execute(f"SELECT {select} FROM {endpoint.table}"):  # noqa: S608
            data = dict(zip(want.keys(), row))
            source = data.get("source")
            if not source and data.get("meta"):
                try:
                    source = (json.loads(data["meta"]) or {}).get("source")
                except (json.JSONDecodeError, TypeError):
                    source = None
            found: Attribution = attribute(data["sid"], source, data.get("profile"),
                                           endpoint.default_runtime)
            yield SessionRow(
                session_id=str(data["sid"]),
                store=endpoint.name,
                runtime=found.runtime,
                surface=found.surface,
                title=str(data.get("title") or "")[:70],
                message_count=(int(data["count"]) if data.get("count") is not None
                               else (0 if endpoint.count_col else None)),
                updated_at=float(data.get("time") or 0.0),
            )
    finally:
        conn.close()


def all_sessions() -> list[SessionRow]:
    """Every conversation on this machine, newest first."""
    rows: list[SessionRow] = []
    for endpoint in endpoints():
        rows.extend(_read(endpoint))
    return sorted(rows, key=lambda r: r.updated_at, reverse=True)


def by_profile() -> dict[str, dict[str, list[SessionRow]]]:
    """``{runtime: {"browser": [...], "terminal": [...], "other": [...]}}``.

    Every framework gets an entry even with no conversations, so a caller can
    render an empty profile rather than omitting it — a missing row reads as a
    broken profile, an empty one reads as a new profile.
    """
    # Only session-owning frameworks get buckets. Roundtable is orchestrated
    # from the WebUI and has no app or terminal of its own, so a "Roundtable
    # terminal session" cannot exist; giving it a terminal bucket invites
    # someone to fill one.
    out: dict[str, dict[str, list[SessionRow]]] = {
        f.runtime: {"browser": [], "terminal": [], "other": []}
        for f in FRAMEWORKS if f.owns_sessions
    }
    out["roundtable"] = {"browser": [], "other": []}
    out["unattributed"] = {"browser": [], "terminal": [], "other": []}
    for row in all_sessions():
        bucket = out.get(row.runtime or "unattributed")
        if bucket is None:
            continue
        found = attribute(row.session_id, row.surface, row.runtime)
        key = ("browser" if found.started_in_browser
               else "terminal" if found.started_in_terminal else "other")
        # A framework with no app or terminal has no terminal bucket. A row
        # that looks terminal there is a mislabelled source, not a real
        # terminal conversation, so it lands in "other" rather than inventing
        # a bucket the framework cannot have.
        if key not in bucket:
            key = "other"
        bucket[key].append(row)
    return out


def prune_sessions(
    older_than_days: float,
    *,
    min_messages: int = 1,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Delete stale, empty conversations from every store.

    Conservative on purpose — only rows that are BOTH older than the cutoff and
    hold fewer than ``min_messages`` messages are removed, so a long-idle real
    conversation survives while probe and smoke-test leftovers do not.

    A store that does not record a message count is SKIPPED, not assumed empty.
    The Gateway store has no such column, and reading its missing count as zero
    made a dry run offer to delete 64 real conversations as "empty". Emptiness
    you cannot measure is not emptiness.

    ``dry_run`` is the default: nothing is deleted unless it is set False.
    """
    if older_than_days <= 0:
        raise ValueError("older_than_days must be positive")
    cutoff = time.time() - older_than_days * 86400.0
    report: dict[str, Any] = {"dry_run": dry_run, "cutoff_days": older_than_days,
                              "removed": {}, "kept": 0}
    report["skipped"] = {}
    for endpoint in endpoints():
        if not endpoint.exists():
            continue
        if not endpoint.count_col:
            report["skipped"][endpoint.name] = "no message-count column; cannot judge emptiness"
            continue
        doomed = [
            r for r in _read(endpoint)
            if r.updated_at and r.updated_at < cutoff
            and r.message_count is not None and r.message_count < min_messages
        ]
        report["removed"][endpoint.name] = [r.session_id for r in doomed]
        if doomed and not dry_run:
            conn = sqlite3.connect(endpoint.path)
            try:
                conn.executemany(
                    f"DELETE FROM {endpoint.table} WHERE {endpoint.id_col} = ?",  # noqa: S608
                    [(r.session_id,) for r in doomed],
                )
                conn.commit()
            finally:
                conn.close()
    report["kept"] = len(all_sessions()) - sum(
        len(v) for v in report["removed"].values()
    ) if dry_run else len(all_sessions())
    return report


def repair_attribution(*, dry_run: bool = True) -> dict[str, Any]:
    """Backfill each store's profile column from what the session id says.

    Only fills rows that have no profile recorded; an existing value is left
    alone. Rows whose id carries no framework stay unattributed rather than
    being guessed into a bucket.
    """
    report: dict[str, Any] = {"dry_run": dry_run, "updated": {}}
    for endpoint in endpoints():
        if not endpoint.exists() or not endpoint.profile_col:
            continue
        conn = sqlite3.connect(endpoint.path)
        try:
            if endpoint.profile_col not in _columns(conn, endpoint.table):
                continue
            fixes = [
                (r.runtime, r.session_id)
                for r in _read(endpoint) if r.runtime
            ]
            pending = []
            for runtime, sid in fixes:
                cur = conn.execute(
                    f"SELECT {endpoint.profile_col} FROM {endpoint.table} "  # noqa: S608
                    f"WHERE {endpoint.id_col} = ?", (sid,)).fetchone()
                if cur is not None and not (cur[0] or "").strip():
                    pending.append((runtime, sid))
            report["updated"][endpoint.name] = len(pending)
            if pending and not dry_run:
                conn.executemany(
                    f"UPDATE {endpoint.table} SET {endpoint.profile_col} = ? "  # noqa: S608
                    f"WHERE {endpoint.id_col} = ?", pending)
                conn.commit()
        finally:
            conn.close()
    return report


__all__ = [
    "Endpoint", "SessionRow", "all_sessions", "by_profile",
    "endpoints", "prune_sessions", "repair_attribution",
]
