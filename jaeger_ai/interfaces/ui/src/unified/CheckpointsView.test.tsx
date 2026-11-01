import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { CheckpointsView } from "./CheckpointsView";
import type { JaegerSource } from "../api/source";

const source = { sessions: vi.fn(async () => [{ session_id: "gateway-1", title: "Work", workspace: "/tmp/ws" }]) } as unknown as JaegerSource;
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });
it("lists checkpoint metadata and opens a read-only diff for the selected session", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { expect(init?.method).toBeUndefined(); calls.push(url); return url.startsWith("/api/checkpoints/list") ? Response.json({ checkpoints: [{ id: "abc123", message: "Before edit", date: "2026-10-31", date_display: "Oct 31", files: 2, files_changed: 1 }] }) : Response.json({ diff: "-old\n+new", total_changes: 1 }); }));
  const el = document.createElement("div"); document.body.append(el);
  await act(async () => { createRoot(el).render(<CheckpointsView source={source} params={new URLSearchParams()} />); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(el.textContent).toContain("Before edit · Oct 31 · 1 changed files");
  await act(async () => { [...el.querySelectorAll("button")].find(b => b.textContent?.includes("Before edit"))?.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(el.querySelector("pre")?.textContent).toContain("+new");
  expect(el.querySelector<HTMLButtonElement>("button[disabled]")?.textContent).toBe("Restore");
  expect(calls).toHaveLength(2);
  expect(calls.every(url => new URL(url, "http://localhost").searchParams.get("session_id") === "gateway-1")).toBe(true);
});
