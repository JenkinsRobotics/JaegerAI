import { expect, it } from "vitest";
import type { Task } from "../api/types";
import { currentBackgroundTasks } from "./ConversationTasks";

it("shows only confirmed active background work owned by this conversation", () => {
  const task = (task_id: string, state: string, session_id = "mine", goal = "Prepare the brief"): Task =>
    ({ task_id, state, goal, provenance: { session_id } });
  expect(currentBackgroundTasks([
    task("job-active", "running"),
    task("job-queued", "queued"),
    task("foreign", "running", "other"),
    task("turn:in-chat", "running"),
    task("finished", "completed"),
    task("maintenance", "running", "mine", "Skill review (background, no one is waiting)"),
  ], "mine").map(t => t.task_id)).toEqual(["job-active", "job-queued"]);
});
