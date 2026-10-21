import { describe, expect, it, vi } from "vitest";
import { groupRows } from "./sections";
import { loadRoster, onRosterEvent, type AgentsState } from "./agentsStore";
import { MockSource } from "../api/mock";

const row = (id: string, extra: Record<string, unknown> = {}) => ({ agent: { id, name: id, ...extra } as never, lastActivityAt: 0 });

describe("sections grouping", () => {
  it("is hidden (one flat group) while there are no sections", () => {
    expect(groupRows([row("a"), row("b", { pinned: true })], [])).toEqual([{ id: "all", rows: [row("a"), row("b", { pinned: true })] }]);
  });
  it("Pinned first (by pin_order), then each section, then Other", () => {
    const rows = [row("a", { section_id: "s1" }), row("b", { pinned: true, pin_order: 2 }), row("c"), row("d", { pinned: true, pin_order: 1 })];
    const g = groupRows(rows, [{ id: "s1", name: "Builders" }]);
    expect(g.map((x) => [x.title, x.rows.map((r) => r.agent.id)])).toEqual([["Pinned", ["d", "b"]], ["Builders", ["a"]], ["Other", ["c"]]]);
    expect(groupRows(rows, [{ id: "s1", name: "Builders" }], { pinnedGroup: false })[0].title).toBe("Builders");
  });
});

describe("roster events", () => {
  it("does not fabricate an empty section list when its supported backend fails", async () => {
    await expect(loadRoster({ agents: async () => [{ id: "owned", name: "Owned", section_id: null } as never], agentsSummary: async () => [], agentActions: { sections: async () => { throw new Error("section registry offline"); } } as never })).rejects.toThrow("section registry offline");
  });
  it("agent.unread patches in place; agent.* and section.* refresh; others ignored", () => {
    let state = { agents: [{ id: "a", name: "a", unread_count: 0 }], summaries: [], seen: {}, loading: false } as unknown as AgentsState;
    const refresh = vi.fn();
    const set = (f: (s: AgentsState) => AgentsState) => { state = f(state); };
    onRosterEvent({ event: "agent.unread", payload: { agent_id: "a", unread_count: 3 } } as never, refresh, set);
    expect(state.agents[0].unread_count).toBe(3);
    expect(refresh).not.toHaveBeenCalled();
    for (const e of ["agent.updated", "agent.created", "agent.deleted", "section.updated", "section.deleted"]) onRosterEvent({ event: e, payload: {} } as never, refresh, set);
    onRosterEvent({ event: "turn.started", payload: {} } as never, refresh, set);
    expect(refresh).toHaveBeenCalledTimes(5);
  });
  it("the mock without the spec has no global stream (the store keeps polling)", async () => {
    await expect(new MockSource().globalEvents(() => {}, new AbortController().signal)).rejects.toMatchObject({ status: 404 });
  });
});
