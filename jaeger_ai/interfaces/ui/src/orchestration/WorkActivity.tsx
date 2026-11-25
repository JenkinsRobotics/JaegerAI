import { useState } from "react";
import type { PendingApproval } from "../api/source";
import { Badge } from "../unified/ui";
import { LEAD_ID, relativeTime } from "./feed";
import { OutputLinkView, type Navigate } from "./OutputLinkView";
import type { ActivityRow, OrchestrationSnapshot } from "./types";
import { isInternalWork } from "../tasks/internalWork";

const active = new Set(["running", "working", "in_progress", "queued", "pending", "paused", "approved", "admitted"]);
const finished = new Set(["completed", "done", "failed", "cancelled", "canceled", "denied", "rejected"]);
const clean = (value: string) => value.trim().replace(/\s+/g, " ");
const short = (value: string, n = 100) => value.length > n ? value.slice(0, n - 1).trimEnd() + "…" : value;
const unix = (value = 0) => value > 1e12 ? value / 1000 : value;
type Bucket = "attention" | "active" | "recent";
type Job = { id: string; title: string; brief?: string; owner: string; state: string; at: number; bucket: Bucket; href?: string; action?: string; approvals: PendingApproval[]; workers: OrchestrationSnapshot["handoffs"]; events: ActivityRow[]; note?: string };

export function projectWork(snapshot: OrchestrationSnapshot, rows: ActivityRow[], stale = false): Job[] {
  const jobs = new Map<string, Job>();
  const requests = new Map<string, Job>();
  const sessions = new Map<string, Job[]>();
  const knownApprovals = !stale && Array.isArray(snapshot.approvals);
  const stateOf = (raw: string) => stale && (active.has(raw) || raw === "needs_owner" || raw === "pending_approval") ? "status_unknown" : raw === "pending_approval" ? "status_unknown" : raw;
  const bucketOf = (state: string): Bucket => state === "needs_owner" || state === "blocked" ? "attention" : active.has(state) ? "active" : "recent";
  for (const t of snapshot.tasks) {
    const brief = clean(t.provenance?.submission_goal || t.goal || "");
    if (isInternalWork(brief) || isInternalWork(t.goal)) continue;
    const state = stateOf(t.state ?? "status_unknown");
    const job: Job = { id: `task:${t.task_id}`, title: short(brief || "Untitled task"), brief, owner: t.agent_id ?? t.owning_agent ?? LEAD_ID, state, bucket: bucketOf(state), at: unix(t.updated_at ?? t.created_at), href: `/work/tasks?task=${encodeURIComponent(t.task_id)}`, action: finished.has(state) ? "View outcome" : "Open task", approvals: [], workers: [], events: [], note: t.error ? short(clean(t.error), 170) : undefined };
    jobs.set(job.id, job);
    if (t.provenance?.request_id) requests.set(t.provenance.request_id, job);
    if (t.provenance?.session_id) sessions.set(t.provenance.session_id, [...(sessions.get(t.provenance.session_id) ?? []), job]);
  }
  for (const h of snapshot.handoffs) {
    const brief = clean(h.task ?? "");
    if (isInternalWork(brief)) continue;
    const taskId = (h as typeof h & { task_id?: string }).task_id ?? h.metadata?.task_id;
    const related = typeof taskId === "string" ? jobs.get(`task:${taskId}`) : undefined;
    const parent = related ?? (h.parent_run_id ? requests.get(h.parent_run_id) : undefined);
    if (parent) { parent.workers.push(h); continue; }
    const state = stateOf(h.status ?? "status_unknown");
    jobs.set(`handoff:${h.id}`, { id: `handoff:${h.id}`, title: short(brief || "Delegated assignment"), brief, owner: h.to_agent_id ?? LEAD_ID, state, bucket: bucketOf(state), at: unix(h.updated_at ?? h.created_at), href: `handoff:${h.id}`, action: "View handoff", approvals: [], workers: [], events: [], note: h.result?.summary ? short(clean(h.result.summary), 170) : undefined });
  }
  const external = new Map<string, ActivityRow[]>();
  for (const row of rows) if (row.externalRun) {
    const group = external.get(row.externalRun.id) ?? [];
    group.push(row); external.set(row.externalRun.id, group);
  }
  for (const [id, updates] of external) {
    const ordered = updates.sort((a, b) => b.at - a.at);
    const last = ordered[0].externalRun!;
    const brief = clean(ordered.find(r => r.externalRun?.brief)?.externalRun?.brief ?? "");
    if (isInternalWork(brief)) continue;
    const existing = requests.get(id) ?? (last.session && sessions.get(last.session)?.length === 1 ? sessions.get(last.session)?.[0] : undefined);
    if (existing) { existing.events.push(...ordered); continue; }
    const state = active.has(last.status) ? "status_unknown" : last.status;
    const job: Job = { id: `external:${id}`, title: short(brief || "Work from a connected app"), brief, owner: last.owner, state, bucket: bucketOf(state), at: ordered[0].at, href: last.session ? `/chat?session=${encodeURIComponent(last.session)}` : undefined, action: "Open conversation", approvals: [], workers: [], events: ordered, note: ordered[0].callerId ? `From ${ordered[0].callerId === "mcp" ? "a connected app (MCP)" : ordered[0].callerId}` : undefined };
    jobs.set(job.id, job);
    requests.set(id, job);
    if (last.session) sessions.set(last.session, [...(sessions.get(last.session) ?? []), job]);
  }
  if (knownApprovals) for (const a of snapshot.approvals ?? []) {
    if (a.status !== "pending") continue;
    const candidates = a.session_id ? sessions.get(a.session_id) : undefined;
    let job = (a.task_id ? jobs.get(`task:${a.task_id}`) : undefined) ?? (a.request_id ? requests.get(a.request_id) : undefined) ?? (!a.request_id && candidates?.length === 1 ? candidates[0] : undefined);
    if (!job) {
      const id = `approval:${a.request_id || a.session_id || a.approval_id}`;
      job = jobs.get(id) ?? { id, title: short(clean(a.task || "Permission request")), owner: a.agent_id ?? LEAD_ID, state: "needs_approval", bucket: "attention", at: unix(a.created_at), approvals: [], workers: [], events: [] };
      jobs.set(id, job);
    }
    job.approvals.push(a);
    job.state = "needs_approval";
    job.bucket = "attention";
  }
  const workers = new Map([...jobs.values()].flatMap(job => job.workers.map(h => [h.id, job] as const)));
  for (const event of rows) {
    const job = (event.taskId && jobs.get(`task:${event.taskId}`)) || (event.handoffId && (jobs.get(`handoff:${event.handoffId}`) ?? workers.get(event.handoffId)));
    if (job) job.events.push(event);
  }
  return [...jobs.values()].sort((a, b) => b.at - a.at);
}

