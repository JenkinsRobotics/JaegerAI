/* Pure mappers: EXISTING gateway records + events → activity rows, checks and
 * output links. No I/O here; adapter.ts feeds it. */
import type { Agent, GatewayEvent, Handoff, Task } from "../api/types";
import { label } from "../agents/agentsLogic";
import type { ActivityItem, ActivityKind, ActivityRow, ArtifactRef, CheckRecord, CheckState, HandoffCheck, OutputLink } from "./types";

export const LEAD_ID = "native:jaeger";
type Names = (id: string) => string;

const sec = (t?: number | null) => (t ? (t > 1e12 ? t / 1000 : t) : 0);
const PASSED = new Set(["completed_verified"]);
const FAILED = new Set(["failed", "blocked", "cancelled"]);
const PENDING = new Set(["queued", "running", "needs_owner", "paused", "completed", "done"]);

export function taskLink(task: Pick<Task, "task_id" | "goal">): OutputLink {
  return { kind: "task", label: task.goal ? `Task: ${task.goal}` : `Task ${task.task_id}`, href: `/work/tasks?task=${encodeURIComponent(task.task_id)}` };
}
export function handoffLink(h: Pick<Handoff, "id" | "task">): OutputLink {
  return { kind: "handoff", label: "Exchange", href: `handoff:${h.id}` };
}
export function sessionLink(agentId: string, label = "Conversation"): OutputLink {
  return { kind: "session", label, href: `/chat?agent=${encodeURIComponent(agentId)}` };
}

/** GAP G5: explicit handoff↔task link. Until it ships, match the task whose
 * provenance request_id equals the handoff's request_id. */
export function taskForHandoff(h: Handoff, tasks: Task[]): Task | undefined {
  const linked = (h as Handoff & { task_id?: string }).task_id;
  if (linked) return tasks.find((t) => t.task_id === linked);
  if (!h.request_id) return undefined;
  return tasks.find((t) => t.provenance?.request_id === h.request_id);
}

const HTTPS = /^https:\/\//i;
const HTTP = /^http:\/\//i;
const base = (path: string) => path.split("/").filter(Boolean).pop() ?? path;

/** G2 `evidence_ref`: `task:T1 | handoff:h1 | url:https://… | file:path@sha256`. */
export function parseEvidence(ref?: string | null): OutputLink | undefined {
  if (!ref) return undefined;
  const i = ref.indexOf(":");
  const scheme = i > 0 ? ref.slice(0, i) : "";
  const rest = i > 0 ? ref.slice(i + 1) : ref;
  switch (scheme) {
    case "task": return { ...taskLink({ task_id: rest }), label: "Evidence: task" };
    case "handoff": return { kind: "handoff", label: "Evidence: exchange", href: `handoff:${rest}` };
    case "url": return HTTPS.test(rest) ? { kind: "url", label: "Evidence", href: rest } : { kind: "url", label: rest, href: rest, copy: true };
    case "file": { const at = rest.lastIndexOf("@"); const path = at > 0 ? rest.slice(0, at) : rest; return { kind: "file", label: base(path), href: path, sha: at > 0 ? rest.slice(at + 1) : undefined, copy: true }; }
    default: return HTTPS.test(ref) ? { kind: "url", label: "Evidence", href: ref } : { kind: "url", label: ref, href: ref, copy: true };
  }
}

/** G2: prefer the gateway's check record; else derive from the linked task. */
export function checkFor(h: Handoff, tasks: Task[]): HandoffCheck {
  const recorded = (h as Handoff & { check?: CheckRecord | null }).check;
  if (recorded?.state) {
    return {
      state: recorded.state, source: "gateway", checkedBy: recorded.checked_by ?? undefined, checkedAt: recorded.checked_at ?? undefined,
      note: recorded.note ?? undefined, evidence: parseEvidence(recorded.evidence_ref),
    };
  }
  const task = taskForHandoff(h, tasks);
  if (!task?.state) return { state: "unchecked", source: "derived" };
  const state: CheckState = PASSED.has(task.state) ? "passed" : FAILED.has(task.state) ? "failed" : PENDING.has(task.state) ? "pending" : "unchecked";
  return { state, source: "derived", evidence: taskLink(task), checkedAt: sec(task.updated_at) || undefined };
}

/** G3: typed artifacts. https (`ref` or optional `url`) is a link; sessions and
 * tasks route in-app; files, commits and http links are copy chips. */
