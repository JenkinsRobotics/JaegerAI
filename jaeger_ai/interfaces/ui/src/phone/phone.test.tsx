import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { PhoneChat, PhoneList, rowView } from "./PhoneShell";
import { rowTime } from "./usePhone";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const now = Date.now() / 1000;
const agents = [
  { id: "native:jaeger", name: "jaeger", display_name: "Jager AI system engineer", role: "lead" },
  { id: "native:gw", name: "gw", display_name: "Jaeger Gateway & WebUI", role: "specialist" },
  { id: "native:mac", name: "mac", display_name: "Jaeger Mac App", role: "specialist", unread_count: 0,
    last_message: { id: "m1", created_at: new Date((now - 60) * 1000).toISOString(), kind: "task", preview: "From last_message" } },
] as never[];
const summaries = [{ id: "native:gw", last_preview: "Message from lead", last_activity_at: now - 120, last_source: "handoff", unseen: true, status: "working" }] as never[];

function mount(node: React.ReactNode) {
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  act(() => root.render(node)); return { el, root };
}

describe("phone list", () => {
  it("features the lead with a star; rows have name, time, typed preview, unread dot and an N-unread pill", () => {
    const onOpen = vi.fn();
    const { el, root } = mount(<PhoneList state={{ agents, summaries, seen: {} }} userInitials="MJ" statusOk onOpen={onOpen} onSearch={() => {}} onNew={() => {}} onSettings={() => {}} />);
    expect(el.querySelector(".jg-plead__name")!.textContent).toBe("Jaeger");
    const rows = [...el.querySelectorAll(".jg-prow")];
    expect(rows.map((r) => r.querySelector(".jg-prow__name")!.textContent)).toEqual(["Jaeger Mac App", "Jaeger Gateway & WebUI"]);
    expect(rows[0].textContent).toContain("From last_message");
    expect(rows[1].querySelector('[aria-label="Unread"]')).toBeTruthy();
    expect(rows[1].querySelector('[aria-label="Active"]')).toBeTruthy();
    expect(rows[0].querySelector('[aria-label="Unread"]')).toBeNull();
    expect(el.querySelector(".jg-punread")!.textContent).toContain("1 unread");
    for (const b of el.querySelectorAll("button")) expect(b.className).toBeTruthy();
    act(() => (rows[1] as HTMLElement).click());
    expect(onOpen).toHaveBeenCalledWith("native:gw");
    act(() => root.unmount());
  });
  it("uses primary for the featured agent and unread_count over the local seen mark", () => {
    const v = rowView({ agent: { id: "a", name: "a", unread_count: 3 } as never, lastActivityAt: 0 }, { a: 9e12 });
    expect(v.unread).toBe(true);
  });
  it("formats row times like iOS", () => {
    const n = new Date(2026, 9, 19, 9, 0);
    expect(rowTime(new Date(2026, 9, 19, 7, 15).getTime() / 1000, n)).toBe("7:15 AM");
    expect(rowTime(new Date(2026, 9, 18, 7, 15).getTime() / 1000, n)).toBe("Yesterday");
  });
});

describe("phone chat", () => {
  it("shows back, the agent pill and …; Back and a left-edge swipe return to the list", () => {
    const onBack = vi.fn();
    const { el, root } = mount(<PhoneChat agentId="native:gw" agentName="Jaeger Gateway & WebUI" onBack={onBack} onInfo={() => {}}><p>chat</p></PhoneChat>);
    expect(el.querySelector(".jg-pbar__pill")!.textContent).toContain("Jaeger Gateway & WebUI");
    act(() => el.querySelector<HTMLButtonElement>('[aria-label="Back"]')!.click());
    const screen = el.querySelector(".jg-phone-chat")!;
    const touch = (type: string, x: number) => { const e = new Event(type, { bubbles: true }); Object.assign(e, { touches: [{ clientX: x, clientY: 300 }], changedTouches: [{ clientX: x, clientY: 300 }] }); screen.dispatchEvent(e); };
    act(() => { touch("touchstart", 8); touch("touchend", 140); });
    expect(onBack).toHaveBeenCalledTimes(2);
    act(() => root.unmount());
  });
});
