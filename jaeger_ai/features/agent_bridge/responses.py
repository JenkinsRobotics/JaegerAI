"""Deliver canonical outcomes as data; never admit work or resolve approvals."""

import hashlib

from .outcomes import project_goal
from .service import AgentMessages, enabled

TERMINAL = frozenset({"completed", "failed", "cancelled", "execution_unknown"})


def deliver_responses(gateway, *, request_id=None, caller=None):
    """Idempotent recovery from the durable admission/receipt, including crash gaps.

    Only explicitly linked goals qualify. Historical inert inbox entries and
    unlinked unknown receipts are never enrolled, retried or executed.
    """
    enabled()
    with gateway.store._get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_goals WHERE source_message_id IS NOT NULL"
            + (" AND request_id=?" if request_id else "")
            + (" AND caller=?" if caller else ""),
            (*((request_id,) if request_id else ()), *((caller,) if caller else ())),
        ).fetchall()
    service = AgentMessages(gateway.store)
    for row in rows:
        receipt = gateway.store.get_request(row["request_id"])
        if not receipt or receipt.get("status") not in TERMINAL:
            continue
        # Freeze to the canonical receipt, not a changing verifier projection.
        # Successful model output alone never claims verified tool effects.
        outcome = project_goal(row["id"], row["thread"], receipt)
        status = outcome["status"]
        unknown = status == "execution_unknown"
        body = ("Outcome unknown; no retry started." if unknown else outcome["result"]["output"])
        body = body.encode("utf-8")[:12000].decode("utf-8", errors="ignore")
        identity = f"{row['caller']}:{row['id']}:{receipt['status']}"
        service.send("jaegerd", {
            "id": "goal-response-" + hashlib.sha256(identity.encode()).hexdigest(),
            "thread": row["thread"], "to": row["caller"],
            "kind": "answer" if receipt["status"] == "completed" else "status",
            "title": "Goal response", "body": body,
            "status_line": status, "reply_to": row["source_message_id"],
        }, correlation={
            "goal_id": row["id"], "request_id": row["request_id"],
            "session_id": row["session"],
            **{name: receipt["result"][name] for name in ("task_id", "handoff_id")
               if isinstance((receipt.get("result") or {}).get(name), str)},
        })
