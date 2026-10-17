/* Basic Tasks board. A typed port of the kanban columns in
 * features/webui/static/panels.js (_kanbanBoard), fed from GET /v1/tasks with
 * agent_id / eta / runner (rev 5, TB2). */
import { useEffect, useState } from "react";
import { label, runnerLabel } from "../agents/agentsLogic";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";

const COLUMNS: Array<{ id: string; title: string; states: string[] }> = [
  { id: "queued", title: "Queued", states: ["queued"] },
  { id: "running", title: "Working", states: ["running"] },
  { id: "waiting", title: "Needs you", states: ["needs_owner", "paused", "blocked"] },
  { id: "done", title: "Done", states: ["done", "failed", "cancelled"] },
];

export function TasksBoard({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    const load = () => source.tasks().then((t) => live && (setTasks(t), setError(undefined)), (e: Error) => live && setError(e.message));
    void load();
    const timer = setInterval(load, 15_000);
    return () => { live = false; clearInterval(timer); };
  }, [source]);
  const agentName = (id?: string | null) => {
    const agent = agents.find((a) => a.id === id);
    return agent ? label(agent) : id ?? "Unassigned";
  };
  return (
    <div className="jg-tasks">
      <div className="jg-chat__band" data-aether-window-drag-region><span className="jg-title-pill">Tasks</span></div>
      {error && <p className="jg-notice jg-notice--error jg-pad">Couldn't load tasks: {error}</p>}
      <div className="jg-board">
        {COLUMNS.map((col) => {
          const items = (tasks ?? []).filter((t) => col.states.includes(String(t.state)));
          return (
            <section key={col.id} className="jg-board__col" aria-label={col.title}>
              <h2 className="jg-board__title">{col.title} <span className="jg-muted">{items.length}</span></h2>
              {items.map((t) => (
                <article key={t.task_id} className={`jg-card jg-card--${t.state}`}>
                  <div className="jg-card__goal">{t.goal ?? t.task_id}</div>
                  <div className="jg-card__meta">
                    <span>{agentName(t.agent_id ?? t.owning_agent)}</span>
                    {runnerLabel(t.runner) && <span className="jg-tag">{runnerLabel(t.runner)}</span>}
                    {t.eta && <span>ETA {t.eta}</span>}
                  </div>
                </article>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}
