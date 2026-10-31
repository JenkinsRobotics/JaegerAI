"""grokbot wake: small payload, task_id, rate limit, stale-row expiry. No network or Keychain."""

import json

import pytest

from jaeger_ai.features.agent_bridge import outbox

from .test_agent_bridge_outbox import put, rows, store, worker  # noqa: F401


def payload(store, i=0):  # noqa: F811
    return json.loads(bytes(rows(store)[i]["payload"]))


def test_body_truncated_and_task_ids(store):  # noqa: F811
    put(store, body="é" * 5000)
    p = payload(store)
    assert p["truncated"] is True and len(p["body"].encode()) <= outbox.MAX_WAKE_BODY_BYTES
    assert p["task_id"] == "m1"
    put(store, id="r1", kind="result", reply_to="h9", body="done")
    p = payload(store, 1)
    assert p["task_id"] == "h9" and "truncated" not in p


def test_not_addressed_to_grokbot_is_ignored(store):  # noqa: F811
    put(store, to="ares")
    assert rows(store) == []


@pytest.mark.asyncio
async def test_rate_limit_and_dedupe(store):  # noqa: F811
    sent = []

    async def transport(url, key, body, ident):
        sent.append(ident)
        return 200

    for i in range(outbox.RATE_PER_MINUTE + 3):
        put(store, id=f"m{i}")
    put(store, id="m0")  # duplicate id: no second row
    w = worker(store, transport, clock=lambda: 1e12)
    with store._get_conn() as conn:
        conn.execute("UPDATE agent_webhook_outbox SET created_at=?, available_at=?", (1e12, 1e12))
    while await w.run_once():
        pass
    assert len(sent) == outbox.RATE_PER_MINUTE == len(set(sent))
    assert len(rows(store)) == outbox.RATE_PER_MINUTE + 3


@pytest.mark.asyncio
async def test_stale_rows_expire_not_sent(store):  # noqa: F811
    async def transport(*a):
        pytest.fail("stale row must not be sent")

    put(store)
    now = rows(store)[0]["created_at"] + outbox.MAX_AGE_SECONDS + 1
    assert not await worker(store, transport, clock=lambda: now).run_once()
    assert rows(store)[0]["status"] == "expired"
