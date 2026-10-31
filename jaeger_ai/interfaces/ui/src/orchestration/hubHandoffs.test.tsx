import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityFeed } from "./ActivityFeed";
import { activityItemRow, handoffForId, handoffRows, mergeRows, namesFrom } from "./feed";
import type { ActivityItem } from "./types";

const names = namesFrom([{ id: "native:jaeger", name: "jaeger", display_name: "Jaeger", role: "lead" }]);
const W = "/Users/m/.jaeger/agent-workspaces/ares/jobs/h-ga";
// Shapes copied from live GET /v1/activity?kinds=handoff.* (hub-10f9e1ba, gateway 816adb02).
const item = (kind: "handoff.sent" | "handoff.result", over: Record<string, unknown> = {}): ActivityItem => {
  const sent = kind === "handoff.sent";
  const from = sent ? "grokbot" : "ares", to = sent ? "ares" : "grokbot";
  const data = { caller: { caller_id: from, caller_kind: "mcp" }, recipient: to, handoff_id: "h-ga", message_id: sent ? "h-ga" : "result-1", thread: "thread-1",
    title: sent ? "Build" : "Built", status: sent ? "handoff" : "done", refs: sent ? [] : [`${W}/result.md`, `${W}/codex.log`], at: sent ? 100 : 200, ...over };
  return { event_id: sent ? 1 : 2, kind, ts: sent ? 100 : 200, agent_id: to, actor_id: from, session_id: "*", needs_me: false,
    summary: sent ? "grokbot handed off h-ga to ares: Build" : "ares posted result for h-ga to grokbot [done]: Built",
    refs: { handoff_id: "h-ga", thread: "thread-1", message_id: data.message_id, caller_id: from, caller_kind: "mcp", recipient: to, task_id: null, approval_id: null, project_id: null, session_id: null } as ActivityItem["refs"], data };
};

describe("hub handoff.sent / handoff.result", () => {
  it("maps sent to a started row: sender → recipient with title", () => {
    expect(activityItemRow(item("handoff.sent"), names)).toMatchObject({ key: "handoff.started:h-ga", kind: "handoff.started", agentId: "grokbot", handoffId: "h-ga", action: "handed off to Ares: Build", at: 100 });
  });

  it("maps result to finished with artifact links, and failures to failed", () => {
    const r = activityItemRow(item("handoff.result"), names)!;
    expect(r).toMatchObject({ key: "handoff.finished:h-ga", kind: "handoff.finished", agentId: "ares", action: "finished: Built", output: { kind: "file", label: "result.md", copy: true } });
    const f = activityItemRow(item("handoff.result", { status: "failed", title: "Broke" }), names)!;
    expect(f).toMatchObject({ key: "handoff.failed:h-ga", kind: "handoff.failed", needsYou: true, check: { state: "failed" } });
    expect(activityItemRow(item("handoff.result", { status: "error" }), names)?.kind).toBe("handoff.failed");
    expect(activityItemRow(item("handoff.result", { status: "partial" }), names)).toMatchObject({ kind: "handoff.finished", statusPill: { text: "partial" } });
  });

  it("dedupes with agent.handoff rows for the same handoff_id", () => {
    const legacy = handoffRows({ id: "h-ga", from_agent_id: "grokbot", to_agent_id: "ares", task: "Build", status: "completed", created_at: 90, updated_at: 190 }, [], names);
    const merged = mergeRows(legacy, [activityItemRow(item("handoff.sent"), names)!, activityItemRow(item("handoff.result"), names)!]);
    expect(merged.map((r) => r.key).sort()).toEqual(["handoff.finished:h-ga", "handoff.started:h-ga"]);
  });

  it("groups sent+result into one details handoff with outputs", () => {
    const rows = [activityItemRow(item("handoff.sent"), names)!, activityItemRow(item("handoff.result"), names)!];
    const h = handoffForId("h-ga", [], rows)!;
    expect(h).toMatchObject({ id: "h-ga", from_agent_id: "grokbot", to_agent_id: "ares", task: "Build", status: "completed", result: { summary: "Built" } });
    expect((h.result as { artifact_refs: unknown[] }).artifact_refs).toHaveLength(2);
    expect(handoffForId("h-ga", [{ id: "h-ga", task: "Listed" }], rows)).toMatchObject({ task: "Listed", result: { artifact_refs: [{ kind: "file" }, { kind: "file" }] } });
    expect(handoffForId("nope", [], rows)).toBeUndefined();
  });

  it("shows in Handoffs and All tabs and opens details", () => {
    const onOpen = vi.fn();
    const rows = mergeRows([], [activityItemRow(item("handoff.sent"), names)!, activityItemRow(item("handoff.result"), names)!,
      { key: "task:t:running", kind: "task.updated", agentId: "ares", action: "is working on a task", at: 50 }]);
    render(<ActivityFeed rows={rows} names={names} stream="live" onOpenHandoff={onOpen} onNavigate={() => {}} now={300} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(screen.getByRole("radio", { name: "Handoffs" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/handed off to Ares: Build/)).toBeTruthy();
    fireEvent.click(screen.getAllByText("Exchange")[0]);
    expect(onOpen).toHaveBeenCalledWith("h-ga");
  });
});
