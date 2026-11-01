/** Machine tab data: resource manager (GET /v1/resources) and log tail (GET /v1/machine/logs). */
export type ResourceSnapshot = { mem_free_gb: number; mem_total_gb: number; mem_pressure: number; cpu_load: number; gpu_util: number | null; disk_free_gb: number; thermal: string; on_battery: boolean; battery_pct: number | null; idle_s: number; ollama_loaded: string[]; research_gb: number; at: number };
export type ResourceConfig = { min_free_mem_gb: number; max_memory_pressure: number; max_cpu_load: number; max_gpu_util_pct: number; min_free_disk_gb: number; research_disk_budget_gb: number; pause_on_thermal: boolean; concurrency: { heavy: number; light: number } };
export type ResourceStatus = { snapshot: ResourceSnapshot; config: ResourceConfig; decision?: { allow?: boolean; reason?: string; [k: string]: unknown }; [k: string]: unknown };
export type LogLine = { text: string; level: "debug" | "info" | "warn" | "error" | string };
export type LogTail = { source: string; exists: boolean; lines: LogLine[]; truncated: boolean; bytes?: number; mtime?: number };
export type LogSource = { id: string; exists: boolean; bytes: number; mtime: number | null };

/** Which limits the resource manager would currently trip, so the card says why work is throttled. */
export function pressure(s: ResourceSnapshot, c: ResourceConfig): string[] {
  const out: string[] = [];
  if (s.mem_free_gb < c.min_free_mem_gb) out.push(`Free memory ${s.mem_free_gb.toFixed(1)} GB < ${c.min_free_mem_gb} GB`);
  if (s.mem_pressure > c.max_memory_pressure) out.push(`Memory pressure level ${s.mem_pressure}`);
  if (s.cpu_load > c.max_cpu_load) out.push(`CPU load ${cpuText(s.cpu_load)} is over the ${Math.round(c.max_cpu_load * 100)}% limit`);
  if (s.gpu_util != null && s.gpu_util > c.max_gpu_util_pct) out.push(`GPU ${s.gpu_util}% > ${c.max_gpu_util_pct}%`);
  if (s.disk_free_gb < c.min_free_disk_gb) out.push(`Disk ${s.disk_free_gb.toFixed(0)} GB free < ${c.min_free_disk_gb} GB`);
  if (s.research_gb > c.research_disk_budget_gb) out.push(`Research cache ${s.research_gb.toFixed(1)} GB over budget`);
  if (c.pause_on_thermal && s.thermal && s.thermal !== "nominal") out.push(`Thermal state ${s.thermal}`);
  return out;
}

export const logsUrl = (source: string, o: { lines?: number; q?: string; level?: string } = {}) =>
  `/v1/machine/logs?${new URLSearchParams({ source, lines: String(o.lines ?? 300), ...(o.q ? { q: o.q } : {}), ...(o.level ? { level: o.level } : {}) })}`;

/** Load average per core as a percent of the whole CPU (J-087): capped at 100%, with the queue depth when oversubscribed. */
export function cpuText(loadPerCore: number): string {
  const pct = Math.min(100, Math.round(loadPerCore * 100));
  return loadPerCore > 1 ? `${pct}% (${loadPerCore.toFixed(1)}× queued)` : `${pct}%`;
}
