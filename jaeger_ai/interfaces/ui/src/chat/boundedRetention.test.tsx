/* GB-074: inline transcript retention is bounded by whole pages; dropped pages remain reachable through their
 * original cursor (isolated fixture home source, no gateway). */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import type { HomePage, HomeSessions } from "./homeSession";
import { MinimalChat, RETAINED_TURNS_MAX } from "./MinimalChat";
import { WebHost } from "./webHost";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const SIZE = 250;
const pageOf = (n: number, before?: string): HomePage => ({ sessionId: "s", entries: {}, before,
  turns: Array.from({ length: SIZE }, (_, i) => ({ turnId: `p${n}-${i}`, message: `m${n}-${i}`, parts: [], state: "completed" as never })) });
const cursors = [undefined, "c1", "c2"] as const;

it("drops the oldest whole pages beyond the budget at the bottom and refetches them from their own cursor", async () => {
  const page = vi.fn(async (_s: string, before?: string) => before === "c2" ? pageOf(2) : before === "c1" ? pageOf(1, "c2") : pageOf(0, "c1"));
  const home: HomeSessions = { mode: "mock", home: async () => "s", page, history: async () => [], read: async () => pageOf(0) };
  const h = new WebHost(new MockSource()); h.home = home; h.listAgents = async () => [];
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<MinimalChat host={h} sessionId="s" />)); await flush();
  const count = () => el.querySelectorAll("section").length;
  const earlier = () => [...el.querySelectorAll("button")].find((b) => b.textContent === "Show earlier messages");
  expect(count()).toBe(SIZE);
  await act(async () => earlier()!.click()); await flush();
  await act(async () => earlier()!.click()); await flush();
  expect(count()).toBe(3 * SIZE);                       // reading older history: never trimmed under the reader
  expect(page.mock.calls.map((c) => c[1])).toEqual([...cursors]);
  const scroller = el.querySelector<HTMLDivElement>(".jg-chat__scroll")!;
  Object.defineProperty(scroller, "scrollHeight", { configurable: true, get: () => 1000 });
  Object.defineProperty(scroller, "clientHeight", { configurable: true, get: () => 1000 });
  scroller.scrollTop = 0;
  await act(async () => { scroller.dispatchEvent(new Event("scroll")); }); await flush();
  expect(count()).toBeLessThanOrEqual(RETAINED_TURNS_MAX);
  expect(count()).toBe(SIZE);                           // whole pages dropped; the newest page is kept
  expect(el.textContent).toContain("m0-249");
  expect(el.textContent).not.toContain("m1-0");
  page.mockClear();
  await act(async () => earlier()!.click()); await flush();
  expect(page).toHaveBeenCalledWith("s", "c1");         // the dropped page is refetched, not lost
  expect(el.textContent).toContain("m1-0");
  act(() => root.unmount()); el.remove();
});
