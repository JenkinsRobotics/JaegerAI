import { expect, it, vi } from "vitest";
import { agentCaps, isProtected, NO_CAPS, conversationIdForAgent } from "./agentActions";
import { GatewayClient } from "./gateway";
it("does not infer destructive capabilities from identity/unread fields", () => {
  const agent = { id: "native:lead", name: "lead", primary: false, unread_count: 0, hidden: false, section_id: null };
  const client = new GatewayClient();
  expect(agentCaps([agent], client.agentActions)).toEqual(NO_CAPS);
  expect(agentCaps([{ ...agent, ui_actions: { read: true } }], client.agentActions)).toEqual({ ...NO_CAPS, read: true });
  expect(isProtected({ ...agent, role: "lead" })).toBe(true);
});
it("Mark Read uses the existing validated seen route without changing agent identity", async () => {
  const client = new GatewayClient();
  const json = vi.spyOn(client, "json").mockResolvedValue({});
  await client.agentActions.markRead("native:jaeger", null);
  expect(json).toHaveBeenCalledWith("/v1/agents/native%3Ajaeger/seen", {});
});
it("sends only cosmetic patches and includes pin concurrency preconditions", async () => {
  const client = new GatewayClient();
  const json = vi.spyOn(client, "json").mockResolvedValue({});
  await client.agentActions.patchAgent("agent:builder", { display_name: "New label", archived: false });
  expect(json).toHaveBeenCalledWith("/v1/agents/agent%3Abuilder", { display_name: "New label", archived: false }, "PATCH");
  await client.agentActions.savePins!(["b", "a"], ["a", "b"]);
  expect(json).toHaveBeenCalledWith("/v1/agents/pins", { agent_ids: ["b", "a"], expected_agent_ids: ["a", "b"] });
});

it("uses durable primary/unread routes with no owner or execution fields", async () => {
  const client = new GatewayClient(); const json = vi.spyOn(client, "json").mockResolvedValue({});
  await client.agentActions.setPrimary!("native:other", "native:first");
  expect(json).toHaveBeenCalledWith("/v1/agents/primary", { agent_id: "native:other", expected_agent_id: "native:first" });
  await client.agentActions.markUnread!("native:other");
  expect(json).toHaveBeenCalledWith("/v1/agents/native%3Aother/seen", { unread: true });
  expect(isProtected({ id: "native:other", primary: true, role: "specialist" })).toBe(false);
});
it("copies the exact resolved home or selected worker session, never the agent ID", async () => {
  const home = vi.fn(async () => "actual-home-123");
  expect(await conversationIdForAgent("native:other", home)).toBe("actual-home-123");
  expect(home).toHaveBeenCalledWith("native:other");
  home.mockClear();
  expect(await conversationIdForAgent("native:other", home, { agentId: "native:other", sessionId: "worker-session-456" })).toBe("worker-session-456");
  expect(home).not.toHaveBeenCalled();
  await expect(conversationIdForAgent("native:other", async () => "")).rejects.toThrow("Conversation ID unavailable");
});
