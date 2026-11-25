import { expect, it, vi } from "vitest";
import type { AgentLive, OrchestrationSnapshot } from "../../orchestration/types";
import { deriveWorkers, recoverMaskedChatStatus } from "./officeState";

const id = "native:jaeger";
const agent = { id, name: "Jaeger" };
const failed = { task_id: "turn:skill-review-old", agent_id: id, state: "failed", goal: "Skill review", updated_at: 200 };
const summary = { id, status: "error", task: failed, last_preview: "Skill review" };
const row: AgentLive = { agent, summary, status: "error", currentTask: failed };
const snapshot: OrchestrationSnapshot = { agents: [agent], summaries: [summary], handoffs: [], tasks: [failed] };

it("leaves a failed review in history without calling it current work", () => {
  const [worker] = deriveWorkers([row], snapshot, 300, false);
  expect(worker).toMatchObject({ mood: "idle", statusText: "Idle" });
  expect(worker.currentTask).toBeUndefined();
  expect(worker.bubble).toBeUndefined();
  expect(snapshot.tasks).toEqual([failed]);
});

it.each([["running", "working"], ["queued", "queued"], ["needs_owner", "approval"], ["blocked", "error"]])(
  "chooses current %s work over a newer historical failure", (state, mood) => {
    const current = { task_id: "current", agent_id: id, state, goal: "Prepare the brief", updated_at: 100 };
    const [worker] = deriveWorkers([row], { ...snapshot, tasks: [failed, current] }, 300, false);
    expect(worker).toMatchObject({ mood, currentTask: { task_id: "current" } });
    expect(worker.bubble).toContain("Prepare the brief");
  },
);

it("recovers an active chat when an older gateway masks it with a failed task", async () => {
  const sessions = vi.fn(async () => [
    { session_id: "previous", status: "failed" },
    { session_id: "current", status: "running" },
  ]);
  const fresh = await recoverMaskedChatStatus(snapshot, { sessions });
  expect(sessions).toHaveBeenCalledWith({ agent_id: id });
  const [worker] = deriveWorkers([{ ...row, summary: fresh.summaries[0] }], fresh, 300, false);
  expect(worker).toMatchObject({ mood: "working", sessionId: "current" });
  expect(worker.currentTask).toBeUndefined();
  expect(worker.bubble).toBeUndefined();
});

it("does not show stale task data when disconnected", () => {
  const [worker] = deriveWorkers([row], snapshot, 300, true);
  expect(worker.mood).toBe("offline");
  expect(worker.currentTask).toBeUndefined();
});
