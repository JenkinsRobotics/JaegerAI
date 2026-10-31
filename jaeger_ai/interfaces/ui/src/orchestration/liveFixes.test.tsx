import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent, Handoff } from "../api/types";
import { agentsLive, derivedGaps, gatewayActivity, resetActivityProbe } from "./adapter";
import { backfill, checkFor } from "./feed";
import { ActivityFeed } from "./ActivityFeed";

const ag = (id: string, over: Partial<Agent> = {}): Agent => ({ id, name: id, display_name: id, role: "specialist", ...over });
const h = (id: string, to: string, status: string, over: Partial<Handoff> = {}): Handoff => ({ id, from_agent_id: "native:jaeger", to_agent_id: to, status, task: "t", created_at: 1, updated_at: 2, ...over });

describe("live fixes", () => {
  beforeEach(() => resetActivityProbe());

  it("#1 team = roster-visible agents plus hidden agents that did work; deleted/runtime idle stay out", () => {
    const agents = [ag("native:jaeger", { role: "lead" }), ag("native:builder"), ag("native:everyday", { hidden: true, archived: true }),
      ag("native:reviewer", { hidden: true }), ag("native:os-1", { role: "runtime" }), ag("native:gone", { deleted: true, hidden: true }), ag("tp:hermes", { kind: "third_party" })];
    const live = agentsLive({ agents, summaries: [], tasks: [], handoffs: [h("h1", "native:everyday", "completed"), h("h2", "native:gone", "failed")] }, derivedGaps);
    expect(live.map((l) => l.agent.id)).toEqual(["native:jaeger", "native:builder", "native:everyday"]);
    expect(live.find((l) => l.agent.id === "native:everyday")?.offRoster).toBe(true);
    expect(live.find((l) => l.agent.id === "native:builder")?.offRoster).toBeUndefined();
  });

  it("#2 denied / execution_unknown are failures; pending_approval needs you; completed is pending", () => {
    for (const s of ["denied", "execution_unknown", "failed", "cancelled"]) expect(checkFor(h("x", "a", s), [])).toMatchObject({ state: "failed", evidence: { href: "handoff:x" } });
    expect(checkFor(h("x", "a", "completed"), []).state).toBe("pending");
    expect(checkFor(h("x", "a", "running"), []).state).toBe("unchecked");
    const rows = backfill({ tasks: [], handoffs: [h("d", "a", "denied", { result: { summary: "Handoff denied by operator." } }), h("u", "b", "execution_unknown"), h("p", "c", "pending_approval")] }, (id) => id);
    expect(rows.find((r) => r.key === "handoff.failed:d")).toMatchObject({ action: "was denied: Handoff denied by operator.", needsYou: true, check: { state: "failed" } });
    expect(rows.find((r) => r.key === "handoff.failed:u")?.action).toBe("ended with an unknown outcome");
    expect(rows.find((r) => r.key === "handoff.started:p")).toMatchObject({ needsYou: true, action: expect.stringContaining("waiting for your approval") });
    expect(rows.some((r) => r.key === "handoff.failed:p" || r.key === "handoff.finished:p")).toBe(false);
  });

  it("#3 feed text is clamped by class, full text stays in the DOM", () => {
    const long = "x".repeat(2000);
    render(<ActivityFeed rows={[{ key: "k", kind: "handoff.finished", agentId: "a", action: `finished: ${long}`, at: 1 }]} names={(id) => id} stream="live" onOpenHandoff={() => undefined} onNavigate={() => undefined} />);
    const p = screen.getByText(/finished:/).closest("p")!;
    expect(p.closest(".jg-orch-row-body")).toBeTruthy();
    expect(p.textContent).toContain(long);
  });

  it("#5 remembers a 404 on /v1/activity for the session", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 404 }));
    const act = gatewayActivity("", f as unknown as typeof fetch);
    await act({ names: (id) => id }); await act({ names: (id) => id });
    await gatewayActivity("", f as unknown as typeof fetch)({ names: (id) => id });
    expect(f).toHaveBeenCalledTimes(1);
    const ok = vi.fn(async () => new Response(JSON.stringify({ items: [], has_more: false, next_before: null })));
    await gatewayActivity("/other", ok as unknown as typeof fetch)({ names: (id) => id });
    expect(ok).toHaveBeenCalledTimes(1);
  });
});
