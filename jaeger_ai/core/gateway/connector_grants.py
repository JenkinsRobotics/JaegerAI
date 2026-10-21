"""Per-account connector grant records (GB-032).

A grant binds one connector *account* (an opaque label; no credentials are
stored here) to an explicit tool list and scope set. Grants are versioned:
creating the same grant from a replayed OAuth callback (same ``callback_id``)
returns the existing revision; re-granting an account supersedes the previous
record with revision+1. ``authorize_call`` is the fail-closed check a pending
or queued call must pass right before it runs: a revoked or superseded grant,
a stale revision, a tool outside the grant, or a missing resource scope all
refuse, naming the reason and a reconnect path. Another account is never
substituted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable
import uuid

ACTIVE, REVOKED, SUPERSEDED = "active", "revoked", "superseded"


class GrantError(ValueError):
    """Invalid grant request."""


@dataclass(frozen=True)
class ConnectorGrant:
    grant_id: str
    connector: str
    account_id: str
    tools: tuple[str, ...]
    scopes: tuple[str, ...]
    status: str
    revision: int
    callback_id: str
    provenance: str
    created_at: float
    updated_at: float
    revoked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tools"], d["scopes"] = list(self.tools), list(self.scopes)
        d["reconnect"] = reconnect_path(self.connector, self.account_id)
        return d


def reconnect_path(connector: str, account_id: str) -> dict[str, str]:
    return {"action": "reauthorize", "connector": connector, "account_id": account_id}


def _clean_list(values: Iterable[Any], what: str) -> tuple[str, ...]:
    if isinstance(values, str) or values is None:
        raise GrantError(f"{what} must be a list")
    out = sorted({str(v).strip() for v in values if str(v).strip()})
    if "*" in out:
        raise GrantError(f"{what} must be explicit; '*' is not allowed")
    return tuple(out)


class ConnectorGrantStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure(self) -> None:
        if self._ready:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS connector_grants (grant_id TEXT PRIMARY KEY, connector TEXT NOT NULL,"
                " account_id TEXT NOT NULL, tools TEXT NOT NULL, scopes TEXT NOT NULL, status TEXT NOT NULL,"
                " revision INTEGER NOT NULL, callback_id TEXT NOT NULL, provenance TEXT NOT NULL,"
                " created_at REAL NOT NULL, updated_at REAL NOT NULL, revoked_reason TEXT NOT NULL DEFAULT '')")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS cg_callback ON connector_grants(callback_id)"
                      " WHERE callback_id != ''")
            c.execute("CREATE INDEX IF NOT EXISTS cg_account ON connector_grants(connector, account_id)")
        self._ready = True

    @staticmethod
    def _row(r: sqlite3.Row) -> ConnectorGrant:
        return ConnectorGrant(grant_id=r["grant_id"], connector=r["connector"], account_id=r["account_id"],
                              tools=tuple(json.loads(r["tools"])), scopes=tuple(json.loads(r["scopes"])),
                              status=r["status"], revision=r["revision"], callback_id=r["callback_id"],
                              provenance=r["provenance"], created_at=r["created_at"],
                              updated_at=r["updated_at"], revoked_reason=r["revoked_reason"])

    # ── reads (never create the database) ─────────────────────────────
    def list(self, *, connector: str = "", account_id: str = "", include_inactive: bool = False) -> list[ConnectorGrant]:
        if not self.path.exists():
            return []
        q, args = "SELECT * FROM connector_grants WHERE 1=1", []
        if connector:
            q, args = q + " AND connector=?", args + [connector]
        if account_id:
            q, args = q + " AND account_id=?", args + [account_id]
        if not include_inactive:
            q, args = q + " AND status=?", args + [ACTIVE]
        with self._conn() as c:
            return [self._row(r) for r in c.execute(q + " ORDER BY connector, account_id, revision", args)]

    def get(self, grant_id: str) -> ConnectorGrant | None:
        if not self.path.exists():
            return None
        with self._conn() as c:
            r = c.execute("SELECT * FROM connector_grants WHERE grant_id=?", (grant_id,)).fetchone()
        return self._row(r) if r else None

    # ── writes ────────────────────────────────────────────────────────
    def create(self, *, connector: str, account_id: str, tools: Iterable[Any], scopes: Iterable[Any],
               callback_id: str = "", provenance: str = "") -> tuple[ConnectorGrant, bool]:
        """Returns ``(grant, created)``; a replayed ``callback_id`` returns the existing grant."""
        connector, account_id = str(connector or "").strip(), str(account_id or "").strip()
        if not connector or not account_id:
            raise GrantError("connector and account_id are required")
        tools_t, scopes_t = _clean_list(tools, "tools"), _clean_list(scopes, "scopes")
        if not tools_t:
            raise GrantError("tools must name at least one tool")
        callback_id = str(callback_id or "").strip()
        self._ensure()
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                if callback_id:
                    r = c.execute("SELECT * FROM connector_grants WHERE callback_id=?", (callback_id,)).fetchone()
                    if r:
                        c.execute("COMMIT")
                        return self._row(r), False
                cur = c.execute("SELECT * FROM connector_grants WHERE connector=? AND account_id=? AND status=?",
                                (connector, account_id, ACTIVE)).fetchone()
                if cur and tuple(json.loads(cur["tools"])) == tools_t and tuple(json.loads(cur["scopes"])) == scopes_t:
                    c.execute("COMMIT")
                    return self._row(cur), False
                top = c.execute("SELECT MAX(revision) FROM connector_grants WHERE connector=? AND account_id=?",
                                (connector, account_id)).fetchone()[0] or 0
                now = time.time()
                if cur:
                    c.execute("UPDATE connector_grants SET status=?, updated_at=? WHERE grant_id=?",
                              (SUPERSEDED, now, cur["grant_id"]))
                gid = "cgr_" + uuid.uuid4().hex[:16]
                c.execute("INSERT INTO connector_grants VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (gid, connector, account_id, json.dumps(tools_t), json.dumps(scopes_t), ACTIVE,
                           top + 1, callback_id, provenance, now, now, ""))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return self.get(gid), True  # type: ignore[return-value]

    def revoke(self, grant_id: str, *, reason: str = "") -> ConnectorGrant | None:
        """Idempotent. Returns the grant (revoked) or None if unknown."""
        g = self.get(grant_id)
        if g is None or g.status == REVOKED:
            return g
        with self._lock, self._conn() as c:
            c.execute("UPDATE connector_grants SET status=?, revoked_reason=?, updated_at=? WHERE grant_id=?",
                      (REVOKED, str(reason or "")[:300], time.time(), grant_id))
        return self.get(grant_id)

    # ── enforcement check (read-only) ────────────────────────────────
    def authorize_call(self, grant_id: str, *, tool: str, required_scopes: Iterable[Any] = (),
                       expected_revision: int | None = None) -> dict[str, Any]:
        g = self.get(grant_id)
        if g is None:
            return {"allowed": False, "reason": "unknown_grant", "grant_id": grant_id}
        base = {"grant_id": g.grant_id, "connector": g.connector, "account_id": g.account_id,
                "revision": g.revision}
        if g.status != ACTIVE:
            return {**base, "allowed": False, "reason": f"grant_{g.status}",
                    "reconnect": reconnect_path(g.connector, g.account_id)}
        if expected_revision is not None and int(expected_revision) != g.revision:
            return {**base, "allowed": False, "reason": "stale_grant_revision",
                    "reconnect": reconnect_path(g.connector, g.account_id)}
        if str(tool) not in g.tools:
            return {**base, "allowed": False, "reason": "tool_not_granted", "tool": str(tool)}
        missing = sorted(set(_clean_list(required_scopes, "required_scopes")) - set(g.scopes))
        if missing:
            return {**base, "allowed": False, "reason": "missing_scope", "missing_scopes": missing,
                    "reconnect": reconnect_path(g.connector, g.account_id)}
        return {**base, "allowed": True, "reason": "granted"}
