import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { TasksBoard } from "./TasksBoard";
import type { JaegerSource } from "../api/source";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const roots: ReturnType<typeof createRoot>[] = [];
afterEach(async () => { await act(async () => roots.splice(0).forEach(r => r.unmount())); document.body.innerHTML = ""; });
async function mount(source: Partial<JaegerSource>) { const el = document.createElement("div"); document.body.append(el); const root = createRoot(el); roots.push(root); await act(async () => root.render(<TasksBoard source={source as JaegerSource} agents={[]} />)); return el; }
it("approves the displayed version only, preserves a backend rejection and shows unknown states", async () => {
  const approve = vi.fn(async () => { throw new Error("Task changed; refresh before approving"); });
  const source = { tasks: async () => [{ task_id: "owned", goal: "Original objective", state: "paused", updated_at: 42, provenance: { authorized: false } }, { task_id: "uncertain", state: "execution_unknown" }], taskActions: { approve, cancel: vi.fn(), create: vi.fn(), edit: vi.fn() } };
  const el = await mount(source);
  const button = [...el.querySelectorAll("button")].find(b => b.textContent === "Approve this version")!;
  await act(async () => button.click());
  expect(approve).toHaveBeenCalledExactlyOnceWith("owned", 42);
  expect(el.textContent).toContain("Task changed; refresh before approving");
  expect(el.textContent).not.toContain("Proposal approved");
  expect(el.querySelector('[aria-label="Other states"]')?.textContent).toContain("execution_unknown");
});
it("does not offer edit or approval for authorized or already executed paused tasks", async () => {
  const el = await mount({ tasks: async () => [{ task_id: "running-paused", state: "paused", updated_at: 42, provenance: { authorized: true } }, { task_id: "attempted", state: "paused", updated_at: 42, provenance: { authorized: false }, run_history: [{}] }], taskActions: {} as never });
  expect(el.textContent).not.toContain("Approve this version");
  expect(el.textContent).not.toContain("Edit proposal");
  expect([...el.querySelectorAll("button")].filter(b => b.textContent === "Cancel task")).toHaveLength(2);
});
