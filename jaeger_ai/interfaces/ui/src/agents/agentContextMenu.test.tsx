import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentContextMenu, agentMenuItems } from "./AgentContextMenu";
import { NO_CAPS, agentCaps } from "../api/agentActions";
import type { Agent } from "../api/types";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { document.body.innerHTML = ""; });
const bot: Agent = { id: "native:fixture", name: "Fixture", role: "specialist", kind: "jaeger_native", primary: true };
const caps = { ...NO_CAPS, read: true, unread: true, primary: true, pin: true, hide: true, rename: true };

describe("scoped Mac agent popup", () => {
  it("matches current primary groups, toggles pin, and never offers identity transfer or delete", () => {
    const { main, more } = agentMenuItems(bot, caps, true, true);
    expect(main.map((i) => i.label)).toEqual(["Unpin", "Mark as Unread", "Copy conversation ID", "Hide from sidebar", "Replace with different Bot"]);
    expect(main.filter((i) => i.separator).map((i) => i.id)).toEqual(["copy-id", "hide"]);
    expect(more).toEqual([]);
    expect(agentMenuItems(bot, caps, true, true, true).main[1]).toMatchObject({ id: "read", label: "Mark as Read" });
    expect(agentMenuItems(bot, { ...caps, primary: false }, true, true).main.some((i) => i.id === "replace-primary")).toBe(false);
    expect(agentMenuItems(bot, caps, false, true).main[0].label).toBe("Pin");
    expect(agentMenuItems(bot, caps, true, false).main.some((i) => i.id === "replace-primary")).toBe(false);
  });
  it("offers only reference ordinary supported actions, with Make primary in management", () => {
    const other = { ...bot, primary: false };
    expect(agentMenuItems(other, caps, false, true).main.map((i) => i.label)).toEqual(["Pin", "Mark as Unread", "Rename Bot", "Copy conversation ID", "Hide from sidebar"]);
    expect(agentMenuItems(other, NO_CAPS, false, true).main.map((i) => i.label)).toEqual(["Copy conversation ID"]);
    const full = agentMenuItems(other, { ...caps, sections: true, remove: true }, false, true).main;
    expect(full.map(i => i.label)).toEqual(["Pin", "Move to new section", "Mark as Unread", "Rename Bot", "Copy conversation ID", "Hide from sidebar", "Delete"]);
    expect(full.filter(i => i.separator).map(i => i.id)).toEqual(["rename", "copy-id", "hide"]);
    expect(full.at(-1)).toMatchObject({ id: "delete", danger: true });
    expect(agentCaps([other], {} as never)).toEqual(NO_CAPS);
  });
  it("renders actual separators and dispatches the chosen ID without a hidden More menu", () => {
    const onAction = vi.fn(); const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
    act(() => root.render(<AgentContextMenu agent={bot} preview="" at={{ x: 12, y: 12 }} phone={false} caps={caps} pinned alternative onAction={onAction} onClose={() => {}} />));
    const items = [...el.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    expect(el.querySelectorAll('[role="separator"]')).toHaveLength(2);
    expect(el.querySelector('.jg-amenu__preview')).toBeNull();
    expect(items.some((i) => i.textContent?.includes("More"))).toBe(false);
    act(() => items.at(-1)!.click());
    expect(onAction).toHaveBeenCalledWith("replace-primary", bot);
    act(() => root.unmount());
  });
});

it("keeps the secondary rename prompt open when its input is clicked", async () => {
  const { AgentPrompt } = await import('./AgentContextMenu');
  const done = vi.fn(); const el = document.createElement('div'); document.body.append(el); const root = createRoot(el);
  await act(async () => { root.render(<AgentPrompt title="Rename fixture" confirm="Save" input={{ placeholder: "Name", value: "Owned" }} onDone={done} />); });
  act(() => el.querySelector('input')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  expect(done).not.toHaveBeenCalled();
  act(() => root.unmount());
});
