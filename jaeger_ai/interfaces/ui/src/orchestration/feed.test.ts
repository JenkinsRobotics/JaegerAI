import { describe, expect, it } from "vitest";
import type { GatewayEvent, Handoff, Task } from "../api/types";
import { artifactsFor, backfill, checkFor, eventRow, mergeRows, relativeTime, taskForHandoff } from "./feed";

const names = (id: string) => ({ "native:jaeger": "Jaeger", "native:mac": "Mac App" } as Record<string, string>)[id] ?? id;
const h = (over: Partial<Handoff> = {}): Handoff => ({ id: "h1", from_agent_id: "native:jaeger", to_agent_id: "native:mac", task: "fix build", status: "running", request_id: "r1", created_at: 100, updated_at: 200, ...over });
const t = (over: Partial<Task> = {}): Task => ({ task_id: "t1", goal: "fix build", state: "running", agent_id: "native:mac", updated_at: 150, provenance: { request_id: "r1" }, ...over });

describe("orchestration feed", () => {
  it("links a handoff to its task by request_id (pre-G5) or task_id (G5)", () => {
    expect(taskForHandoff(h(), [t()])?.task_id).toBe("t1");
    expect(taskForHandoff(h({ request_id: undefined }), [t()])).toBeUndefined();
    expect(taskForHandoff({ ...h(), task_id: "t2" } as Handoff, [t(), t({ task_id: "t2" })])?.task_id).toBe("t2");
  });

  it("derives checks from task state and never claims passed without proof", () => {
    expect(checkFor(h(), []).state).toBe("unchecked");
    expect(checkFor(h(), [t({ state: "done" })]).state).toBe("pending");
    expect(checkFor(h(), [t({ state: "completed_verified" })])).toMatchObject({ state: "passed", source: "derived", evidence: { kind: "task" } });
    expect(checkFor(h(), [t({ state: "failed" })]).state).toBe("failed");
    expect(checkFor({ ...h(), check: { state: "passed", evidence_ref: "https://ci/1" } } as Handoff, []).source).toBe("gateway");
  });

  it("maps a finished handoff to start + finish rows with artifacts", () => {
    const rows = backfill({ handoffs: [h({ status: "completed", result: { summary: "green", artifact_refs: [{ kind: "commit", ref: "abcdef1234" }] } as Handoff["result"] })], tasks: [] }, names);
    expect(rows.map((r) => r.kind)).toEqual(["handoff.finished", "handoff.started"]);
    expect(rows[0]).toMatchObject({ agentId: "native:mac", action: "finished: green", output: { kind: "commit", label: "abcdef12" } });
    expect(rows[1].action).toBe("handed off to Mac App: fix build");
  });

  it("drops non-https url artifacts", () => {
    expect(artifactsFor(h({ result: { artifact_refs: [{ kind: "url", ref: "javascript:alert(1)" }] } as Handoff["result"] }))).toEqual([]);
  });

  it("maps captured live frames", () => {
    const frames: GatewayEvent[] = [
      { event: "agent.handoff", event_id: 9, created_at: 300, payload: { handoff: h() } },
      { event: "agent.handoff.finished", event_id: 10, created_at: 400, payload: { handoff: h({ status: "failed", result: { summary: "tests red" } }) } },
      { event: "task.updated", event_id: 11, created_at: 410, payload: { task: t({ state: "needs_owner" }) } },
      { event: "approval.request", event_id: 12, created_at: 420, session_id: "s1", payload: { approval_id: "a1", tool: "shell" } },
      { event: "jaeger.state", event_id: 13, payload: {} },
    ];
    const rows = frames.map((f) => eventRow(f, names));
    expect(rows[0]).toMatchObject({ kind: "handoff.started", at: 300 });
    expect(rows[1]).toMatchObject({ kind: "handoff.failed", needsYou: true, action: "couldn't finish: tests red" });
    expect(rows[2]).toMatchObject({ kind: "task.updated", needsYou: true });
    expect(rows[3]).toMatchObject({ kind: "approval.requested", needsYou: true });
    expect(rows[4]).toBeNull();
  });

  it("merges by key newest-first", () => {
    const a = eventRow({ event: "agent.handoff", created_at: 1, payload: { handoff: h() } }, names)!;
    const b = { ...a, at: 5 };
    expect(mergeRows([a], [b])).toHaveLength(1);
    expect(mergeRows([a], [b])[0].at).toBe(5);
    expect(relativeTime(100, 130)).toBe("just now");
    expect(relativeTime(0, 7200)).toBe("2h");
  });
});
