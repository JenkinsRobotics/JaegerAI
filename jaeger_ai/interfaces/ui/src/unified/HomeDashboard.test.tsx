import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { JaegerSource } from "../api/source";
import type { AgentsState } from "../agents/agentsStore";
import { HomeDashboard } from "./HomeDashboard";
import { ToastProvider } from "./ui";

vi.mock("./webui", () => ({
  getJson: vi.fn(async (path: string) => path === "/v1/jobs/runner" ? { service: "runner", health: "ok", jobs: [] } : path === "/v1/system/status" ? { gateway: { ok: true, latency_ms: 12 }, tailscale: { available: false } } : { now: {}, history: [] }),
  sendJson: vi.fn(),
}));

afterEach(() => { document.body.innerHTML = ""; localStorage.clear(); });

it("renders Control Center groups as widget cards and preserves actions", async () => {
  const onNavigate = vi.fn();
  const save = vi.fn(async () => ({ preferences: { enabled: false, revision: 2, muted_agent_ids: [] } }));
  const source = {
    sessions: vi.fn(async () => []), tasks: vi.fn(async () => []),
    notifications: { read: vi.fn(async () => ({ preferences: { enabled: true, revision: 1, muted_agent_ids: [] } })), save },
  } as unknown as JaegerSource;
  const store: AgentsState = { agents: [], summaries: [], seen: {}, loading: false };
  const { container } = render(<ToastProvider><HomeDashboard source={source} store={store} onNavigate={onNavigate} /></ToastProvider>);

  const controlCenter = screen.getByRole("region", { name: "Control Center" });
  expect(controlCenter.querySelectorAll(".jg-widget-card[data-state='ready']")).toHaveLength(8);
  expect(screen.getByRole("region", { name: "Gateway" }).parentElement).toHaveAttribute("title", "Read-only: GET /health");

  fireEvent.click(screen.getByRole("button", { name: "Voice Voice settings" }));
  expect(onNavigate).toHaveBeenCalledWith("/settings/voice");
  fireEvent.click(screen.getByRole("button", { name: "New agent From a character" }));
  expect(onNavigate).toHaveBeenCalledWith("/agents/characters");

  const focus = await screen.findByRole("button", { name: "Focus Off" });
  expect(controlCenter.querySelectorAll(".jg-widget-card__actions button")).toHaveLength(5);
  expect(focus).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(focus);
  await waitFor(() => expect(save).toHaveBeenCalledWith({ expected_revision: 1, enabled: false, muted_agent_ids: [] }));
  expect(container.querySelector(".jg-cc__tile[data-pressed='true'] .jg-widget-card__status")?.textContent).toBe("On · notifications paused");
});
