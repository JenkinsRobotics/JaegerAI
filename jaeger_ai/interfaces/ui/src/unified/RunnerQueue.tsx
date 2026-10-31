/** Work › Pipeline: the 24/7 job runner's queue (GET /v1/jobs/runner) with per-job progress, stuck/backoff state, Pause/Resume and recent runner events. */
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty } from "./ui";
import { getJson, sendJson } from "./webui";
import { type RunnerJob, type RunnerStatus } from "./jobsRunner";
import "./usage.css";

export type RunnerDetail = RunnerStatus & { runner?: { pid?: number; events?: string[]; retries?: Record<string, number> } };

export function jobLine(j: RunnerJob): { label: string; tone?: "ok" | "warn" | "bad" } {
  const total = j.item_count ?? j.videos_in_job ?? 0; const done = j.videos_done ?? 0;
  const base = `${done}/${total} videos${j.progress ? ` · batch ${j.progress.steps_finished}/${j.progress.steps_total} steps` : ""}`;
  if (j.paused) return { label: `Paused · ${base}`, tone: "warn" };
  if (j.stuck) return { label: `Stuck ${Math.round((j.last_progress_s ?? 0) / 60)} min · ${base}`, tone: "bad" };
  if (j.error_count) return { label: `${base} · ${j.error_count} errors`, tone: "warn" };
  return { label: base, tone: j.running ? undefined : "ok" };
}

export function RunnerQueue({ onNavigate }: { onNavigate?: (to: string) => void }) {
  const [s, setS] = useState<RunnerDetail | null>(null); const [err, setErr] = useState<string>(); const [busy, setBusy] = useState<string>();
  const read = useCallback(() => getJson<RunnerDetail>("/v1/jobs/runner").then((x) => { setS(x); setErr(undefined); }, (e: Error) => setErr(e.message)), []);
  useEffect(() => { void read(); const t = setInterval(() => { if (!document.hidden) void read(); }, 15000); return () => clearInterval(t); }, [read]);
  const toggle = async (j: RunnerJob) => {
    setBusy(j.task_id);
    try { await sendJson("POST", `/v1/research/youtube/${encodeURIComponent(j.task_id)}/${j.paused ? "resume" : "pause"}`, {}); await read(); }
    catch (e) { setErr(String((e as Error).message ?? e)); } finally { setBusy(undefined); }
  };
  if (err && !s) return <section className="jg-u-card jg-runq" aria-label="Background jobs"><h2 className="jg-runq__title">Background jobs</h2><Empty title="Runner unavailable">{err}</Empty></section>;
  if (!s || typeof s.service !== "string") return null;
  const jobs = Array.isArray(s.jobs) ? s.jobs : [];
  const tone = s.health === "ok" ? "ok" : s.health === "down" ? "bad" : "warn";
  return (
    <section className="jg-u-card jg-runq" aria-label="Background jobs">
      <header className="jg-runq__head"><h2 className="jg-runq__title">Background jobs</h2>
        <Badge tone={tone}>{s.health === "ok" ? "Runner healthy" : `Runner ${s.health}`}</Badge>
        <span className="jg-runq__sub">{s.service}{s.heartbeat_age_s != null ? ` · heartbeat ${s.heartbeat_age_s}s ago` : ""}{s.runner?.pid ? ` · pid ${s.runner.pid}` : ""}</span></header>
      {jobs.length === 0 ? <Empty title="Queue empty" /> : <ul className="jg-runq__jobs">{jobs.map((j) => { const l = jobLine(j); return (
        <li key={j.task_id} className="jg-runq__job">
          <button className="jg-runq__name" onClick={() => onNavigate?.(`/research/youtube?job=${encodeURIComponent(j.task_id)}`)}>{j.title ?? j.task_id}</button>
          <Badge tone={l.tone}>{l.label}</Badge>
          <span className="jg-runq__sub">phase {j.phase ?? "–"}{s.runner?.retries?.[j.task_id] ? ` · ${s.runner.retries[j.task_id]} retries` : ""}</span>
          <button className="jg-u-btn" disabled={busy === j.task_id} onClick={() => void toggle(j)}>{j.paused ? "Resume" : "Pause"}</button>
        </li>); })}</ul>}
      {!!s.runner?.events?.length && <details className="jg-runq__events"><summary>Recent runner events ({s.runner.events.length})</summary><ol>{s.runner.events.slice(-12).reverse().map((e, i) => <li key={i}>{e}</li>)}</ol></details>}
    </section>
  );
}
