import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { AgentsHome } from "./AgentsHome";
import { ToastProvider } from "./ui";

vi.mock("../orchestration/AgentsActivityPage", () => ({ AgentsActivityPage: () => null }));

it("adds a role, opens its profile, and refreshes the primary badge without navigating", async () => {
  const lead: Agent = { id: "native:jaeger", name: "Jaeger", role: "lead", primary: true };
  const producer: Agent = { id: "native:channel-producer", name: "Channel Producer", role: "specialist", ui_actions: { primary: true }, metadata: { specialty: "Prepare episode briefs" } };
  let catalog = [lead];
  const createAgent = vi.fn(async () => { catalog = [...catalog, producer]; return producer; });
  const setPrimary = vi.fn(async (next: string, previous: string) => {
    expect(previous).toBe(lead.id);
    catalog = catalog.map(a => ({ ...a, primary: a.id === next }));
  });
  const onNavigate = vi.fn();
  const source = { createAgent, agentActions: { setPrimary }, sessions: async () => [] } as unknown as JaegerSource;
  function Harness() {
    const [agents, setAgents] = useState(catalog);
    return <ToastProvider><AgentsHome source={source} agents={agents} refresh={() => setAgents(catalog)} onNavigate={onNavigate} /></ToastProvider>;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Add agent" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Channel Producer" } });
  fireEvent.change(screen.getByLabelText("What job should this agent own?"), { target: { value: "Prepare episode briefs" } });
  fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
  const profile = await screen.findByRole("dialog", { name: "Channel Producer profile" });
  expect(createAgent).toHaveBeenCalledWith(expect.objectContaining({ display_name: "Channel Producer", metadata: { specialty: "Prepare episode briefs" } }));
  fireEvent.click(within(profile).getByRole("button", { name: "Set as primary" }));
  expect(await within(profile).findByText("Primary agent")).toBeTruthy();
  expect(setPrimary).toHaveBeenCalledWith(producer.id, lead.id);
  const team = within(screen.getByRole("region", { name: "Your team" }));
  expect(team.getByRole("button", { name: /Channel Producer.*Primary agent/ })).toBeTruthy();
  expect(team.getByRole("button", { name: /Jaeger.*General assistant/ })).toBeTruthy();
  expect(onNavigate).not.toHaveBeenCalled();
});

it("keeps archived agents off the team until restored from the same profile layout", async () => {
  const lead: Agent = { id: "native:jaeger", name: "Jaeger", role: "lead", primary: true };
  const editor: Agent = { id: "native:editor", name: "Editor", role: "specialist", archived: true, ui_actions: { hide: true, primary: true } };
  let catalog = [lead, editor];
  const patchAgent = vi.fn(async (_id: string, patch: { archived: boolean }) => {
    catalog = [lead, { ...editor, archived: patch.archived }];
  });
  const source = { agentActions: { patchAgent, setPrimary: vi.fn() }, sessions: async () => [] } as unknown as JaegerSource;
  function Harness() {
    const [agents, setAgents] = useState(catalog);
    return <ToastProvider><AgentsHome source={source} agents={agents} refresh={() => setAgents(catalog)} onNavigate={vi.fn()} /></ToastProvider>;
  }
  render(<Harness />);
  const team = within(screen.getByRole("region", { name: "Your team" }));
  const active = within(team.getByRole("list", { name: "Active agents" }));
  expect(active.queryByRole("button", { name: /Editor/ })).toBeNull();
  fireEvent.click(team.getByText("Team options"));
  fireEvent.click(team.getByRole("button", { name: /Editor.*Archived/ }));
  const profile = screen.getByRole("dialog", { name: "Editor profile" });
  expect(within(profile).queryByRole("button", { name: "Set as primary" })).toBeNull();
  fireEvent.click(within(profile).getByRole("button", { name: "Restore" }));
  expect(await within(profile).findByRole("button", { name: "Set as primary" })).toBeTruthy();
  expect(patchAgent).toHaveBeenCalledWith(editor.id, { archived: false });
  expect(active.getByRole("button", { name: /Editor.*Team agent/ })).toBeTruthy();
});
