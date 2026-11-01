/** Backlog API (gateway /v1/backlog via the WebUI passthrough; owner caller). */
import { getJson, sendJson } from "./webui";

export type BacklogStatus = "open" | "in_progress" | "needs_ok" | "done";
export type BacklogPriority = "P0" | "P1" | "P2";
export interface BacklogTask {
  id: string; title: string; detail: string; source: string; status: BacklogStatus; priority: BacklogPriority;
  worker: string; handoff_id: string | null; handoff_thread: string | null; last_note: string; created_at: number; updated_at: number;
}
export interface BacklogList { tasks: BacklogTask[]; counts: Partial<Record<BacklogStatus, number>>; now: number }

export const STATUSES: { value: BacklogStatus; label: string }[] = [
  { value: "needs_ok", label: "Needs OK" }, { value: "in_progress", label: "In progress" }, { value: "open", label: "Open" }, { value: "done", label: "Done" },
];
export const PRIORITIES: BacklogPriority[] = ["P0", "P1", "P2"];
export const WORKERS: { value: string; label: string }[] = [
  { value: "ares", label: "ARES" }, { value: "muse", label: "Muse" }, { value: "rackpc", label: "Rack PC" }, { value: "grokbot", label: "Grok Bot" },
];
export const workerLabel = (w: string) => WORKERS.find((x) => x.value === w)?.label ?? (w || "Unassigned");
export const statusLabel = (s: string) => STATUSES.find((x) => x.value === s)?.label ?? s;

export const backlogApi = {
  list: (signal?: AbortSignal) => getJson<BacklogList>("/v1/backlog?limit=1000", signal),
  add: (t: { title: string; detail?: string; priority?: BacklogPriority; worker?: string }) => sendJson<{ task: BacklogTask }>("POST", "/v1/backlog", { ...t, source: "Matthew (Jaeger)" }),
  update: (id: string, changes: Partial<Pick<BacklogTask, "title" | "detail" | "status" | "priority" | "worker">>) => sendJson<{ task: BacklogTask }>("POST", `/v1/backlog/${encodeURIComponent(id)}`, changes),
  assign: (id: string, worker: string) => sendJson<{ task: BacklogTask; handoff: { id: string; thread: string; to: string } }>("POST", `/v1/backlog/${encodeURIComponent(id)}/assign`, { worker }),
  importFile: () => sendJson<{ added: number; skipped: number }>("POST", "/v1/backlog/import", {}),
};

export interface BacklogFilter { status: string; priority: string; worker: string; q: string }
export function matchBacklog(f: BacklogFilter) {
  const q = f.q.trim().toLowerCase();
  return (t: BacklogTask) => (!f.status || (f.status === "active" ? t.status !== "done" : t.status === f.status))
    && (!f.priority || t.priority === f.priority)
    && (!f.worker || (f.worker === "none" ? !t.worker : t.worker === f.worker))
    && (!q || `${t.title} ${t.detail} ${t.source} ${t.id}`.toLowerCase().includes(q));
}