export function artifactsFor(h: Handoff): OutputLink[] {
  const refs = (h.result as { artifact_refs?: Partial<ArtifactRef>[] } | null | undefined)?.artifact_refs;
  if (!Array.isArray(refs)) return [];
  return refs.flatMap((r): OutputLink[] => {
    if (!r?.ref) return [];
    const kind = (["file", "commit", "session", "task", "url"].includes(String(r.kind)) ? r.kind : "url") as ArtifactRef["kind"];
    const sha = r.sha ?? undefined; const verified = r.verified;
    const label = r.title ?? (kind === "commit" ? r.ref.slice(0, 8) : kind === "file" ? base(r.ref) : kind === "session" ? "Worker session" : r.ref);
    if (r.url && HTTPS.test(r.url)) return [{ kind, label, href: r.url, sha, verified }];
    if (kind === "session") return h.to_agent_id ? [{ ...sessionLink(h.to_agent_id, label), verified }] : [];
    if (kind === "task") return [{ ...taskLink({ task_id: r.ref }), label: r.title ?? "Task", verified }];
    if (kind === "url") return HTTPS.test(r.ref) ? [{ kind, label, href: r.ref, verified }] : HTTP.test(r.ref) ? [{ kind, label, href: r.ref, copy: true, verified }] : [];
    return [{ kind, label, href: r.ref, sha, copy: true, verified }];
  });
}

function handoffKind(status?: string): ActivityKind {
  if (status === "failed" || status === "cancelled" || status === "rejected") return "handoff.failed";
  if (status === "completed" || status === "done" || status === "finished") return "handoff.finished";
  return "handoff.started";
}

export function handoffRows(h: Handoff, tasks: Task[], names: Names): ActivityRow[] {
  const to = h.to_agent_id ?? "unknown";
  const from = h.from_agent_id ?? LEAD_ID;
  const check = checkFor(h, tasks);
  const rows: ActivityRow[] = [{
    key: `handoff.started:${h.id}`, kind: "handoff.started", agentId: from, handoffId: h.id,
    action: `handed off to ${names(to)}${h.task ? `: ${h.task}` : ""}`, at: sec(h.created_at ?? h.updated_at), output: handoffLink(h), check,
  }];
  const kind = handoffKind(h.status);
  if (kind !== "handoff.started") {
    const artifact = artifactsFor(h)[0];
    rows.push({
      key: `${kind}:${h.id}`, kind, agentId: to, handoffId: h.id,
      action: kind === "handoff.failed" ? `couldn't finish${h.result?.summary ? `: ${h.result.summary}` : ""}` : `finished${h.result?.summary ? `: ${h.result.summary}` : ""}`,
      at: sec(h.updated_at ?? h.created_at), output: artifact ?? handoffLink(h), check, needsYou: kind === "handoff.failed" || check.state === "failed",
    });
  }
  return rows;
}

export function taskRow(t: Task): ActivityRow {
  const agentId = t.agent_id ?? t.owning_agent ?? LEAD_ID;
  const state = t.state ?? "updated";
  return {
    key: `task:${t.task_id}:${state}`, kind: "task.updated", agentId, taskId: t.task_id,
    action: `${state === "queued" ? "queued" : state === "running" ? "is working on" : state.replace(/_/g, " ")} ${t.goal ? `“${t.goal}”` : "a task"}`,
    at: sec(t.updated_at ?? t.created_at), output: taskLink(t), needsYou: state === "needs_owner",
  };
}

