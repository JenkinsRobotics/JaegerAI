// The popups people hit: ⌘K Jump to, the composer's + menu, the message right-click menu, the agent menu.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JumpTo } from "../agents/JumpTo";
import { SpecialistList } from "../agents/SpecialistList";
import type { Agent } from "../api/types";
import { MinimalChat } from "./MinimalChat";
import { WebHost } from "./webHost";
import type { JaegerSource } from "../api/source";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement; let root: Root;
beforeEach(() => { el = document.createElement("div"); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); document.body.innerHTML = ""; });
const agents = [{ id: "native:builder", name: "builder", role: "builder" }, { id: "native:designer", name: "designer", role: "designer" }] as unknown as Agent[];
const key = (target: Element, k: string) => act(() => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })); });
const items = () => [...document.querySelectorAll('[role="menuitem"]')].map((n) => n.textContent?.trim()).filter(Boolean);

describe("⌘K Jump to", () => {
  it("filters Bots and actions, moves with arrows and opens with Enter", async () => {
    const onAgent = vi.fn(); const run = vi.fn(); const onClose = vi.fn();
    await act(async () => { root.render(<JumpTo open agents={agents} actions={[{ id: "settings", label: "Settings", run }]} onAgent={onAgent} onClose={onClose} />); });
    const input = document.querySelector<HTMLInputElement>('input[aria-label="Search"]')!;
    expect([...document.querySelectorAll('[role="option"]')].length).toBe(3);
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "des"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    expect([...document.querySelectorAll('[role="option"]')].map((o) => o.textContent)).toEqual([expect.stringMatching(/designer/i)]);
    await key(input, "Enter");
    expect(onAgent).toHaveBeenCalledWith("native:designer");
    expect(onClose).toHaveBeenCalled();
  });
  it("shows each bot's one-line description and an unread dot (Grok's Search rows)", async () => {
    const summaries = [{ id: "native:builder", last_preview: "Building the release", last_activity_at: 100, unseen: true }] as never;
    await act(async () => { root.render(<JumpTo open agents={agents} actions={[]} summaries={summaries} seen={{}} onAgent={vi.fn()} onClose={vi.fn()} />); });
    expect(document.body.textContent).toContain("Building the release");
    expect(document.querySelectorAll('[aria-label="Unread"]').length).toBe(1);
    expect(document.querySelector('input[aria-label="Search"]')!.getAttribute("placeholder")).toBe("Search");
  });
  it("says No matches for a query with no hits, and Esc closes", async () => {
    const onClose = vi.fn();
    await act(async () => { root.render(<JumpTo open agents={agents} actions={[]} onAgent={vi.fn()} onClose={onClose} />); });
    const input = document.querySelector<HTMLInputElement>('input[aria-label="Search"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "zzz"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(document.body.textContent).toContain('No matches for "zzz"');
    await key(input, "Escape");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("agent right-click", () => {
  it("offers Pin to top, Show info and Chat history", async () => {
    const onInfo = vi.fn();
    await act(async () => { root.render(<SpecialistList dragType="x" onPin={vi.fn()} onUnpin={vi.fn()} onInfo={onInfo} onHistory={vi.fn()}><div data-agent-id="native:builder">Builder</div></SpecialistList>); });
    await act(async () => { el.querySelector("[data-agent-id]")!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 10, clientY: 10 })); });
    expect(items().map((t) => (t ?? "").replace(/[\uE000-\uF8FF]/g, "").trim())).toEqual(["Pin to top", "Show info", "Chat history", "Copy agent ID"]);
  });
});

describe("composer + and message menus", () => {
  const source = { kind: "mock", session: vi.fn(async () => ({ sessionId: "s1", turns: [{ turnId: "t1", message: "hello there", parts: [{ kind: "markdownContent", text: "Hi! **Done.**" }], state: "complete" }] })),
    stream: vi.fn(async () => {}), agents: vi.fn(async () => []) } as unknown as JaegerSource;
  it("+ opens Composer actions; Attach files opens the picker", async () => {
    await act(async () => { root.render(<MinimalChat host={new WebHost(source)} sessionId="s1" />); });
    const picker = el.querySelector<HTMLInputElement>('input[type="file"]')!;
    const click = vi.spyOn(picker, "click").mockImplementation(() => {});
    await act(async () => { el.querySelector<HTMLButtonElement>('button[aria-label="Attach file"]')!.click(); });
    expect(document.querySelector('[aria-label="Composer actions"]')).toBeTruthy();
    expect(items()).toContain("Attach files");
    const attach = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((n) => n.textContent?.includes("Attach files"))!;
    await act(async () => { attach.click(); });
    expect(click).toHaveBeenCalled();
  });
  it("right-click on a bubble: Grok's reaction row + Reply, Copy, Copy request ID; Reply quotes it; a reaction shows under the turn", async () => {
    const host = { capabilities: { voice: false }, startTurn: vi.fn(), respondToConfirmation: vi.fn(), copy: vi.fn(), openExternal: vi.fn(),
      sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [{ turnId: "t1", message: "hello there", parts: [{ kind: "markdownContent", text: "Hi! **Done.**" }], state: "complete" }] })) } };
    await act(async () => { root.render(<MinimalChat host={host as never} sessionId="s1" />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const bubble = el.querySelector(".jg-bubble--assistant")!;
    Object.defineProperty(bubble, "innerText", { configurable: true, get: () => "Hi! Done." });
    await act(async () => { bubble.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 20, clientY: 20 })); });
    const labels = items().map((t) => (t ?? "").replace(/[\uE000-\uF8FF]/g, "").trim()).filter((t) => /[A-Za-z]/.test(t));
    expect(labels).toEqual(["Reply", "Copy", "Copy request ID"]);
    expect(document.querySelectorAll('[aria-label^="React "]').length).toBe(5);
    const reply = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((n) => n.textContent?.includes("Reply"))!;
    await act(async () => { reply.click(); });
    expect(el.querySelector<HTMLTextAreaElement>(".jg-composer__input")!.value).toBe("> Hi! Done.\n\n");
    await act(async () => { bubble.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 20, clientY: 20 })); });
    await act(async () => { document.querySelector<HTMLButtonElement>('[aria-label="React 👍"]')!.click(); });
    expect(document.querySelector('[data-turn-id="t1"] .jg-reaction')?.textContent).toBe("👍");
    expect(document.querySelector('[role="menu"]')).toBeNull();
  });
});

describe("native-shell popup bug (menus piled up)", () => {
  it("message menu, then + menu: only one stays open; a mousedown outside closes it", async () => {
    const host = { capabilities: { voice: false }, startTurn: vi.fn(), respondToConfirmation: vi.fn(), copy: vi.fn(), openExternal: vi.fn(),
      sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [{ turnId: "t1", message: "hi", parts: [{ kind: "markdownContent", text: "Hello" }], state: "complete" }] })) } };
    await act(async () => { root.render(<MinimalChat host={host as never} sessionId="s1" />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const menus = () => [...document.querySelectorAll('[role="menu"]')].map((m) => m.getAttribute("aria-label"));
    await act(async () => { el.querySelector(".jg-bubble--assistant")!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 20, clientY: 20 })); });
    expect(menus()).toEqual(["Message actions"]);
    const plus = el.querySelector<HTMLButtonElement>('button[aria-label="Attach file"]')!;
    await act(async () => { plus.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); plus.click(); });
    expect(menus()).toEqual(["Composer actions"]);
    await act(async () => { el.querySelector(".jg-composer__input")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    expect(menus()).toEqual([]);
  });
});
