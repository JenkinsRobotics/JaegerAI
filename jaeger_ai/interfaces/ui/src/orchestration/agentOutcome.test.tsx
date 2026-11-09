import { readFileSync } from "node:fs";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ActivityFeed } from "./ActivityFeed";
import { HandoffInspector } from "./HandoffInspector";
import { checkFor, eventRow, handoffForId } from "./feed";
import { derivedGaps, type OrchestrationAdapter } from "./adapter";
import type { GatewayEvent } from "../api/types";

afterEach(cleanup);
const statuses = ["done", "failed", "timeout", "error", "cancelled", "execution_unknown", "partial", "", "unsupported"];
const fixtures = statuses.map(status => ({ event: "handoff.result", payload: {
  caller: { caller_id: "ares", caller_kind: "mcp" }, recipient: "grokbot", handoff_id: "task-1",
  status, title: "Result report", refs: ["/synthetic/result.txt"], at: 100,
} }));
// Qualification can replay the actual Python worker/MCP/HTTP activity payloads.
const captured = process.env.JAEGER_AGENT_OUTCOME_EVENTS
  ? readFileSync(process.env.JAEGER_AGENT_OUTCOME_EVENTS, "utf8").trim().split("\n").map(line => JSON.parse(line)) : [];

describe("peer execution outcome and independent result check", () => {
  for (const event of [...fixtures, ...captured]) it(`renders reported ${event.payload.status || "unknown"}`, async () => {
    const row = eventRow(event as GatewayEvent, id => id)!;
    const handoff = handoffForId(event.payload.handoff_id, [], [row])!;
    const adapter: OrchestrationAdapter = { gaps: derivedGaps, snapshot: async () => ({ agents: [], summaries: [], handoffs: [], tasks: [] }), exchange: async () => ({ summary: "Peer report body" }) };
    render(<><ActivityFeed rows={[row]} names={id => id} stream="live" onOpenHandoff={() => {}} onNavigate={() => {}} /><HandoffInspector handoff={handoff} tasks={[]} adapter={adapter} names={id => id} onNavigate={() => {}} onClose={() => {}} /></>);
    await screen.findByText("Peer report body");
    expect(row.check?.state).toBe("pending");
    expect(checkFor(handoff, []).state).toBe("pending");
    if (event.payload.status === "done") {
      expect(handoff.status).toBe("completed");
      expect(row.kind).toBe("handoff.finished");
    } else {
      expect(handoff.status).not.toBe("completed");
      expect(row.kind).toBe("handoff.failed");
      expect(row.action).not.toMatch(/^finished/);
      expect(row.needsYou).toBe(true);
    }
    const statusLabel = screen.getByText("Status", { selector: "dt" });
    expect(statusLabel.nextElementSibling?.textContent).toBe(handoff.status);
    expect(screen.queryByText("Passed", { exact: true })).toBeNull();
  });
});