const statuses: Record<string, string> = { needs_approval: "Needs approval", needs_owner: "Needs you", blocked: "Blocked", running: "Running", working: "Running", in_progress: "Running", queued: "Queued", pending: "Queued", approved: "Queued", admitted: "Queued", paused: "Paused", done: "Completed", completed: "Completed", failed: "Failed", cancelled: "Cancelled", canceled: "Cancelled", denied: "Declined", rejected: "Declined", status_unknown: "Status unknown", execution_unknown: "Status unknown" };
const labelFor = (state: string) => statuses[state] ?? "Status unknown";
const tone = (state: string) => ["done", "completed"].includes(state) ? "ok" : ["failed", "blocked", "execution_unknown"].includes(state) ? "bad" : ["needs_approval", "needs_owner", "status_unknown"].includes(state) ? "warn" : undefined;
const buckets = [
  { id: "attention", title: "Needs you", empty: "Nothing needs your attention." },
  { id: "active", title: "Running & queued", empty: "No work is running or queued." },
  { id: "recent", title: "Recent results & other jobs", empty: "No recent jobs to show." },
] as const;

export function WorkActivity({ snapshot, rows, stale, names, onNavigate }: { snapshot: OrchestrationSnapshot; rows: ActivityRow[]; stale: boolean; names: (id: string) => string; onNavigate: Navigate }) {
  const jobs = projectWork(snapshot, rows, stale);
  const [showAll, setShowAll] = useState(false);
  return <section className="jg-orch-jobs" aria-label="Work and activity">
    <h2>Work and activity</h2>
    <p role="status">{stale ? "Current status unavailable. Showing the last known jobs." : "Job status refreshes automatically."}</p>
    {buckets.map(b => {
      const matching = jobs.filter(j => j.bucket === b.id);
      const visible = b.id === "recent" && !showAll ? matching.slice(0, 6) : matching;
      return <section key={b.id} aria-label={b.title}>
        <h3>{b.title}</h3>
        {!visible.length && <p>{b.id === "attention" && (stale || !Array.isArray(snapshot.approvals)) ? "Couldn't confirm open approvals." : b.empty}</p>}
        {visible.length > 0 && <ul className="jg-orch-rows">{visible.map(j => <li key={j.id} className="jg-orch-job">
          <details className="jg-orch-job__details">
            <summary className="jg-orch-job__head">
              <span className="jg-orch-job__identity">
                <strong title={j.title}>{j.title}</strong>
                <span className="jg-orch-job__meta">{names(j.owner)}{j.at ? ` · ${relativeTime(j.at)}` : ""}{j.workers.length ? ` · ${j.workers.length} helper${j.workers.length === 1 ? "" : "s"}` : ""}{j.approvals.length ? ` · ${j.approvals.length} open` : ""}</span>
              </span>
              <Badge tone={tone(j.state)}>{labelFor(j.state)}</Badge>
            </summary>
            <div className="jg-orch-job__body">
            {j.brief && <p>{j.brief}</p>}
            {j.note && <p>{j.note}</p>}
            {j.href && <button type="button" className="jg-u-btn" onClick={() => onNavigate(j.href!)}>{j.action}</button>}
            {j.approvals.map(a => <div key={a.approval_id}><p>{a.prompt}</p>{a.session_id && <button type="button" className="jg-u-btn" onClick={() => onNavigate(`/chat?session=${encodeURIComponent(a.session_id!)}`)}>Review in chat</button>}</div>)}
            {j.workers.map(h => <p key={h.id}>{names(h.to_agent_id ?? LEAD_ID)} · {labelFor(stale && active.has(h.status ?? "") ? "status_unknown" : h.status ?? "")} <button type="button" className="jg-u-btn" onClick={() => onNavigate(`handoff:${h.id}`)}>View assignment</button></p>)}
            {j.events.length > 0 && <details><summary>Event history</summary><ul>{j.events.map(e => <li key={e.key}>{names(e.agentId)} {e.action} {e.output && <OutputLinkView link={e.output} onNavigate={onNavigate} />}</li>)}</ul></details>}
            </div>
          </details>
        </li>)}</ul>}
        {b.id === "recent" && matching.length > 6 && <button type="button" className="jg-u-btn" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer jobs" : "Show older jobs"}</button>}
      </section>;
    })}
  </section>;
}
