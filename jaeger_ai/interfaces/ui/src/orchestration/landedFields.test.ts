import { describe, expect, it } from "vitest";
import type { Agent, Handoff, Task } from "../api/types";
import { agentsLive, derivedGaps } from "./adapter";
import { activityItemRow, artifactsFor, checkFor, eventRow, namesFrom, taskForHandoff } from "./feed";

const names = namesFrom([]);
const h = (over: Record<string, unknown> = {}) => ({ id: "h1", from_agent_id: "native:jaeger", to_agent_id: "native:mac", status: "completed", request_id: "r1", created_at: 1, updated_at: 2, ...over }) as Handoff;
const tasks: Task[] = [
  { task_id: "t-req", provenance: { request_id: "r1" }, state: "running" },
  { task_id: "t-back", state: "completed_verified", ...{ handoff_id: "h1" } } as Task,
  { task_id: "t-own", state: "failed" },
];

describe("landed G2–G5 fields win; stand-ins only when absent", () => {
  it("G5: handoff.task_id → task.handoff_id → request_id", () => {
    expect(taskForHandoff(h({ task_id: "t-own" }), tasks)?.task_id).toBe("t-own");
    expect(taskForHandoff(h({ task_id: null }), tasks)?.task_id).toBe("t-back");
    expect(taskForHandoff(h({ id: "h9" }), tasks)?.task_id).toBe("t-req");
  });

  it("G2: real check beats every stand-in, including failed status and task state", () => {
    expect(checkFor(h({ status: "failed", check: { state: "passed", evidence_ref: "task:t-own", checked_by: "owner:matthew", checked_at: 5 } }), tasks))
      .toMatchObject({ state: "passed", source: "gateway", checkedBy: "owner:matthew", evidence: { kind: "task" } });
    expect(checkFor(h({ check: null }), tasks)).toMatchObject({ source: "derived", state: "passed" }); // via t-back
  });

  it("G3: commit url, verified file sha, explicit worker session", () => {
    const out = artifactsFor(h({ result: { worker_session_id: "native:mac:r1", artifact_refs: [
      { kind: "commit", ref: "a".repeat(40), sha: null, title: "aaaaaaa", verified: true, url: "https://github.com/x/y/commit/" + "a".repeat(40) },
      { kind: "commit", ref: "b".repeat(40), sha: null, title: "bbbbbbb", verified: false, url: null },
      { kind: "file", ref: "out/report.md", sha: "f00d", title: "report.md", verified: true },
      { kind: "session", ref: "native:mac:r1", sha: null, title: "Worker session", verified: true },
    ] } }));
    expect(out.map((o) => [o.kind, o.copy ?? false, o.verified])).toEqual([["commit", false, true], ["commit", true, false], ["file", true, true], ["session", false, true]]);
  });

  it("G4: agent.runner beats the task's runner", () => {
    const agents = [{ id: "native:mac", name: "mac", role: "specialist", runner: "delegate:claude-code" } as Agent];
    const live = agentsLive({ agents, summaries: [], handoffs: [], tasks: [{ task_id: "t", agent_id: "native:mac", state: "running", runner: "native" }] }, derivedGaps);
    expect(live[0].runner).toBe("delegate:claude-code");
  });

  it("project.checked renders as a check row (stream and G1)", () => {
    const row = eventRow({ event: "project.checked", event_id: 77, created_at: 10, payload: { project_id: "release-1.4", result: { ok: false, status: "2 failing", checked_at: 9, checked_by: "owner:matthew" } } }, names);
    expect(row).toMatchObject({ kind: "project.checked", at: 9, action: "checked project release-1.4: 2 failing", check: { state: "failed", source: "gateway" }, needsYou: true, agentId: "native:jaeger" });
    expect(activityItemRow({ event_id: 78, kind: "project.checked", ts: 20, agent_id: "native:reviewer", data: { project_id: "p", result: { ok: true, checked_at: 20, agent_id: "native:reviewer" } } }, names))
      .toMatchObject({ action: "checked project p: passed", agentId: "native:reviewer", check: { state: "passed" } });
  });

  it("approval.request agent_id can be widget/automation; prompt is the text", () => {
    expect(eventRow({ event: "approval.request", created_at: 1, payload: { approval_id: "a", agent_id: "widget", prompt: "Allow shell?" } }, names)).toMatchObject({ agentId: "widget", action: "asked for approval: Allow shell?" });
    expect(names("automation")).toBe("An automation");
    expect(eventRow({ event: "approval.resolved", created_at: 1, payload: { approval_id: "a", approved: false } }, names)?.action).toBe("approval declined");
  });
});
