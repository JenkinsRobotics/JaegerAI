import { describe, expect, it } from "vitest";
import { summarizeRunner, type RunnerStatus } from "./jobsRunner";

const base: RunnerStatus = { service: "com.jenkinsrobotics.jaeger-jobs", health: "ok", heartbeat_age_s: 3,
  jobs: [{ task_id: "yt:X", title: "Ares", videos_in_job: 40, item_count: 2860, videos_done: 12, phase: 2, progress: { steps_finished: 200, steps_total: 320 } }] };

describe("summarizeRunner", () => {
  it("shows live progress across the whole playlist", () => {
    const s = summarizeRunner(base);
    expect(s.value).toBe("12/2860 videos (0%) · batch 200/320 steps");
    expect(s.tone).toBe("ok");
  });
  it("flags down, paused, stuck and errors", () => {
    expect(summarizeRunner({ ...base, health: "down" }).value).toBe("Runner stopped");
    expect(summarizeRunner({ ...base, jobs: [{ ...base.jobs[0], paused: true }] }).value.startsWith("Paused")).toBe(true);
    expect(summarizeRunner({ ...base, health: "stuck" }).tone).toBe("bad");
    expect(summarizeRunner({ ...base, jobs: [{ ...base.jobs[0], error_count: 2 }] }).value).toContain("2 errors");
    expect(summarizeRunner(undefined, "boom").tone).toBe("bad");
  });
});
