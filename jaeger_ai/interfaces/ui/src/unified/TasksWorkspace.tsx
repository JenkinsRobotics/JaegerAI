/**
 * Tasks (unified UI): header with search, status and agent filters and a Board/List switch;
 * the board/list and the task inspector drawer (logs/steps, artifacts, approve/edit/cancel) come
 * from tasks/TasksBoard, so the gateway's proposal safety (receipts, reconciliation) is unchanged.
 * Deep links: /tasks?filter=needs, /tasks?task=<id>, /tasks?view=list.
 */
import { useCallback, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";
import { label } from "../agents/agentsLogic";
import { TasksBoard } from "../tasks/TasksBoard";
import { Segmented } from "./ui";

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
  const [view, setView] = useState<"board" | "list">(params.get("view") === "list" ? "list" : "board");
  const [agentId, setAgentId] = useState("");
  const [query, setQuery] = useState("");
  const [composer, setComposer] = useState(false);
  const [count, setCount] = useState<[number, number]>();
  const filter = useMemo(() => taskMatcher(status, agentId, query), [status, agentId, query]);
  const onCount = useCallback((a: number, b: number) => setCount((c) => (c && c[0] === a && c[1] === b ? c : [a, b])), []);
  const live = agents.filter((a) => !a.hidden && !a.deleted);
  return (
    <div className="jg-u-page jg-u-tasks">
      <header className="jg-u-page__head">
        <div><h1>Tasks</h1><p>{count ? `${count[0]} of ${count[1]} tasks` : "Background work, proposals that need your approval, and results."}</p></div>
        <div className="jg-ui-toolbar">
          <input className="jg-u-search" type="search" placeholder="Search tasks" aria-label="Search tasks" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="jg-u-search" aria-label="Filter by agent" value={agentId} onChange={(e) => setAgentId(e.target.value)} style={{ minWidth: 140 }}>
            <option value="">All agents</option>
            {live.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}
          </select>
          <Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "all", label: "All" }, { value: "needs", label: "Needs you" }, { value: "active", label: "Active" }, { value: "finished", label: "Finished" }]} />
          <Segmented label="View" value={view} onChange={setView} options={[{ value: "board", label: "Board" }, { value: "list", label: "List" }]} />
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/tasks/gallery")}>Gallery</button>
          {source.taskActions && source.agentHome && <button type="button" className="jg-u-btn jg-u-btn--primary" aria-pressed={composer} onClick={() => setComposer((v) => !v)}>{composer ? "Close" : "New task"}</button>}
        </div>
      </header>
      <TasksBoard source={source} agents={agents} view={view} filter={filter} initialTaskId={params.get("task")} composer={composer} bare onCount={onCount} />
    </div>
  );
}
