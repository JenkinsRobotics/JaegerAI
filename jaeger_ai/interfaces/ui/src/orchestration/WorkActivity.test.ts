import { describe, expect, it } from "vitest";
import { projectWork } from "./WorkActivity";
import type { OrchestrationSnapshot } from "./types";

const base: OrchestrationSnapshot = { agents: [], summaries: [], handoffs: [], tasks: [{ task_id: "mail", state: "running", goal: "Check mail access", provenance: { request_id: "req" } }] };
describe("work activity projection", () => {
  it("uses the same job row before, during and after a pending approval", () => {
    const approval = { approval_id: "a", request_id: "req", kind: "tool", prompt: "Allow access?", status: "pending" };
    expect(projectWork(base, [])).toMatchObject([{ id: "task:mail", state: "running" }]);
    expect(projectWork({ ...base, approvals: [approval] }, [])).toMatchObject([{ id: "task:mail", state: "needs_approval", bucket: "attention" }]);
    expect(projectWork({ ...base, approvals: [{ ...approval, status: "approved" }], tasks: [{ ...base.tasks[0], state: "done" }] }, [])).toMatchObject([{ id: "task:mail", state: "done", bucket: "recent", approvals: [] }]);
  });
  it("does not treat old approval events or stale running snapshots as current", () => {
    const old = { kind: "approval.requested", key: "approval:a", agentId: "jaeger", at: 1, action: "asked for approval", needsYou: true } as const;
    expect(projectWork(base, [old], true)).toMatchObject([{ state: "status_unknown", approvals: [], events: [] }]);
  });
  it("keeps routine skill reviews out of the job list", () => {
    expect(projectWork({ ...base, tasks: [{ task_id: "review", goal: "Skill review (background, no one is waiting)" }] }, [])).toEqual([]);
  });
});
