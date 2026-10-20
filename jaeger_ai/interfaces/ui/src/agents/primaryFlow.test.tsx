/** Owned in-memory HTTP/source contract fixture; never uses operator agents/drafts. */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { MockSource } from "../api/mock";
import type { Agent, AgentSummary } from "../api/types";
import type { HomeSessions } from "../chat/homeSession";
import { isUnread } from "./unread";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { localStorage.clear(); document.body.innerHTML = ""; });
const flush = async (fn: () => void = () => {}) => act(async () => { fn(); await new Promise((r) => setTimeout(r, 0)); });

it("replaces only primary, preserves open draft/history, copies exact home, hides/restores and defaults to persisted primary on remount", async () => {
  const caps = { primary: true, unread: true, read: true, rename: true, pin: true, hide: true };
  const a: Agent = { id: "native:fixture-a", name: "Fixture A", role: "specialist", primary: true, ui_actions: caps };
  const b: Agent = { id: "native:fixture-b", name: "Fixture B", role: "specialist", primary: false, ui_actions: caps };
  const rows = [a, b]; let pins: string[] = []; const unread: Record<string, boolean> = {};
  const source = new MockSource();
  vi.spyOn(source, "agents").mockImplementation(async () => rows.map((r) => ({ ...r })));
  vi.spyOn(source, "agentsSummary").mockImplementation(async () => rows.map((r) => ({ id: r.id, status: "idle", unseen: !!unread[r.id] } as AgentSummary)));
  const home: HomeSessions = { mode: "contract", home: vi.fn(async (id) => `actual-conversation-${id}`),
    page: async (id) => ({ sessionId: id, agentId: id.replace("actual-conversation-", ""), turns: [], entries: {} }),
    history: async () => [], read: async (id) => ({ sessionId: id, turns: [], entries: {} }) };
  vi.spyOn(source, "homeSessions").mockReturnValue(home);
  const setPrimary = vi.fn(async (id: string, expected: string) => {
    expect(rows.find((r) => r.primary)?.id).toBe(expected);
    rows.forEach((r) => { r.primary = r.id === id; });
    if (!pins.includes(id)) pins.push(id);
    rows.forEach((r) => { r.pinned = pins.includes(r.id); r.pin_order = pins.indexOf(r.id); });
  });
  const markUnread = vi.fn(async (id: string) => { unread[id] = true; });
  const markRead = vi.fn(async (id: string) => { unread[id] = false; });
  const patch = vi.fn(async (id: string, body: { archived?: boolean }) => { const row = rows.find((r) => r.id === id)!; row.archived = body.archived; row.hidden = body.archived; });
  Object.defineProperty(source, "agentActions", { value: { ...source.agentActions, setPrimary, markUnread, markRead, patchAgent: patch,
    savePins: async (ids: string[], expected: string[]) => {
      expect(pins).toEqual(expected); pins = [...ids]; rows.forEach((r) => { r.pinned = pins.includes(r.id); r.pin_order = pins.indexOf(r.id); });
    } } });
  const priorClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  const clipboard = vi.fn(async () => {});
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboard } });
  const el = document.createElement('div'); document.body.append(el); let root = createRoot(el);
  const click = async (text: string) => flush(() => { const buttons = [...el.querySelectorAll<HTMLButtonElement>('button')]; const button = buttons.find((b) => b.textContent?.replace(/[\uE000-\uF8FF]/g, '').trim() === text); if (!button) throw new Error(`Missing ${text}; buttons: ${buttons.map((b) => b.textContent).join(' | ')}`); button.click(); });
  const context = async (name: string) => flush(() => {
    const button = [...el.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.title === name || b.title === `${name} · Primary bot`)!;
    button.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 30, clientY: 30 }));
  });
  try {
    await flush(() => root.render(<App source={source} />)); await flush();
    const field = el.querySelector<HTMLTextAreaElement>('textarea')!;
    expect(field.placeholder).toBe('Message Fixture A');
    await flush(() => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, 'owned unsent draft'); field.dispatchEvent(new Event('input', { bubbles: true })); });
    await context('Fixture A'); await click('Replace with different Bot');
    await flush(() => { const choose = el.querySelector<HTMLSelectElement>('[aria-label="Primary bot candidate"]')!; choose.value = b.id; choose.dispatchEvent(new Event('change', { bubbles: true })); });
    await click('Make primary');
    expect(setPrimary).toHaveBeenCalledWith(b.id, a.id);
    const starIds = () => [...new Set([...el.querySelectorAll<HTMLElement>('[data-primary-agent-id]')].map((n) => n.dataset.primaryAgentId))];
    expect(starIds()).toEqual([b.id]);
    expect(a.role).toBe('specialist'); expect(b.role).toBe('specialist'); expect(b.pinned).toBe(true);
    expect(el.querySelector('textarea')).toBe(field); expect(field.value).toBe('owned unsent draft'); expect(field.placeholder).toBe('Message Fixture A');
    await context('Fixture A');
    expect(el.querySelector('[role=menu]')?.textContent).toContain('Rename Bot');
    expect(el.querySelector('[role=menu]')?.textContent).not.toContain('Replace with different Bot');
    await click('Copy conversation ID');
    expect(clipboard).toHaveBeenCalledWith(`actual-conversation-${a.id}`);
    await context('Fixture B'); await click('Unpin');
    expect(b.pinned).toBe(false); expect(b.primary).toBe(true); expect(starIds()).toEqual([b.id]);
    expect(el.querySelector('.jg-pinned')?.textContent ?? '').not.toContain('Fixture B');
    expect(el.querySelector('[data-agent-id="native:fixture-b"]')?.textContent).toContain('Fixture B');
    await context('Fixture B'); await click('Pin'); expect(b.pinned).toBe(true);
    setPrimary.mockRejectedValueOnce(new Error('owned primary save rejected'));
    await context('Fixture B'); await click('Replace with different Bot');
    await flush(() => { const choose = el.querySelector<HTMLSelectElement>('[aria-label="Primary bot candidate"]')!; choose.value = a.id; choose.dispatchEvent(new Event('change', { bubbles: true })); });
    await click('Make primary');
    expect(b.primary).toBe(true); expect(starIds()).toEqual([b.id]);
    expect(el.textContent).toContain('owned primary save rejected'); await click('Cancel');
    await context('Fixture B'); await click('Mark as Unread');
    expect(unread[b.id]).toBe(true); expect(starIds()).toEqual([b.id]);
    await context('Fixture B'); expect(el.querySelector('[role=menu]')?.textContent).toContain('Mark as Read');
    await click('Mark as Read'); expect(unread[b.id]).toBe(false); expect(starIds()).toEqual([b.id]);
    await context('Fixture B'); await click('Mark as Unread');
    await context('Fixture B'); await click('Hide from sidebar');
    expect(b.primary).toBe(true); expect(b.archived).toBe(true);
    await flush(() => el.querySelector<HTMLButtonElement>('[aria-label^="Account"]')!.click()); await click('Agents');
    expect(el.textContent).toContain('Primary'); await click('Restore');
    expect(b.archived).toBe(false); expect(b.primary).toBe(true); expect(starIds()).toEqual([b.id]); expect(field.value).toBe('owned unsent draft');
    await flush(() => root.unmount()); root = createRoot(el);
    await flush(() => root.render(<App source={source} />)); await flush();
    expect(el.querySelector<HTMLTextAreaElement>('textarea')!.placeholder).toBe('Message Fixture B');
    expect(starIds()).toEqual([b.id]);
    expect(markRead).toHaveBeenCalledWith(b.id, null); expect(unread[b.id]).toBe(false);
  } finally {
    await flush(() => root.unmount()); el.remove();
    if (priorClipboard) Object.defineProperty(navigator, 'clipboard', priorClipboard);
    else Reflect.deleteProperty(navigator, 'clipboard');
  }
});

it("server unread is authoritative across reload/local seen marks, including a currently open bot", () => {
  expect(isUnread('a', 0, { a: Date.now() }, true)).toBe(true);
  expect(isUnread('a', 300, {}, false)).toBe(false);
  expect(isUnread('a', 300, { a: 200 }, undefined)).toBe(true);
});
