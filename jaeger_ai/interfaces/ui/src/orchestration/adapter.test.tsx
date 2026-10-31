import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import { agentsLive, derivedGaps, liveAdapter } from "./adapter";
import { mockAdapter, mockSnapshotData } from "./mockOrchestration";
import { useOrchestration } from "./useOrchestration";

describe("orchestration adapter", () => {
  it("live adapter reads only EXISTING endpoints", async () => {
    const d = mockSnapshotData(1000);
    const src = { agents: vi.fn(async () => d.agents), agentsSummary: vi.fn(async () => d.summaries), handoffs: vi.fn(async () => d.handoffs), tasks: vi.fn(async () => d.tasks), handoffExchange: vi.fn() } as unknown as JaegerSource;
    const a = liveAdapter(src);
    expect(a.follow).toBeUndefined();
    expect((await a.snapshot()).agents).toHaveLength(5);
    expect(a.gaps.kind).toBe("derived");
  });

  it("orders lead, busy, idle and derives runner from active task (pre-G4)", () => {
    const live = agentsLive(mockSnapshotData(1000), derivedGaps);
    expect(live[0].agent.id).toBe("native:jaeger");
    expect(live.find((r) => r.agent.id === "native:mac")).toMatchObject({ status: "working", runner: "delegate:codex", currentTask: { eta: "12m" } });
    expect(live.at(-1)?.status).toBe("idle");
  });

  it("hook backfills, applies stream frames once, and surfaces errors", async () => {
    const adapter = mockAdapter();
    const { result } = renderHook(() => useOrchestration(adapter));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await waitFor(() => expect(result.current.stream).toBe("live"));
    expect(result.current.rows.some((r) => r.kind === "approval.requested")).toBe(true);
    expect(result.current.live.find((r) => r.agent.id === "native:reviewer")?.status).toBe("checking");
    const failing = mockAdapter({ fail: true });
    const bad = renderHook(() => useOrchestration(failing));
    await waitFor(() => expect(bad.result.current.status).toBe("error"));
    expect(bad.result.current.error).toBe("Gateway unreachable");
    act(() => bad.result.current.retry());
  });
});
