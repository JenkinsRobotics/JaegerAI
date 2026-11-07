import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { WorkspaceBrowser } from "./WorkspaceBrowser";
import type { JaegerSource } from "../api/source";

const source = { sessions: vi.fn(async () => [{ session_id: "chat-only", title: "No workspace" }, { session_id: "gateway-1", title: "Gateway chat", workspace: "/tmp/ws" }]) } as unknown as JaegerSource;
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });
async function mount(reply: (url: string) => Response, params = "") {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { expect(init?.method).toBeUndefined(); calls.push(url); return reply(url); }));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<WorkspaceBrowser source={source} params={new URLSearchParams(params)} />); });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  return { el, calls };
}
it("uses the selected Gateway session for read-only Git and file requests", async () => {
  const { el, calls } = await mount(url => url.startsWith("/api/list") ? Response.json({ entries: [{ name: "docs", path: "docs", type: "dir" }, { name: "readme.txt", path: "readme.txt", type: "file" }] }) : url.startsWith("/api/git/status") ? Response.json({ git: { is_git: true, branch: "main", files: [{ path: "readme.txt", status: "M", staged: false, unstaged: true, untracked: false }] } }) : url.startsWith("/api/git/branches") ? Response.json({ branches: { current: "main", local: [{ name: "main" }], remote: [] } }) : url.startsWith("/api/file?") ? Response.json({ content: "hello" }) : Response.json({ diff: { diff: "+hello" } }), "session=gateway-1");
  expect(calls).toHaveLength(3);
  expect(calls.every(url => new URL(url, "http://localhost").searchParams.get("session_id") === "gateway-1")).toBe(true);
  await act(async () => { [...el.querySelectorAll("button")].find(b => b.textContent?.includes("readme.txt") && !b.textContent?.includes("Diff"))?.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(el.textContent).toContain("hello");
  expect(el.querySelector("a")?.getAttribute("href")).toContain("/api/file/raw?");
  await act(async () => { [...el.querySelectorAll("button")].find(b => b.textContent === "Diff")?.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(el.textContent).toContain("+hello");
  expect(calls.every(url => url.startsWith("/api/") && new URL(url, "http://localhost").searchParams.get("session_id") === "gateway-1")).toBe(true);
});
it("shows a clear empty workspace state", async () => {
  const { el } = await mount(url => url.startsWith("/api/list") ? Response.json({ entries: [] }) : url.startsWith("/api/git/status") ? Response.json({ git: { is_git: false } }) : Response.json({ branches: null }), "session=gateway-1");
  expect(el.textContent).toContain("workspace folder is empty");
  expect(el.textContent).toContain("not a Git repository");
});
it("handles a missing Gateway session without a file or Git panel", async () => {
  const { el } = await mount(() => Response.json({ error: "Session not found" }, { status: 404 }), "session=missing");
  expect(el.querySelector('[role="alert"]')?.textContent).toContain("no workspace to browse");
  expect(el.querySelector('[aria-label="File browser"]')).toBeNull();
});
it("defaults to the first session that has a workspace", async () => {
  const { calls, el } = await mount(url => url.startsWith("/api/list") ? Response.json({ entries: [] }) : url.startsWith("/api/git/status") ? Response.json({ git: { is_git: false } }) : Response.json({ branches: null }));
  expect(calls.length).toBeGreaterThan(0);
  expect(calls.every(url => new URL(url, "http://localhost").searchParams.get("session_id") === "gateway-1")).toBe(true);
  expect([...el.querySelectorAll("option")].map(o => o.textContent)).not.toContain("No workspace");
});
it("opens folders reported with type dir", async () => {
  const { el, calls } = await mount(url => url.startsWith("/api/list") ? Response.json({ entries: url.includes("path=docs") ? [] : [{ name: "docs", path: "docs", type: "dir" }] }) : url.startsWith("/api/git/status") ? Response.json({ git: { is_git: false } }) : Response.json({ branches: null }), "session=gateway-1");
  expect([...el.querySelectorAll("button")].some(button => button.textContent?.trim() === "docs")).toBe(true);
  await act(async () => { [...el.querySelectorAll("button")].find(b => b.textContent?.includes("docs"))?.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(calls.some(url => url.includes("path=docs"))).toBe(true);
  expect(calls.some(url => url.startsWith("/api/file?"))).toBe(false);
});
