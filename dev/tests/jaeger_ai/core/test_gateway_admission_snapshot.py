"""R01 — admission freezes the complete execution input (RELEASE_AUDIT.md A03).

Before: Gateway admitted a turn by text + request_id only, then wrote the
body's model/provider into mutable session metadata *after* admission — even
for a replay — and execution read that metadata (and every session
attachment) at run time. A retry with a different model was a silent replay
that nonetheless re-pointed the session; an upload after admission leaked
into an already-admitted turn.

After: explicit choices are part of request identity, the resolved snapshot
is persisted atomically with admission, and execution reads only the
snapshot. Pre-upgrade (digest v1) receipts replay by their original digest.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from jaeger_ai.core.gateway.server import _admitted_execution
from jaeger_ai.core.gateway.session_store import (
    GatewaySessionStore,
    RequestConflict,
    input_fingerprint,
)


@pytest.fixture
def store(tmp_path):
    return GatewaySessionStore(tmp_path / "gateway_sessions.sqlite3")


def _finish(store, request_id):
    """Return the session to idle so another turn may be admitted."""
    with store._immediate() as conn:
        row = conn.execute("SELECT session_id FROM client_requests WHERE request_id=?",
                           (request_id,)).fetchone()
        conn.execute("UPDATE client_requests SET status='completed' WHERE request_id=?", (request_id,))
        conn.execute("UPDATE sessions SET status='idle' WHERE session_id=?", (row["session_id"],))


def test_identical_retry_replays_without_touching_session_selection(store):
    first = store.admit_request("s", "work", request_id="r1",
                                requested={"model": "m1", "provider": "p1"})
    assert first["accepted"] and first["execution"]["model"] == "m1"
    store.update_metadata("s", {"model": "operator-changed", "provider": "px"})

    replay = store.admit_request("s", "work", request_id="r1",
                                 requested={"model": "m1", "provider": "p1"})

    assert replay["replayed"] and not replay["accepted"]
    assert replay["execution"] == first["execution"]
    meta = store.get_session("s")["metadata"]
    assert (meta["model"], meta["provider"]) == ("operator-changed", "px")


@pytest.mark.parametrize("changed", [
    {"model": "m2", "provider": "p1"},
    {"model": "m1", "provider": "p2"},
    {"model": "m1", "provider": "p1", "workspace": "/elsewhere"},
    {"model": "m1", "provider": "p1", "options": {"temperature": 0.2}},
    {"model": "m1", "provider": "p1", "attachment_ids": []},
    {},
])
def test_same_request_id_with_different_choices_conflicts(store, changed):
    store.admit_request("s", "work", request_id="r1",
                        requested={"model": "m1", "provider": "p1"})
    with pytest.raises(RequestConflict):
        store.admit_request("s", "work", request_id="r1", requested=changed)


def test_blank_choice_equals_omitted_choice(store):
    store.admit_request("s", "work", request_id="r1", requested={"model": ""})
    replay = store.admit_request("s", "work", request_id="r1", requested={})
    assert replay["replayed"]


def test_omitted_model_resolves_from_session_default_and_stays_frozen(store):
    store.admit_request("s", "set default", request_id="r0", requested={"model": "m1", "provider": "p1"})
    _finish(store, "r0")

    admitted = store.admit_request("s", "use default", request_id="r1")
    store.update_metadata("s", {"model": "later", "provider": "later-p"})

    assert admitted["execution"]["model"] == "m1"
    assert admitted["execution"]["provider"] == "p1"
    assert store.get_request("r1")["execution"]["model"] == "m1"


def test_new_model_without_provider_drops_the_previous_models_provider(store):
    store.admit_request("s", "a", request_id="r0", requested={"model": "m1", "provider": "p1"})
    _finish(store, "r0")

    admitted = store.admit_request("s", "b", request_id="r1", requested={"model": "m2"})

    assert admitted["execution"]["provider"] is None
    assert "provider" not in store.get_session("s")["metadata"]


def test_attachment_uploaded_after_admission_is_not_in_the_snapshot(store):
    store.ensure_session("s")
    store.add_attachment("s", {"attachment_id": "att_a", "sha256": "aa", "size_bytes": 1})
    admitted = store.admit_request("s", "look", request_id="r1")
    store.add_attachment("s", {"attachment_id": "att_b", "sha256": "bb", "size_bytes": 2})

    ids = [a["attachment_id"] for a in store.get_request("r1")["execution"]["attachments"]]
    assert ids == ["att_a"]
    assert admitted["execution"]["attachments"][0]["sha256"] == "aa"


def test_unknown_explicit_attachment_is_rejected(store):
    store.ensure_session("s")
    with pytest.raises(ValueError, match="Unknown attachment"):
        store.admit_request("s", "look", request_id="r1", requested={"attachment_ids": ["att_missing"]})
    assert store.get_request("r1") is None


def test_pre_upgrade_receipt_replays_by_its_original_text_digest(tmp_path):
    db = tmp_path / "gateway_sessions.sqlite3"
    store = GatewaySessionStore(db)
    store.admit_request("s", "legacy work", request_id="old")
    # Rewrite the row exactly as a schema-v5 Gateway recorded it.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE client_requests SET digest=?, digest_version=1, execution_json='{}' "
                     "WHERE request_id='old'", (input_fingerprint("legacy work"),))

    replay = store.admit_request("s", "legacy work", request_id="old",
                                 requested={"model": "anything"})

    assert replay["replayed"]
    assert replay["execution"] == {}
    assert _admitted_execution(replay) is None
    with pytest.raises(RequestConflict):
        store.admit_request("s", "different legacy work", request_id="old")


def test_v5_database_gains_snapshot_columns_without_losing_rows(tmp_path):
    db = tmp_path / "gateway_sessions.sqlite3"
    GatewaySessionStore(db).admit_request("s", "kept", request_id="keep")
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE client_requests DROP COLUMN execution_json")
        conn.execute("ALTER TABLE client_requests DROP COLUMN digest_version")
        conn.execute("UPDATE schema_meta SET value='5' WHERE key='version'")

    store = GatewaySessionStore(db)

    assert store.schema_version() >= 6
    row = store.get_request("keep")
    assert row["input_text"] == "kept"
    assert row["digest_version"] == 1 and row["execution"] == {}


def test_admitted_execution_distinguishes_snapshot_from_legacy():
    assert _admitted_execution({"digest_version": 2, "execution": {"model": "m"}}) == {"model": "m"}
    assert _admitted_execution({"digest_version": 1, "execution": {}}) is None
    assert _admitted_execution({}) is None


def test_turn_attachments_uses_snapshot_and_withholds_changed_content(store):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    store.ensure_session("s")
    store.add_attachment("s", {"attachment_id": "att_a", "sha256": "aa", "size_bytes": 1})
    store.add_attachment("s", {"attachment_id": "att_b", "sha256": "bb", "size_bytes": 1})
    fake = type("G", (), {"store": store})()
    snapshot = {"attachments": [{"attachment_id": "att_a", "sha256": "aa"},
                                {"attachment_id": "att_b", "sha256": "changed"}]}

    chosen = JaegerGatewayApp._turn_attachments(fake, "s", snapshot)

    assert [a["attachment_id"] for a in chosen] == ["att_a"]
    assert len(JaegerGatewayApp._turn_attachments(fake, "s", None)) == 2
    assert json.dumps(chosen)  # serializable for provider adapters


def test_empty_tool_grant_is_kept_and_differs_from_no_grant(store):
    admitted = store.admit_request("s", "work", request_id="g1", requested={"allowed_tools": []})
    assert admitted["execution"]["allowed_tools"] == []
    with pytest.raises(RequestConflict):
        store.admit_request("s", "work", request_id="g1")  # absent = unrestricted: different request
    _finish(store, "g1")
    other = store.admit_request("s", "work", request_id="g2")
    assert other["execution"]["allowed_tools"] is None


def test_tool_grant_rejects_blank_names(store):
    with pytest.raises(ValueError, match="allowed_tools"):
        store.admit_request("s", "work", request_id="g3", requested={"allowed_tools": ["", "x"]})


def test_display_text_is_persisted_and_frozen_separately_from_execution_text(store):
    admitted = store.admit_request(
        "s", "[directive] visible question", request_id="d1",
        requested={"display_text": "visible question"},
    )
    assert admitted["input_text"] == "[directive] visible question"
    assert admitted["execution"]["display_text"] == "visible question"
    messages = store.get_session("s")["messages"]
    assert messages[0]["content"] == "visible question"
    assert admitted["event"]["data"]["text"] == "visible question"

    replay = store.admit_request(
        "s", "[directive] visible question", request_id="d1",
        requested={"display_text": "visible question"},
    )
    assert replay["replayed"]
    with pytest.raises(RequestConflict):
        store.admit_request(
            "s", "[directive] visible question", request_id="d1",
            requested={"display_text": "other visible"},
        )


def test_missing_display_text_persists_execution_text_and_differs_from_empty(store):
    admitted = store.admit_request("s", "plain prompt", request_id="d2")
    assert admitted["execution"]["display_text"] is None
    assert store.get_session("s")["messages"][0]["content"] == "plain prompt"
    with pytest.raises(RequestConflict):
        store.admit_request(
            "s", "plain prompt", request_id="d2", requested={"display_text": ""},
        )
    _finish(store, "d2")
    empty = store.admit_request(
        "s", "plain prompt", request_id="d3", requested={"display_text": ""},
    )
    assert empty["execution"]["display_text"] == ""
    assert store.get_session("s")["messages"][-1]["content"] == ""


def test_is_subordinate_false_equals_omitted_and_true_is_identity(store):
    first = store.admit_request("s", "work", request_id="sub1")
    assert first["execution"]["is_subordinate"] is False
    replay = store.admit_request(
        "s", "work", request_id="sub1", requested={"is_subordinate": False},
    )
    assert replay["replayed"]
    with pytest.raises(RequestConflict):
        store.admit_request(
            "s", "work", request_id="sub1", requested={"is_subordinate": True},
        )
    _finish(store, "sub1")
    granted = store.admit_request(
        "s", "work", request_id="sub2", requested={"is_subordinate": True},
    )
    assert granted["execution"]["is_subordinate"] is True
    assert store.admit_request(
        "s", "work", request_id="sub2", requested={"is_subordinate": True},
    )["replayed"]
