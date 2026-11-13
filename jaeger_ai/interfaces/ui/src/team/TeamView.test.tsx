import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TeamView } from "./TeamView";
import type { TeamApi, TeamSnapshot } from "../api/team";

const agent = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name: id, display_name: name, role: "specialist", team: "pilot", description: `${name} role`, persona: "", skills: ["s"], tools: ["read_file"],
  avatar: { seed: id, url: null }, pack: "character/v1", status: "idle", activity: null, ...extra,
});
const snap: TeamSnapshot = {
  agents: [agent("native:a", "Engineer"), agent("native:b", "Design", { status: "working" })],
  rooms: [{ session_id: "room-1", title: "Review room", members: ["native:a", "native:b"], probe: false },
          { session_id: "room-2", title: "Probe room", members: ["native:a", "native:b"], probe: true }],
  handoffs: [{ id: "h1", from_agent_id: "native:a", to_agent_id: "native:b", status: "completed", task: "Review the Team page" }],
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
    await waitFor(() => expect(screen.getByText("Two findings.")).toBeTruthy());
    expect(screen.queryByRole("option", { name: "Probe room" })).toBeNull();
  });
  it("needs the live Gateway", () => {
    render(<TeamView source={{} as never} />);
    expect(screen.getByText(/needs the live Gateway/)).toBeTruthy();
  });
});
