import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { AGENT_DRAG_TYPE } from "./pins";
import { SpecialistList } from "./SpecialistList";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A drag/drop event carrying an agent id, as WebKit delivers it. */
function dragEvent(type: string, id: string) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", {
    value: { types: [AGENT_DRAG_TYPE], getData: (t: string) => (t === AGENT_DRAG_TYPE ? id : ""), dropEffect: "none" },
  });
  return event;
}

describe("SpecialistList drop zone", () => {
  it("unpins a tile dropped on the empty list (every specialist pinned) and shows the hint", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onUnpin = vi.fn();
    act(() => { root.render(<SpecialistList dragType={AGENT_DRAG_TYPE} onPin={() => {}} onUnpin={onUnpin} emptyDropHint>{[]}</SpecialistList>); });
    const nav = host.querySelector("nav")!;
    expect(nav.textContent).toContain("Drag a pinned agent here to unpin it");
    const over = dragEvent("dragover", "agent:everyday");
    act(() => { nav.dispatchEvent(over); });
    expect(over.defaultPrevented).toBe(true);
    expect(nav.className).toContain("is-drop-target");
    const drop = dragEvent("drop", "agent:everyday");
    act(() => { nav.dispatchEvent(drop); });
    expect(onUnpin).toHaveBeenCalledWith("agent:everyday");
    expect(nav.className).not.toContain("is-drop-target");
    act(() => root.unmount());
    host.remove();
  });

  it("ignores drags that don't carry an agent (e.g. files)", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onUnpin = vi.fn();
    act(() => { root.render(<SpecialistList dragType={AGENT_DRAG_TYPE} onPin={() => {}} onUnpin={onUnpin}>{[]}</SpecialistList>); });
    const files = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(files, "dataTransfer", { value: { types: ["Files"], getData: () => "" } });
    act(() => { host.querySelector("nav")!.dispatchEvent(files); });
    expect(onUnpin).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain("unpin");
    act(() => root.unmount());
    host.remove();
  });
});

describe("Agent actions menu", () => {
  it("offers Pin, Mark as read, Show info, Chat history, Copy agent ID with icons; Mark as read calls back with the id", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onMarkRead = vi.fn();
    act(() => { root.render(<SpecialistList dragType={AGENT_DRAG_TYPE} onPin={() => {}} onUnpin={() => {}} onInfo={() => {}} onHistory={() => {}} onMarkRead={onMarkRead}>{[<div key="a" data-agent-id="native:builder">Builder</div>]}</SpecialistList>); });
    act(() => { host.querySelector("[data-agent-id]")!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 10, clientY: 10 })); });
    const items = [...document.querySelectorAll('[role="menuitem"]')];
    expect(items.map((i) => i.textContent!.replace(/[\uE000-\uF8FF]/g, "").trim())).toEqual(["Pin to top", "Mark as read", "Show info", "Chat history", "Copy agent ID"]);
    expect(items.every((i) => i.querySelector(".jg-icon"))).toBe(true);
    act(() => { (items[1] as HTMLElement).click(); });
    expect(onMarkRead).toHaveBeenCalledWith("native:builder");
    act(() => root.unmount());
  });
});
