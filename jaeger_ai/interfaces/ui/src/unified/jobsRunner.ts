/** 24/7 job runner (GET /v1/jobs/runner): types + a pure summary for the Home tile. */
import type { Tone } from "./ui";

export type RunnerJob = {
  task_id: string; title?: string; state?: string; phase?: number; paused?: boolean; running?: boolean;
  videos_in_job?: number; item_count?: number; videos_done?: number; last_progress_s?: number; stuck?: boolean; error_count?: number;
  progress?: { steps_finished: number; steps_total: number };
};
export type RunnerStatus = { service: string; health: "ok" | "stuck" | "backoff" | "restarting" | "down" | string; heartbeat_age_s: number | null; jobs: RunnerJob[] };

export function summarizeRunner(s: RunnerStatus | undefined, err?: string): { value: string; tone?: Tone; hint: string; job?: RunnerJob } {
  if (err) return { value: "Unavailable", tone: "bad", hint: err };
  if (!s) return { value: "Checking…", hint: "GET /v1/jobs/runner" };
  const job = s.jobs[0];
  if (s.health === "down") return { value: "Runner stopped", tone: "bad", hint: `${s.service} has no fresh heartbeat`, job };
  if (!job) return { value: "Idle · queue empty", tone: "ok", hint: s.service, job };
  const total = job.item_count ?? job.videos_in_job ?? 0;
  const done = job.videos_done ?? 0;
  const pct = total ? Math.floor((done / total) * 100) : 0;
  const step = job.progress ? ` · batch ${job.progress.steps_finished}/${job.progress.steps_total} steps` : "";
  const base = `${done}/${total} videos (${pct}%)${step}`;
  if (job.paused) return { value: `Paused · ${base}`, tone: "warn", hint: "Click to resume", job };
  if (s.health === "stuck" || job.stuck) return { value: `Stuck · ${base}`, tone: "bad", hint: `No progress for ${Math.round((job.last_progress_s ?? 0) / 60)} min; the runner retries with backoff`, job };
  if (job.error_count) return { value: `${base} · ${job.error_count} errors`, tone: "warn", hint: "Click to pause", job };
  return { value: base, tone: "ok", hint: `${job.title ?? job.task_id} · phase ${job.phase ?? "–"} · click to pause`, job };
}
