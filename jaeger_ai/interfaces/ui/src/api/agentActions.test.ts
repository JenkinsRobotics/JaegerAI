import { expect, it, vi } from "vitest";
import { agentCaps, isProtected, NO_CAPS } from "./agentActions";
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
