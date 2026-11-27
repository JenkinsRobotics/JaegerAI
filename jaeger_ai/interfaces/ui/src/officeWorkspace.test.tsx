import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OfficeWorkspace, buildJaegerStudioFloorplan, findPath } from "@jaeger/ui-office";

describe("@jaeger/ui-office Virtual Office", () => {
  it("computes walkable BFS paths between Command Desk and Coffee Lounge", () => {
    const fp = buildJaegerStudioFloorplan();
    const path = findPath(11, 4, 19, 10, fp.tiles, fp.blockedTiles);
    expect(path.length).toBeGreaterThan(4);
    expect(path[path.length - 1]).toEqual({ col: 19, row: 10 });
  });

  it("renders live agents, subagents, budget, and lets operator inspect an agent", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          agents: [
            {
              id: "jaeger",
              name: "Jaeger",
              role: "Primary Autonomous Mind",
              kind: "primary",
              zone: "command",
              activity: "typing",
              statusLabel: "Running edit_file",
              currentTool: "edit_file",
              currentTask: "Building Virtual Office",
              model: "mistral-large-4:cloud",
              accentColor: "#38bdf8",
              paletteIndex: 0,
            },
            {
              id: "sub_1",
              name: "Researcher-1",
              role: "Subagent (researcher)",
              kind: "subagent",
              zone: "engineering",
              activity: "reading",
              statusLabel: "Searching docs",
              currentTool: "web_search",
              currentTask: "Compare MIT pixel office donors",
              accentColor: "#2dd4bf",
              paletteIndex: 4,
            },
          ],
          activityFeed: [
            { id: "ev1", timestamp: 1700000000, agentName: "Jaeger", kind: "tool", summary: "Ran edit_file cleanly" },
          ],
          budgets: { daily_cap_usd: 25, daily_spent_usd: 1.5, daily_remaining_usd: 23.5 },
          pendingApprovals: 1,
          activeSubagents: 1,
          estopActive: false,
          autonomyEnabled: true,
          minecraftConnected: true,
          droidAwake: true,
          updatedAt: 1700000000,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<OfficeWorkspace baseUrl="" />);

    await waitFor(() => {
      expect(screen.getByText("Jaeger Virtual Office")).toBeTruthy();
      expect(screen.getByText("Building Virtual Office")).toBeTruthy();
      expect(screen.getByText(/1 live subagent/)).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Researcher-1" }));
    expect(screen.getByText("Compare MIT pixel office donors")).toBeTruthy();
    fetchSpy.mockRestore();
  });
});
