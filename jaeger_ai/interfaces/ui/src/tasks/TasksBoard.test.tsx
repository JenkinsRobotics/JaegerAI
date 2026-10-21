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
it("recovers an uncertain proposal by read only lookup without clearing a newer draft", async () => {
  const prefix = 'jaeger.ui.task-proposal.';
  const intent = { requestId: 'owned-nonce', sessionId: 'owned-home', origin: 'owned-bot', goal: 'Original proposal ' };
  localStorage.setItem(prefix+'intent.v1.owned-nonce', JSON.stringify(intent));
  localStorage.setItem(prefix+'draft.v1', JSON.stringify({ goal: 'Newer draft', origin: 'owned-bot' }));
  const create = vi.fn(), lookup = vi.fn(async () => ({ session_id: intent.sessionId, request_id: intent.requestId, tasks: [{ task_id: 'owned-task', goal: 'Later edited proposal', state: 'paused', provenance: { submission_goal: 'Original proposal' } }] }));
  const el = await mount({ tasks: async () => [], agentHome: vi.fn(), taskActions: { create, lookup } as never });
  expect((el.querySelector('[aria-label="Task objective"]') as HTMLTextAreaElement).value).toBe('Newer draft');
  await act(async () => [...el.querySelectorAll('button')].find(b=>b.textContent==='Check saved proposal')!.click());
  expect(lookup).toHaveBeenCalledExactlyOnceWith('owned-home', 'owned-nonce');
  expect(create).not.toHaveBeenCalled();
  expect(localStorage.getItem(prefix+'intent.v1.owned-nonce')).toBeNull();
  expect(JSON.parse(localStorage.getItem(prefix+'draft.v1')!).goal).toBe('Newer draft');
  localStorage.removeItem(prefix+'draft.v1');
});
it("retains the command journal when lookup is absent or has a conflicting objective", async () => {
  const key = 'jaeger.ui.task-proposal.intent.v1.owned-conflict';
  localStorage.setItem(key, JSON.stringify({ requestId: 'owned-conflict', sessionId: 'owned-home', origin: 'owned-bot', goal: 'Original' }));
  const create = vi.fn();
  const el = await mount({ tasks: async () => [{ task_id: 'other', goal: 'Different', provenance: { request_id: 'owned-conflict', session_id: 'owned-home' } }], agentHome: vi.fn(), taskActions: { create } as never });
  await act(async () => [...el.querySelectorAll('button')].find(b=>b.textContent==='Check saved proposal')!.click());
  expect(el.textContent).toContain('Saved task objective differs');
  expect(localStorage.getItem(key)).not.toBeNull();
  expect(create).not.toHaveBeenCalled();
  localStorage.removeItem(key);
});
