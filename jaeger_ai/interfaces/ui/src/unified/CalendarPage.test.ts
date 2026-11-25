import { expect, it } from "vitest";
import type { ScheduleJob } from "../api/source";
import { calendarEntries } from "./CalendarPage";

it("joins open deadlines and enabled next runs without inventing occurrences", () => {
  const base: ScheduleJob = { id: "brief", name: "Daily brief", prompt: "", cron: "0 9 * * *", state: "active", enabled: true };
  const entries = calendarEntries([
    { ...base, next_fire_at: "2026-11-25T17:00:00Z" },
    { ...base, id: "paused", enabled: false, next_fire_at: "2026-11-25T18:00:00Z" },
    { ...base, id: "invalid", next_fire_at: "not a date" },
  ], [
    { task_id: "first", state: "running", eta: "2026-11-25T16:00:00Z", goal: "Prepare slides" },
    { task_id: "complete", state: "completed_verified", eta: "2026-11-25T15:00:00Z" },
  ]);
  expect(entries.map(i => [i.kind, i.href])).toEqual([
    ["task", "/work/tasks?task=first"],
    ["schedule", "/automations?job=brief"],
  ]);
});
