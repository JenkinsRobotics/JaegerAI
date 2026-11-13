import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TeamView } from "./TeamView";
import type { CollaborationMode, CollaborationSnapshot, TeamApi, TeamSnapshot } from "../api/team";

const agent = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name: id, display_name: name, role: "specialist", team: "pilot", description: `${name} role`, persona: "", skills: ["s"], tools: ["read_file"],
  avatar: { seed: id, url: null }, pack: "character/v1", status: "idle", activity: null, ...extra,
});
const snap: TeamSnapshot = {
  agents: [agent("native:a", "Engineer"), agent("native:b", "Design", { status: "working" })],
  rooms: [{ session_id: "room-1", title: "Review room", members: ["native:a", "native:b"], probe: false },
          { session_id: "room-2", title: "Probe room", members: ["native:a", "native:b"], probe: true }],
  handoffs: [{ id: "h1", from_agent_id: "native:a", to_agent_id: "native:b", status: "completed", task: "Review the Team page" },
             { id: "room:room-1:2:native:a", kind: "room", from_agent_id: "native:b", to_agent_id: "native:a", status: "not_taken",
               task: "Design → Engineer in “Review room”", session_id: "room-1", room_title: "Review room" }],
  limits: {},
};
const team: TeamApi = {
  snapshot: async () => snap,
  room: async (id) => ({ room: { session_id: id, title: "Review room", members: ["native:a", "native:b"], probe: false },
    messages: [{ id: 1, role: "user", kind: "room_message", content: "Please review", sender_agent_id: null },
               { id: 2, role: "assistant", kind: "room_reply", content: "Two findings.", sender_agent_id: "native:b" }] }),
  createRoom: async () => ({ session_id: "room-3", title: "x", members: [] }),
  say: async () => ({ request_id: "room_x", session_id: "room-1" }),
};

describe("Team page", () => {
  it("shows the roster, hand-offs and the room transcript; hides test rooms", async () => {
    render(<TeamView source={{ team } as never} />);
    expect(await screen.findByRole("heading", { name: "Engineer" })).toBeTruthy();
    expect(screen.getByText("2 agents · 1 working · 1 rooms")).toBeTruthy();
    expect(screen.getByText("Review the Team page")).toBeTruthy();
    expect(screen.getByText("Design → Engineer in “Review room”")).toBeTruthy();
    expect(screen.getByText("not taken")).toBeTruthy();
    expect(screen.getByText("room")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Two findings.")).toBeTruthy());
    expect(screen.queryByRole("option", { name: "Probe room" })).toBeNull();
  });
  it("is Inner workings in One mind: helper profiles and delegations, no rooms; the mode switch saves", async () => {
    let mode: CollaborationMode = "one_mind";
    const collab = (): CollaborationSnapshot => ({ mode, label: mode, description: "", default: "one_mind", limits: {},
      options: [{ id: "one_mind", label: "One mind", description: "one" }, { id: "team", label: "Team", description: "team" }, { id: "auto", label: "Auto", description: "auto" }] });
    const lead = agent("native:jaeger", "Jaeger", { role: "lead", team: null });
    const oneMind: TeamApi = {
      ...team,
      snapshot: async () => ({ ...snap, mode, agents: [lead, ...snap.agents],
        handoffs: [{ id: "d1", kind: "delegate", from_agent_id: "native:jaeger", to_agent_id: "native:b", status: "completed",
          task: "Review the header", tokens: { prompt: 100, completion: 50, total: 150, reported: true, cost_usd: null } }, ...snap.handoffs] }),
      mode: async () => collab(),
      setMode: async (m) => { mode = m; return collab(); },
    };
    render(<TeamView source={{ team: oneMind } as never} />);
    expect(await screen.findByText("Inner workings")).toBeTruthy();
    expect(screen.getByText("2 helpers · 1 working · 1 delegations")).toBeTruthy();
    expect(screen.getByText("Review the header")).toBeTruthy();
    expect(screen.getByText("150 tok")).toBeTruthy();
    expect(screen.queryByText("Review the Team page")).toBeNull(); // team hand-offs are not inner workings
    expect(screen.queryByRole("heading", { name: "Jaeger" })).toBeNull(); // helpers, not the lead
    expect(screen.queryByRole("button", { name: /New room/ })).toBeNull();
    const teamBtn = await screen.findByRole("radio", { name: /Team/ });
    await waitFor(() => expect((teamBtn as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(teamBtn);
    await waitFor(() => expect(mode).toBe("team"));
    expect(await screen.findByRole("button", { name: /New room/ })).toBeTruthy();
  });
  it("needs the live Gateway", () => {
    render(<TeamView source={{} as never} />);
    expect(screen.getByText(/needs the live Gateway/)).toBeTruthy();
  });
});
