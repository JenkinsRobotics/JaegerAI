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
