"""M2 live evidence script (read-only against prod state; uses a temp instance root).

Proves, with observable output:
 1. An unauthorized action (git_push by an outside caller) is DENY/REQUIRE_APPROVAL
    BEFORE it runs, with the kernel trace as the log entry.
 2. An authorized Tier 1 action (local read) is ALLOW.
 3. A durable task is owned by one owner; a second owner is blocked (TaskConflict).
 4. An effect is executed and verified, and a deliberately failing effect is
    recorded as failed, not success.

Run: PYTHONPATH=. python3 dev/scripts/m2_evidence.py
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="M2-EVIDENCE %(levelname)s %(message)s")
log = logging.getLogger("m2")

from jaeger_ai.core.authority.kernel import PolicyKernel, ProposedAction

tmp = Path(tempfile.mkdtemp(prefix="m2-evidence-"))

kernel = PolicyKernel()

# ── 1. Unauthorized action blocked BEFORE it runs ──────────────────────────
trace: list[dict] = []
push = ProposedAction(
    tool_name="git_push",
    arguments={"remote": "origin", "branch": "master"},
    session_id="mcp:demo",
    actor="mcp:outside-caller",
    tier="privileged",
)
d_push = kernel.evaluate(push, dry_run=True, instance_root=tmp, trace=trace)
log.info("UNAUTHORIZED git_push by mcp caller -> %s (%s) policy=%s decision_id=%s",
         d_push.decision.value, d_push.reason, d_push.policy_name, d_push.decision_id)
assert d_push.decision.value in ("deny", "require_approval"), d_push
assert not d_push.is_authorized, "push must not be authorized"

# ── 2. Authorized Tier 1 action allowed ────────────────────────────────────
trace2: list[dict] = []
read = ProposedAction(
    tool_name="read_file",
    arguments={"path": "/etc/hostname"},
    session_id="owner:cli",
    actor="owner:cli",
    tier="read_only",
)
d_read = kernel.evaluate(read, dry_run=True, instance_root=tmp, trace=trace2)
log.info("AUTHORIZED read_file by owner -> %s (%s)", d_read.decision.value, d_read.reason)
assert d_read.is_authorized, d_read

# ── 3. Durable task ownership: second owner blocked ────────────────────────
from jaeger_ai.core.tasks.models import DurableTask
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore, TaskConflict

store = SqliteDurableTaskStore(tmp / "tasks.db")
t = DurableTask(task_id="m2-demo-task", owning_agent="agent:jaeger", goal="M2 demo")
store.admit_task(t)
store.update_task("m2-demo-task", lambda x: setattr(x, "owning_agent", "agent:ares"))
try:
    store.admit_task(DurableTask(task_id="m2-demo-task", owning_agent="agent:muse", goal="conflict"))
    log.error("CONFLICT NOT BLOCKED — task admitted twice")
    raise SystemExit("fail: conflicting ownership not blocked")
except TaskConflict as e:
    log.info("SECOND OWNER BLOCKED -> TaskConflict: %s", e)
# survives "restart" (new store handle, same DB)
store2 = SqliteDurableTaskStore(tmp / "tasks.db")
again = store2.get_task("m2-demo-task")
log.info("TASK SURVIVES RESTART -> owning_agent=%s state=%s", again.owning_agent, again.state)
assert again.owning_agent == "agent:ares"

# ── 4. Effect executed+verified; failing effect recorded as failed ─────────
from jaeger_ai.core.entity.verification import VerificationContract, VerificationStatus

target = tmp / "ok.txt"
target.write_text("data")
r_ok = VerificationContract.verify_filesystem_write(target, expected_content="data", objective=f"write {target}")
log.info("AUTHORIZED EFFECT VERIFIED -> status=%s evidence=%s", r_ok.status.value, r_ok.evidence)
assert r_ok.status == VerificationStatus.OBJECTIVE_VERIFIED, r_ok.status
# deliberately failing task: file absent -> must be reported failed, not success
r_bad = VerificationContract.verify_filesystem_write(tmp / "missing.txt", objective="write missing.txt")
log.info("FAILING EFFECT REPORTED AS -> status=%s evidence=%s (must not be OBJECTIVE_VERIFIED)", r_bad.status.value, r_bad.evidence)
assert r_bad.status != VerificationStatus.OBJECTIVE_VERIFIED, r_bad.status

log.info("M2 EVIDENCE COMPLETE: block-before-run ok, allow ok, conflict blocked ok, restart durability ok, failure reported ok")
