import { describe, expect, it } from "vitest";
import { isProbeSession } from "./ProcessView";

const row = (title: string, metadata?: Record<string, unknown>) => ({ session_id: "x", title, metadata } as never);

describe("probe sessions are gated out of the Process view list", () => {
  it("hides demo, audit and check sessions and anything marked probe", () => {
    for (const t of ["Process view demo", "Events audit observation", "Chat check", "Cleanup check · 3", "Process check · redesign"]) expect(isProbeSession(row(t))).toBe(true);
    expect(isProbeSession(row("Plan the garage build", { probe: true }))).toBe(true);
  });
  it("keeps real sessions", () => {
    expect(isProbeSession(row("Plan the garage build"))).toBe(false);
    expect(isProbeSession(row("Chat about checks"))).toBe(false);
  });
});
