import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { agentCaps, NO_CAPS, type AgentActions } from "../api/agentActions";
import { MockSource } from "../api/mock";
import type { Agent } from "../api/types";
import { AgentContextMenu, AgentPrompt, agentMenuItems } from "./AgentContextMenu";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { document.body.innerHTML = ""; });
const gw = { id: "agent:gw", name: "gw", display_name: "Jaeger Gateway & WebUI", role: "builder" } as Agent;
const ALL = { read: true, pin: true, hide: true, sections: true, duplicate: true, remove: true, template: true };
const labels = (sel: string) => [...document.querySelectorAll(`${sel} [role="menuitem"]`)].map((b) => b.textContent!.replace(/[\uE000-\uF8FF]/g, "").trim());
function mount(node: React.ReactNode) { const el = document.createElement("div"); document.body.append(el); const root = createRoot(el); act(() => root.render(node)); return root; }

describe("agent capabilities (spec fields on GET /v1/agents)", () => {
  it("today's gateway (no new fields): nothing server-backed", () => {
    expect(agentCaps([gw], {} as AgentActions)).toEqual(NO_CAPS);
  });
  it("a gateway on the spec: every item", () => {
    expect(agentCaps([{ ...gw, ui_actions: ALL }], {} as AgentActions)).toEqual(ALL);
  });
});

describe("AgentContextMenu", () => {
  it("full spec: Grok's order, preview card, More expands Copy ID / Duplicate / Delete and dims the first card", () => {
    const onAction = vi.fn();
    mount(<AgentContextMenu agent={gw} preview="The iPhone fix is tested" at={{ x: 10, y: 10 }} phone caps={ALL} pinned={false} onAction={onAction} onClose={() => {}} />);
    expect(document.querySelector(".jg-amenu__bubble")!.textContent).toBe("The iPhone fix is tested");
    expect(labels('[aria-label="Jaeger Gateway & WebUI actions"]')).toEqual(["Open chat", "Agent profile", "Conversation history", "Mark Read", "Pin on this device", "New Section", "Share as Template", "Hide", "More"]);
    expect(document.querySelector(".is-danger")!.textContent).toContain("Hide");
    act(() => [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((b) => b.textContent!.includes("More"))!.click());
    expect(labels('[aria-label="More"]')).toEqual(["More", "Copy ID", "Duplicate", "Delete"]);
    expect(document.querySelector(".jg-amenu__card.is-dimmed")).toBeTruthy();
    act(() => [...document.querySelectorAll<HTMLButtonElement>('[aria-label="More"] [role="menuitem"]')].find((b) => b.textContent!.includes("Delete"))!.click());
    expect(onAction).toHaveBeenCalledWith("delete", gw);
  });
  it("today's gateway: only Mark Read (local), Pin (local) and More → Copy ID", () => {
    const { main, more } = agentMenuItems(gw, NO_CAPS, false);
    expect(main.map((i) => i.label)).toEqual(["Open chat", "Agent profile", "Conversation history", "Mark Read on this device", "Pin on this device"]);
    expect(more.map((i) => i.label)).toEqual(["Copy ID"]);
  });
  it("never offers Hide or Delete for protected agents (primary, native:jaeger)", () => {
    for (const a of [{ ...gw, primary: true }, { ...gw, id: "native:jaeger" }]) {
      const { main, more } = agentMenuItems(a, ALL, true);
      expect(main.map((i) => i.label)).not.toContain("Hide");
      expect(main.map((i) => i.label)).toContain("Unpin on this device");
      expect(more.map((i) => i.label)).not.toContain("Delete");
    }
  });
});

describe("Delete confirm + mock gateway", () => {
  it("Cancel never deletes; Delete confirms; the mock soft-deletes and refuses the lead with 409", async () => {
    const done = vi.fn();
    mount(<AgentPrompt title="Delete Jaeger Gateway & WebUI?" danger confirm="Delete" onDone={done} />);
    act(() => [...document.querySelectorAll("button")].find((b) => b.textContent === "Cancel")!.click());
    expect(done).toHaveBeenLastCalledWith(false);
    act(() => [...document.querySelectorAll("button")].find((b) => b.textContent === "Delete")!.click());
    expect(done).toHaveBeenLastCalledWith(true, "");
    const mock = new MockSource();
    await mock.agentActions.remove("agent:gateway-webui");
    expect((await mock.agents()).some((a) => a.id === "agent:gateway-webui")).toBe(false);
    await expect(mock.agentActions.remove("native:jaeger")).rejects.toMatchObject({ status: 409 });
  });
});
