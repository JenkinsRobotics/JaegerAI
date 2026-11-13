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
  // G5 (real): handoff.task_id, then task.handoff_id; fallback: request_id match.
  const linked = (h as Handoff & { task_id?: string | null }).task_id ?? (h.metadata?.task_id as string | undefined);
  if (linked) return tasks.find((t) => t.task_id === linked);
  const back = tasks.find((t) => (t as Task & { handoff_id?: string | null }).handoff_id === h.id);
  if (back) return back;
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

/** Handoff statuses (gateway vocabulary) that end without a usable result. */
export const HANDOFF_FAILED = new Set(["failed", "cancelled", "rejected", "denied", "execution_unknown"]);
const HANDOFF_DONE = new Set(["completed", "done", "finished"]);

/** G2: prefer the gateway's check record; else derive like the gateway's
 * defaults (failed-ish → failed, completed → pending; never passed), with a
 * linked task's state taking over when present. */
export function checkFor(h: Handoff, tasks: Task[]): HandoffCheck {
  const recorded = (h as Handoff & { check?: CheckRecord | null }).check;
  if (recorded?.state) {
    return {
      state: recorded.state, source: "gateway", checkedBy: recorded.checked_by ?? undefined, checkedAt: recorded.checked_at ?? undefined,
      note: recorded.note ?? undefined, evidence: parseEvidence(recorded.evidence_ref),
    };
  }
  const status = String(h.status ?? "");
  if (HANDOFF_FAILED.has(status)) return { state: "failed", source: "derived", evidence: handoffLink(h) };
  const task = taskForHandoff(h, tasks);
  if (!task?.state) return { state: HANDOFF_DONE.has(status) ? "pending" : "unchecked", source: "derived" };
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

const FAILED_TEXT: Record<string, string> = { denied: "was denied", execution_unknown: "ended with an unknown outcome", cancelled: "was cancelled", rejected: "was rejected" };

function handoffKind(status?: string): ActivityKind {
  if (HANDOFF_FAILED.has(String(status))) return "handoff.failed";
  if (HANDOFF_DONE.has(String(status))) return "handoff.finished";
  return "handoff.started";
}

export function handoffRows(h: Handoff, tasks: Task[], names: Names): ActivityRow[] {
  const to = h.to_agent_id ?? "unknown";
  const from = h.from_agent_id ?? LEAD_ID;
  const check = checkFor(h, tasks);
  const rows: ActivityRow[] = [{
    key: `handoff.started:${h.id}`, kind: "handoff.started", agentId: from, handoffId: h.id,
    action: `handed off to ${names(to)}${h.status === "pending_approval" ? " (waiting for your approval)" : ""}${h.task ? `: ${h.task}` : ""}`, at: sec(h.created_at ?? h.updated_at), output: handoffLink(h), check,
    needsYou: h.status === "pending_approval" || undefined,
  }];
  const kind = handoffKind(h.status);
  if (kind !== "handoff.started") {
    const artifact = artifactsFor(h)[0];
    rows.push({
      key: `${kind}:${h.id}`, kind, agentId: to, handoffId: h.id,
      action: kind === "handoff.failed" ? `${FAILED_TEXT[String(h.status)] ?? "couldn't finish"}${h.result?.summary ? `: ${h.result.summary}` : ""}` : `finished${h.result?.summary ? `: ${h.result.summary}` : ""}`,
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
    case "handoff.sent":
    case "handoff.result":
      return hubHandoffRow(e.event, p, at, names);
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
      return id ? { key: `approval:${id}`, kind: "approval.requested", agentId: str(p.agent_id) || LEAD_ID, at, action: `asked for approval${str(p.title ?? p.prompt ?? p.tool ?? p.task) ? `: ${str(p.title ?? p.prompt ?? p.tool ?? p.task).slice(0, 160)}` : ""}`, needsYou: true, output: { kind: "approval", label: "Review", href: e.session_id && e.session_id !== "*" ? `/chat?agent=${encodeURIComponent(str(p.agent_id) || LEAD_ID)}` : "/home" } } : null;
    }
    case "approval.reviewed": {
      const verdict = str(p.verdict) || "unsure";
      const reason = str(p.reason);
      const tool = str(p.tool);
      return { key: `approval-reviewed:${str(p.request_id) || str(p.approval_id) || at}:${verdict}`, kind: "approval.reviewed", agentId: str(p.agent_id) || LEAD_ID, at, action: `reviewer ${verdict}${tool ? ` ${tool}` : ""}${reason ? `: ${reason.slice(0, 160)}` : ""}` };
    }
    case "approval.resolved": {
      const id = str(p.approval_id ?? p.id);
      return id ? { key: `approval:${id}:resolved`, kind: "approval.resolved", agentId: str(p.agent_id) || LEAD_ID, at, action: `approval ${str(p.decision) || (p.approved === true ? "granted" : p.approved === false ? "declined" : "resolved")}` } : null;
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
    case "turn.start": case "turn.finish": case "turn.failed": case "turn.cancelled": case "turn.unknown": {
      return callerGoalRow(e, p, at, names);
    }
    case "project.checked": { // {project_id, result{ok, status?, checked_at}}
      const r = (p.result && typeof p.result === "object" ? p.result : {}) as { ok?: boolean; status?: string; checked_at?: number; agent_id?: string; checked_by?: string };
      const project = str(p.project_id);
      if (!project) return null;
      const state: CheckState = r.ok === true ? "passed" : r.ok === false ? "failed" : "pending";
      const when = sec(r.checked_at) || at;
      const by = r.agent_id || (r.checked_by && !r.checked_by.startsWith("owner:") ? r.checked_by : "") || LEAD_ID;
      return {
        key: `project.checked:${project}:${e.event_id ?? Math.floor(when)}`, kind: "project.checked", agentId: by, at: when,
        action: `checked project ${project}: ${r.status || (state === "pending" ? "checked" : state)}`,
        check: { state, source: "gateway", checkedBy: r.checked_by, checkedAt: when }, needsYou: state === "failed" || undefined,
      };
    }
    default:
      return null;
  }
}

const HUB_FAILED = new Set([...HANDOFF_FAILED, "error", "blocked"]);

/** Hub (Gateway & WebUI) handoff.sent / handoff.result → the same keys as
 * agent.handoff rows (`handoff.started:<id>`, `handoff.finished|failed:<id>`)
 * so mergeRows dedupes them. Sent: caller → recipient. Result: the caller is
 * the worker posting back to the recipient (the original sender). */
function hubHandoffRow(kind: string, p: Record<string, unknown>, at: number, names: Names): ActivityRow | null {
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const caller = (p.caller && typeof p.caller === "object" ? p.caller : {}) as { caller_id?: string; caller_kind?: string };
  const id = str(p.handoff_id), by = str(caller.caller_id), recipient = str(p.recipient);
  if (!id || !by) return null;
  const title = str(p.title) || undefined;
  const paths = Array.isArray(p.refs) ? p.refs.filter((r): r is string => typeof r === "string" && r.length > 0).slice(0, 16) : [];
  const artifact_refs = paths.map((ref): ArtifactRef => (/^https?:\/\//i.test(ref) ? { kind: "url", ref } : { kind: "file", ref }));
  const sent = kind === "handoff.sent";
  const raw = str(p.status);
  const status = sent ? "started" : HUB_FAILED.has(raw) ? (HANDOFF_FAILED.has(raw) ? raw : "failed") : "completed";
  const h: Handoff = sent
    ? { id, from_agent_id: by, to_agent_id: recipient, task: title, status: "running", created_at: at, updated_at: at }
    : { id, from_agent_id: recipient, to_agent_id: by, status, result: { summary: title, artifact_refs } as Handoff["result"], created_at: at, updated_at: at };
  const rows = handoffRows({ ...h, status }, [], names);
  const row = sent ? rows.find((r) => r.kind === "handoff.started") : rows.find((r) => r.kind !== "handoff.started");
  if (!row) return null;
  const pill = !sent && raw && !HANDOFF_DONE.has(raw) && !HUB_FAILED.has(raw) ? { text: raw.replace(/_/g, " ") } : undefined;
  return { ...row, at, handoff: h, callerId: by, ...(pill ? { statusPill: pill } : {}) };
}

/** Details-panel handoff for an id: the gateway record when listed, else one
 * merged from hub rows (sent gives task/route, result gives status/outputs). */
export function handoffForId(id: string | undefined, listed: Handoff[], rows: ActivityRow[]): Handoff | undefined {
  if (!id) return undefined;
  const hub = rows.filter((r) => r.handoffId === id && r.handoff).sort((a, b) => a.at - b.at).map((r) => r.handoff!);
  const found = listed.find((h) => h.id === id);
  const refs = hub.map((h) => (h.result as { artifact_refs?: ArtifactRef[] } | null | undefined)?.artifact_refs).find((r) => r?.length);
  if (found) {
    const own = (found.result as { artifact_refs?: ArtifactRef[] } | null | undefined)?.artifact_refs;
    return refs && !own?.length ? { ...found, result: { ...(found.result ?? {}), artifact_refs: refs } as Handoff["result"] } : found;
  }
  if (!hub.length) return undefined;
  const sent = hub.find((h) => h.task !== undefined);
  const merged = hub.reduce((acc, h) => ({ ...acc, ...Object.fromEntries(Object.entries(h).filter(([, v]) => v !== undefined)) }), {} as Handoff);
  return sent ? { ...merged, from_agent_id: sent.from_agent_id, to_agent_id: sent.to_agent_id, task: sent.task } : merged;
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

const GOAL_STATUS: Record<string, { text: string; tone?: "ok" | "warn" | "bad" }> = {
  running: { text: "Running", tone: "warn" }, completed: { text: "Completed", tone: "ok" }, failed: { text: "Failed", tone: "bad" },
  cancelled: { text: "Cancelled", tone: "bad" }, execution_unknown: { text: "Outcome unknown", tone: "bad" },
};
const TURN_STATUS: Record<string, string> = { "turn.start": "running", "turn.finish": "completed", "turn.failed": "failed", "turn.cancelled": "cancelled", "turn.unknown": "execution_unknown" };

/** "codex" → "Codex"; A2A callers are marked. */
export function callerName(id: string, kind?: string): string {
  const base = id.replace(/^agent:/, "").split(":")[0] || id;
  return base.charAt(0).toUpperCase() + base.slice(1) + (kind === "a2a" ? " (A2A)" : "");
}

/** turn.* rows for outside-caller sessions (MCP/A2A goals). Owner chat turns
 * have no data.caller and are ignored. */
function callerGoalRow(e: GatewayEvent, p: Record<string, unknown>, at: number, names: Names): ActivityRow | null {
  const c = (p.caller && typeof p.caller === "object" ? p.caller : null) as { caller_id?: string; caller_kind?: string; session_id?: string; request_id?: string; status?: string; goal_id?: string | null; thread?: string | null; agent_id?: string | null } | null;
  if (!c?.caller_id) return null;
  const status = c.status || TURN_STATUS[e.event] || "running";
  const to = c.agent_id || LEAD_ID;
  const id = c.goal_id || c.request_id || c.session_id || String(e.event_id ?? at);
  const text = typeof p.error === "string" ? p.error : typeof p.text === "string" ? p.text : "";
  return {
    key: `goal:${id}:${status}`, kind: "caller.goal", agentId: c.caller_id, callerId: c.caller_id, at,
    action: `${c.caller_kind === "a2a" ? "(A2A) " : ""}→ ${names(to)} goal${c.goal_id ? ` ${c.goal_id}` : ""}${c.thread ? ` (${c.thread})` : ""}${text ? `: ${text.slice(0, 300)}` : ""}`,
    statusPill: GOAL_STATUS[status] ?? { text: status.replace(/_/g, " ") },
    output: sessionLink(to, `Open ${names(to)}`),
    needsYou: status === "failed" || status === "execution_unknown" || undefined,
  };
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
  const map = new Map<string, string>([["widget", "A widget"], ["automation", "An automation"], ...agents.map((a): [string, string] => [a.id, label(a)])]);
  return (id) => map.get(id) ?? (/^(native|specialist|tp):/.test(id) ? id : callerName(id));
};
