/**
 * Tasks (unified UI): header with search, status and agent filters and a Board/List switch;
 * the board/list and the task inspector drawer (logs/steps, artifacts, approve/edit/cancel) come
 * from tasks/TasksBoard, so the gateway's proposal safety (receipts, reconciliation) is unchanged.
 * A status strip (gateway, Tailscale, Focus, research jobs, approvals) sits under the header.
 * Deep links: /tasks?filter=needs, /tasks?task=<id>, /tasks?view=list.
 */
import { useCallback, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { TasksBoard } from "../tasks/TasksBoard";
import { isInternalWork } from "../tasks/internalWork";
import { Segmented, PageHead } from "./ui";
import "./workWorkspace.css";

export const TASK_FILTERS = {
  all: () => true,
  needs: (t: Task) => ["needs_owner", "paused", "blocked", "waiting_approval"].includes(String(t.state)),
  active: (t: Task) => ["running", "queued"].includes(String(t.state)),
  finished: (t: Task) => ["done", "completed", "completed_verified", "failed", "cancelled"].includes(String(t.state)),
} as const;
export type TaskFilter = keyof typeof TASK_FILTERS;

export function taskMatcher(status: TaskFilter, agentId: string, query: string) {
  const q = query.trim().toLowerCase();
  return (t: Task) => TASK_FILTERS[status](t)
    && (!agentId || (t.agent_id ?? t.owning_agent) === agentId)
    && (!q || `${t.goal ?? ""} ${t.task_id}`.toLowerCase().includes(q));
}

export function TasksWorkspace({ source, agents, params, onNavigate }: { source: JaegerSource; agents: Agent[]; params: URLSearchParams; onNavigate: (to: string) => void }) {
  const initialFilter = params.get("filter");
  const [status, setStatus] = useState<TaskFilter>(initialFilter && initialFilter in TASK_FILTERS ? initialFilter as TaskFilter : "all");
  const [view, setView] = useState<"board" | "list">(params.get("view") === "board" ? "board" : "list");
  const [agentId, setAgentId] = useState("");
  const [query, setQuery] = useState("");
  const [composer, setComposer] = useState(false);
  const [showMaintenance, setShowMaintenance] = useState(false);
  const [count, setCount] = useState<[number, number]>();
  const filter = useMemo(() => {
    const matches = taskMatcher(status, agentId, query);
    return (t: Task) => matches(t) && (showMaintenance || (!isInternalWork(t.goal) && !isInternalWork(t.provenance?.submission_goal)));
  }, [status, agentId, query, showMaintenance]);
  const onCount = useCallback((a: number, b: number) => setCount((c) => (c && c[0] === a && c[1] === b ? c : [a, b])), []);
  const live = agents.filter(a => !a.deleted && visible(a));
  return (
    <div className="jg-u-page jg-u-tasks jg-work-density">
      <PageHead title="Tasks" subtitle="See what needs you, what’s moving, and what’s done." actions={<>
        {source.workflows && <button type="button" className="jg-u-btn" onClick={() => onNavigate("/work/tasks/workflows")}>Saved workflows</button>}
        <button type="button" className="jg-u-btn" onClick={() => onNavigate("/work/process")}>Inspect runs</button>
        {source.taskActions && source.agentHome && <button type="button" className="jg-u-btn jg-u-btn--primary" aria-pressed={composer} onClick={() => setComposer((v) => !v)}>{composer ? "Close task form" : "New task"}</button>}
      </>} />
      <div className="jg-work-toolbar">
        <Segmented label="Task status" value={status} onChange={setStatus} options={[{ value: "all", label: "All" }, { value: "needs", label: "Needs you" }, { value: "active", label: "Active" }, { value: "finished", label: "Finished" }]} />
        <Segmented label="Task layout" value={view} onChange={setView} options={[{ value: "list", label: "List" }, { value: "board", label: "Board" }]} />
      </div>
      <div className="jg-work-toolbar">
          <input className="jg-u-search" type="search" placeholder="Search tasks" aria-label="Search tasks" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="jg-u-search jg-minw-select" aria-label="Filter by agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">All agents</option>
            {live.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}
          </select>
          {count && <small className="jg-u-note" role="status">{count[0]} {count[0] === 1 ? "task" : "tasks"} shown</small>}
      </div>
      <TasksBoard source={source} agents={agents} view={view} filter={filter} initialTaskId={params.get("task")} composer={composer} bare onCount={onCount}
        onInspectRun={t => {
          const link = new URLSearchParams({ session: t.provenance!.session_id!, task: t.task_id });
          if (t.provenance?.request_id) link.set("run", t.provenance.request_id);
          onNavigate(`/work/process?${link}`);
        }} />
      <details className="jg-work-secondary"><summary>Extra views</summary>
        <label className="jg-u-check"><input type="checkbox" checked={showMaintenance} onChange={e => setShowMaintenance(e.target.checked)} /> Include background maintenance</label>
        <button type="button" className="jg-u-btn" onClick={() => onNavigate("/work/tasks/gallery")}>Task gallery</button>
      </details>
    </div>
  );
}
