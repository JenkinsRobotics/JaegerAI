import { describe, expect, it } from "vitest";
import { taskMatcher } from "./TasksWorkspace";

const tasks = [
  { task_id: "a", goal: "Write hello world", state: "paused", agent_id: "native:jaeger" },
  { task_id: "b", goal: "Summarise inbox", state: "running", agent_id: "native:ada" },
  { task_id: "c", goal: "Old report", state: "done", agent_id: "native:jaeger" },
];
describe("task filters", () => {
  it("'needs you' keeps paused proposals", () => expect(tasks.filter(taskMatcher("needs", "", "")).map((t) => t.task_id)).toEqual(["a"]));
  it("filters by agent and query", () => {
    expect(tasks.filter(taskMatcher("all", "native:jaeger", "")).map((t) => t.task_id)).toEqual(["a", "c"]);
    expect(tasks.filter(taskMatcher("all", "", "INBOX")).map((t) => t.task_id)).toEqual(["b"]);
    expect(tasks.filter(taskMatcher("finished", "", "")).map((t) => t.task_id)).toEqual(["c"]);
  });
});