/** One live gateway event → zero or one row. Unknown events are ignored. */
export function eventRow(e: GatewayEvent, names: Names): ActivityRow | null {
  const p = (e.payload ?? {}) as Record<string, unknown>;
  const at = sec((typeof p.at === "number" ? p.at : undefined) ?? (e.created_at as number | undefined) ?? Date.now() / 1000);
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  switch (e.event) {
    case "agent.handoff":
    case "agent.handoff.finished": {
      const h = (p.handoff && typeof p.handoff === "object" ? p.handoff : p) as Handoff;
      if (!h.id) return null;
      const done = e.event === "agent.handoff.finished";
      const status = done ? (h.status ?? "completed") : "started";
      const [row] = handoffRows({ ...h, status, updated_at: at, created_at: h.created_at ?? at }, [], names).filter((r) => (done ? r.kind !== "handoff.started" : r.kind === "handoff.started"));
      return row ? { ...row, at } : null;
    }
    case "agent.handoff.checked": { // G2 event: {handoff: <handoff with check>}
      const h = (p.handoff && typeof p.handoff === "object" ? p.handoff : null) as (Handoff & { check?: CheckRecord }) | null;
      if (!h?.id || !h.check?.state) return null;
      const check = checkFor(h, []);
      const by = h.check.checked_by ?? "";
      return {
        key: `handoff.checked:${h.id}:${check.state}`, kind: "handoff.checked", agentId: by.startsWith("owner:") || by === "gateway" || !by ? LEAD_ID : by, handoffId: h.id, at,
        action: `check ${check.state}${h.task ? ` on “${h.task}”` : ""}${check.note ? `: ${check.note}` : ""}`, check,
        output: check.evidence ?? { kind: "handoff", label: "Exchange", href: `handoff:${h.id}` }, needsYou: check.state === "failed",
      };
    }
    case "task.created":
    case "task.updated": {
      const t = (p.task && typeof p.task === "object" ? p.task : p) as Task;
      return t.task_id ? { ...taskRow(t), kind: e.event, at } : null;
    }
    case "approval.request": {
      const id = str(p.approval_id ?? p.id);
      return id ? { key: `approval:${id}`, kind: "approval.requested", agentId: str(p.agent_id) || LEAD_ID, at, action: `asked for approval${str(p.title ?? p.tool) ? `: ${str(p.title ?? p.tool)}` : ""}`, needsYou: true, output: { kind: "approval", label: "Review", href: e.session_id && e.session_id !== "*" ? `/chat?agent=${encodeURIComponent(str(p.agent_id) || LEAD_ID)}` : "/home" } } : null;
    }
    case "approval.resolved": {
      const id = str(p.approval_id ?? p.id);
      return id ? { key: `approval:${id}:resolved`, kind: "approval.resolved", agentId: str(p.agent_id) || LEAD_ID, at, action: `approval ${str(p.decision) || "resolved"}` } : null;
    }
    case "agent.status.changed": { // G6 event; time in payload.at
      const id = str(p.agent_id ?? p.id);
      const text: Record<string, string> = { waiting_approval: "is waiting for approval", blocked: "is blocked", error: "hit an error", working: "is working", queued: "is queued", idle: "is idle" };
      const hid = str(p.handoff_id), tid = str(p.task_id);
      return id ? { key: `status:${id}:${str(p.status)}:${Math.floor(at)}`, kind: "agent.status", agentId: id, at, action: text[str(p.status)] ?? `is ${str(p.status).replace(/_/g, " ") || "idle"}`,
        handoffId: hid || undefined, taskId: tid || undefined,
        output: hid ? { kind: "handoff", label: "Exchange", href: `handoff:${hid}` } : tid ? taskLink({ task_id: tid }) : undefined,
        needsYou: str(p.status) === "waiting_approval" || undefined } : null;
    }
    default:
      return null;
  }
}

/** Merge rows by key (newer wins), newest first, capped. */
export function mergeRows(current: ActivityRow[], incoming: ActivityRow[], cap = 300): ActivityRow[] {
  const byKey = new Map(current.map((r) => [r.key, r]));
  for (const row of incoming) {
    const prev = byKey.get(row.key);
    if (!prev || row.at >= prev.at) byKey.set(row.key, prev ? { ...prev, ...row } : row);
  }
  return [...byKey.values()].sort((a, b) => b.at - a.at).slice(0, cap);
}

export function backfill(snapshot: { handoffs: Handoff[]; tasks: Task[] }, names: Names): ActivityRow[] {
  return mergeRows([], [...snapshot.handoffs.flatMap((h) => handoffRows(h, snapshot.tasks, names)), ...snapshot.tasks.map(taskRow)]);
}

/** G1 item → row: same mapper as the live stream, plus the gateway's
 * summary/needs_me when the payload alone isn't enough. */
export function activityItemRow(item: ActivityItem, names: Names): ActivityRow | null {
  const row = eventRow({ event: item.kind, event_id: item.event_id, created_at: item.ts, session_id: item.session_id ?? undefined, payload: item.data ?? {} }, names);
  const needsYou = item.needs_me || undefined;
  if (row) return { ...row, at: sec(item.ts), needsYou: needsYou ?? row.needsYou };
  if (!item.summary) return null;
  const r = item.refs ?? {};
  return {
    key: `activity:${item.event_id}`, kind: "agent.status", agentId: item.agent_id, at: sec(item.ts), action: item.summary, needsYou,
    handoffId: r.handoff_id ?? undefined, taskId: r.task_id ?? undefined,
    output: r.handoff_id ? { kind: "handoff", label: "Exchange", href: `handoff:${r.handoff_id}` } : r.task_id ? taskLink({ task_id: r.task_id }) : undefined,
  };
}

/** G6 status vocabulary → dot tone. */
export function statusTone(status: string): "ok" | "warn" | "bad" | "idle" {
  if (status === "working") return "ok";
  if (status === "waiting_approval" || status === "blocked") return "warn";
  if (status === "error") return "bad";
  return "idle";
}

export function relativeTime(at: number, now = Date.now() / 1000): string {
  const d = Math.max(0, now - at);
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)}m`;
  if (d < 86400) return `${Math.round(d / 3600)}h`;
  return `${Math.round(d / 86400)}d`;
}

export const namesFrom = (agents: Agent[]): Names => {
  const map = new Map(agents.map((a) => [a.id, label(a)]));
  return (id) => map.get(id) ?? id;
};
