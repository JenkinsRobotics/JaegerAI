import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent, Handoff } from "../api/types";
import { agentsLive, derivedGaps, gatewayActivity, resetActivityProbe } from "./adapter";
import { ActivityFeed } from "./ActivityFeed";
import { activityItemRow, backfill, callerName, eventRow, namesFrom } from "./feed";
import { mockAdapter } from "./mockOrchestration";
import { OrchestrationPanes } from "./OrchestrationPanes";

const names = namesFrom([{ id: "native:jaeger", name: "jaeger", display_name: "Jaeger", role: "lead" }]);
const caller = (over: Record<string, unknown> = {}) => ({ caller_id: "codex", caller_kind: "mcp", session_id: "codex:bridge-t1", request_id: "rq", status: "completed", goal_id: "g-1", thread: "t1", agent_id: "native:jaeger", ...over });

describe("MCP/A2A caller goals", () => {
  beforeEach(() => resetActivityProbe());

  it("renders turn.* caller rows as goals from that app, with status and a link", () => {
    const row = activityItemRow({ event_id: 5, kind: "turn.finish", ts: 10, agent_id: "native:jaeger", actor_id: "codex", data: { caller: caller() } }, names)!;
    expect(row).toMatchObject({ kind: "caller.goal", agentId: "codex", callerId: "codex", action: "→ Jaeger goal g-1 (t1)", statusPill: { text: "Completed", tone: "ok" }, output: { href: "/chat?agent=native%3Ajaeger" } });
    expect(names("codex")).toBe("Codex");
    const failed = eventRow({ event: "turn.failed", created_at: 3, payload: { error: "quota", caller: caller({ caller_id: "partner-bot", caller_kind: "a2a", status: "failed" }) } }, names)!;
    expect(failed).toMatchObject({ action: "(A2A) → Jaeger goal g-1 (t1): quota", statusPill: { tone: "bad" }, needsYou: true });
    expect(eventRow({ event: "turn.start", created_at: 1, payload: { caller: caller({ status: undefined }) } }, names)?.statusPill?.text).toBe("Running");
    expect(eventRow({ event: "turn.unknown", created_at: 1, payload: { caller: caller({ status: undefined }) } }, names)?.statusPill?.text).toBe("Outcome unknown");
  });

  it("ignores owner chat turns (no data.caller)", () => {
    expect(eventRow({ event: "turn.finish", created_at: 1, payload: { text: "hi" } }, names)).toBeNull();
    expect(callerName("agent:partner-bot", "a2a")).toBe("Partner-bot (A2A)");
  });

  it("sends agent_id to /v1/activity", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ items: [], has_more: false, next_before: null })));
    await gatewayActivity("", f as unknown as typeof fetch)({ agentId: "codex", names });
    expect(f).toHaveBeenCalledWith("/v1/activity?limit=50&agent_id=codex", expect.anything());
  });

  it("feed caller filter lists callers and filters rows", () => {
    const onCaller = vi.fn();
    const rows = [
      activityItemRow({ event_id: 1, kind: "turn.finish", ts: 2, agent_id: "native:jaeger", data: { caller: caller() } }, names)!,
      { key: "x", kind: "task.updated" as const, agentId: "native:jaeger", action: "did x", at: 1 },
    ];
    const { rerender } = render(<ActivityFeed rows={rows} names={names} stream="live" onOpenHandoff={() => undefined} onNavigate={() => undefined} onCaller={onCaller} />);
    fireEvent.change(screen.getByLabelText("From app"), { target: { value: "codex" } });
    expect(onCaller).toHaveBeenCalledWith("codex");
    rerender(<ActivityFeed rows={rows} names={names} stream="live" onOpenHandoff={() => undefined} onNavigate={() => undefined} onCaller={onCaller} caller="codex" />);
    expect(document.querySelectorAll(".jg-orch-row")).toHaveLength(1);
  });

  it("initial ?agent_id caller filters the panes and the G1 request", async () => {
    const adapter = mockAdapter();
    const spy = vi.spyOn(adapter.gaps, "activity");
    render(<OrchestrationPanes adapter={adapter} onNavigate={() => undefined} initialCaller="codex" />);
    await screen.findByText(/goal g-17/);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({ agentId: "codex" })));
    expect(screen.queryByText(/goal g-9/)).toBeNull();
    expect((screen.getByLabelText("From app") as HTMLSelectElement).value).toBe("codex");
  });

  it("team excludes deleted agents while their feed rows stay (supervisor rule)", () => {
    const agents: Agent[] = [{ id: "native:jaeger", name: "jaeger", role: "lead" }, { id: "native:everyday", name: "everyday", role: "specialist", hidden: true, deleted: true }];
    const handoffs: Handoff[] = [{ id: "h", from_agent_id: "native:jaeger", to_agent_id: "native:everyday", status: "completed", created_at: 1, updated_at: 2 }];
    expect(agentsLive({ agents, summaries: [], tasks: [], handoffs }, derivedGaps).map((l) => l.agent.id)).toEqual(["native:jaeger"]);
    expect(backfill({ handoffs, tasks: [] }, namesFrom(agents)).some((r) => r.agentId === "native:everyday")).toBe(true);
  });
});
