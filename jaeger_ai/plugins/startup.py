"""Revision-bound extension startup policy in the existing Gateway metadata owner.

No runtime/database is initialized by discovery. Policy affects future entry-point
loads, never unloads retained code, changes grants, or starts a connection.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote


def environment_id(prefix=None):
    return hashlib.sha256(
        str(Path(prefix or sys.prefix).resolve()).encode()
    ).hexdigest()[:32]


def slot(group, name, package):
    import re

    package = re.sub(r"[-_.]+", "-", package).lower()
    return hashlib.sha256("\0".join((group, name, package)).encode()).hexdigest()[:32]


def _decode(row):
    value = json.loads(row[0]) if row else {"revision": 0, "entries": {}}
    if (
        not isinstance(value, dict)
        or type(value.get("revision")) is not int
        or value.get("revision", -1) < 0
        or not isinstance(value.get("entries"), dict)
    ):
        raise ValueError("Startup policy unavailable")
    if any(
        not isinstance(k, str)
        or not isinstance(v, str)
        or (
            v != "disabled"
            and (len(v) != 32 or any(c not in "0123456789abcdef" for c in v))
        )
        for k, v in value["entries"].items()
    ):
        raise ValueError("Startup policy unavailable")
    return value


def read(store=None, *, environment=None):
    key = "plugin_startup:" + str(environment or environment_id())
    if store is not None:
        conn = store._get_conn()
    else:
        from jaeger_ai.core.gateway.session_store import default_store_path

        path = default_store_path(create=False)
        if not path.exists():
            return {"revision": 0, "entries": {}}
        conn = sqlite3.connect(
            "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro", uri=True
        )
    try:
        return _decode(
            conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        )
    finally:
        conn.close()


def permitted(policy, slot_id, revision):
    setting = policy["entries"].get(slot_id)
    return setting is None or setting == revision


def save(store, *, environment, updates, expected_revision, operation_id, result):
    """CAS and acknowledged policy receipt commit in the SAME Gateway transaction."""
    if type(expected_revision) is not int:
        raise ValueError("Current startup revision required")
    key = "plugin_startup:" + environment
    with store._immediate() as conn:
        prior = conn.execute(
            "SELECT receipt_json FROM control_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if prior is None:
            raise ValueError("Operation was not reserved")
        if prior[0]:
            return json.loads(prior[0])
        pointer = conn.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            ("control_scope:plugin-packages:" + environment,),
        ).fetchone()
        if pointer:
            active = conn.execute(
                "SELECT receipt_json FROM control_operations WHERE operation_id=?",
                (pointer[0],),
            ).fetchone()
            if active is None or active[0] is None:
                raise ValueError(
                    "Package operation unresolved; startup policy retained"
                )
        value = _decode(
            conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        )
        if value["revision"] != expected_revision:
            raise ValueError("Startup policy changed; review current state")
        entries = {**value["entries"], **updates}
        value = {"revision": value["revision"] + 1, "entries": entries}
        _decode((json.dumps(value),))
        conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        receipt = {
            "ok": True,
            "operation_id": operation_id,
            "http_status": 200,
            "result": {
                **result,
                "policy_revision": value["revision"],
                "activation_performed": False,
            },
        }
        conn.execute(
            "UPDATE control_operations SET status='settled',receipt_json=? WHERE operation_id=?",
            (json.dumps(receipt), operation_id),
        )
    return receipt


def assert_package_idle(store, environment):
    conn = store._get_conn()
    try:
        pointer = conn.execute(
            "SELECT value FROM schema_meta WHERE key=?",
            ("control_scope:plugin-packages:" + environment,),
        ).fetchone()
        if pointer:
            row = conn.execute(
                "SELECT receipt_json FROM control_operations WHERE operation_id=?",
                (pointer[0],),
            ).fetchone()
            if row is None or row[0] is None:
                raise ValueError(
                    "Package operation unresolved; startup policy retained until package reconciliation"
                )
    finally:
        conn.close()
