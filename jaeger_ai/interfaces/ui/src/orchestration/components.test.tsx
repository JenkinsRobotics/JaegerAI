import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { mockAdapter } from "./mockOrchestration";
import { OrchestrationPanes } from "./OrchestrationPanes";
import { CheckBadge } from "./CheckBadge";

describe("orchestration panes", () => {
  it("renders lead, team, feed, and opens a handoff inspector", async () => {
    const nav = vi.fn();
    render(<StrictMode><OrchestrationPanes adapter={mockAdapter()} onNavigate={nav} /></StrictMode>);
    await screen.findByLabelText("Lead agent");
    expect(screen.getByText(/Coordinating/)).toBeTruthy();
    expect(screen.getByText("via codex")).toBeTruthy();
    await screen.findByText("Live");
    fireEvent.click(screen.getAllByRole("button", { name: /Exchange/ })[0]);
    const insp = await screen.findByLabelText("Handoff details");
    await waitFor(() => expect(insp.textContent).not.toMatch(/Loading/));
    fireEvent.click(within(insp).getAllByRole("button", { name: /^Task:/ })[0]);
    expect(nav).toHaveBeenCalledWith(expect.stringMatching(/^\/work\/tasks\?task=/));
  });

  it("filters to needs-you rows", async () => {
    render(<OrchestrationPanes adapter={mockAdapter()} onNavigate={() => undefined} />);
    await screen.findByText("Live");
    fireEvent.click(screen.getByRole("radio", { name: "Needs you" }));
    for (const row of document.querySelectorAll(".jg-orch-row")) expect(row.getAttribute("data-needs")).toBe("true");
  });

  it("shows an error state, not fake data", async () => {
    render(<OrchestrationPanes adapter={mockAdapter({ fail: true })} onNavigate={() => undefined} />);
    expect(await screen.findByText(/Gateway unreachable/)).toBeTruthy();
  });

  it("labels derived checks", () => {
    render(<CheckBadge check={{ state: "passed", source: "derived" }} />);
    expect(screen.getByText("Checked · task")).toBeTruthy();
  });

  it("inspector picks up agent.handoff.checked without a refetch", async () => {
    render(<OrchestrationPanes adapter={mockAdapter()} onNavigate={() => undefined} />);
    await screen.findByText("Live");
    fireEvent.click(screen.getAllByRole("button", { name: /Exchange/ }).find((b) => b.closest(".jg-orch-row")?.textContent?.includes("handed off to Mac App"))!);
    const insp = await screen.findByLabelText("Handoff details");
    await waitFor(() => expect(within(insp).getByText(/^Checking/)).toBeTruthy());
    expect(within(insp).getByText("waiting on CI")).toBeTruthy();
  });

  it("keeps the feed when G1 history fails, with a notice", async () => {
    const base = mockAdapter();
    const adapter = { ...base, gaps: { ...base.gaps, activity: async () => { throw new Error("activity 500"); } } };
    render(<OrchestrationPanes adapter={adapter} onNavigate={() => undefined} />);
    expect(await screen.findByText(/Older activity couldn't load \(activity 500\)/)).toBeTruthy();
    expect(screen.getByLabelText("Lead agent")).toBeTruthy();
  });
});
