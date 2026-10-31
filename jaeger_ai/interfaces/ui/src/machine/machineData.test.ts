import { describe, expect, it } from "vitest";
import { logsUrl, pressure, type ResourceConfig, type ResourceSnapshot } from "./machineData";
import { jobLine } from "../unified/RunnerQueue";
import { fmtNum, metered } from "../unified/UsagePage";

const cfg: ResourceConfig = { min_free_mem_gb: 4, max_memory_pressure: 1, max_cpu_load: 0.85, max_gpu_util_pct: 90, min_free_disk_gb: 15, research_disk_budget_gb: 40, pause_on_thermal: true, concurrency: { heavy: 1, light: 2 } };
const snap: ResourceSnapshot = { mem_free_gb: 15, mem_total_gb: 32, mem_pressure: 1, cpu_load: 0.4, gpu_util: 37, disk_free_gb: 1800, thermal: "nominal", on_battery: false, battery_pct: null, idle_s: 10, ollama_loaded: [], research_gb: 0.04, at: 0 };

describe("machine + work + models wiring helpers", () => {
  it("explains resource throttling only when a limit trips", () => {
    expect(pressure(snap, cfg)).toEqual([]);
    expect(pressure({ ...snap, mem_free_gb: 2, gpu_util: 95, thermal: "serious" }, cfg)).toEqual(["Free memory 2.0 GB < 4 GB", "GPU 95% > 90%", "Thermal state serious"]);
  });
  it("builds the logs query", () => {
    expect(logsUrl("jobs", { q: "error", level: "warn", lines: 50 })).toBe("/v1/machine/logs?source=jobs&lines=50&q=error&level=warn");
  });
  it("summarises runner jobs: paused, stuck, errors", () => {
    expect(jobLine({ task_id: "a", paused: true, item_count: 10, videos_done: 2 }).label).toBe("Paused · 2/10 videos");
    expect(jobLine({ task_id: "a", stuck: true, last_progress_s: 1800, item_count: 10 }).tone).toBe("bad");
    expect(jobLine({ task_id: "a", error_count: 3, item_count: 1, videos_done: 1, progress: { steps_finished: 1, steps_total: 8 } }).label).toBe("1/1 videos · batch 1/8 steps · 3 errors");
  });
  it("never shows unmetered zero tokens as real usage", () => {
    expect(metered({ total_tokens: 0 })).toBe(false); expect(metered({ total_tokens: 5 })).toBe(true);
    expect(fmtNum(1530)).toBe("1.5k"); expect(fmtNum(2_400_000)).toBe("2.4M");
  });
});
