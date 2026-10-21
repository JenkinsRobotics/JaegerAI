/** Projection of the existing Gateway durable task owner; never a second scheduler. */
import { useEffect, useRef, useState } from "react";
import { label, runnerLabel } from "../agents/agentsLogic";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";
import { ErrorState } from "../shell/ErrorState";

const COLUMNS = [
  { id: "queued", title: "Queued", states: ["queued"] },
  { id: "running", title: "Working", states: ["running"] },
  { id: "waiting", title: "Needs you", states: ["needs_owner", "paused", "blocked"] },
  { id: "done", title: "Finished", states: ["done", "failed", "cancelled"] },
];
const terminal = (task: Task) => ["done", "failed", "cancelled"].includes(String(task.state));
const proposal = (task: Task) => task.state === "paused" && task.provenance?.authorized === false && !task.run_history?.length;

export function TasksBoard({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string>();
  const [operationError, setOperationError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false), locked = useRef(false);
  const [goal, setGoal] = useState(""), [origin, setOrigin] = useState("");
  const [editing, setEditing] = useState<Task>(), [editGoal, setEditGoal] = useState("");
  const [uncertain, setUncertain] = useState<string>();
  const [notice, setNotice] = useState<string>();
  useEffect(() => {
    let live = true, reading = false;
    const load = async () => {
      if (reading) return; reading = true;
      try { const rows = await source.tasks(); if (live) { setTasks(rows); setError(undefined); } }
      catch (e) { if (live) setError(String((e as Error).message ?? e)); }
      finally { reading = false; }
    };
    void load(); const timer = setInterval(load, 15_000);
    return () => { live = false; clearInterval(timer); };
  }, [source, attempt]);
  const act = async (operation: () => Promise<unknown>, success: string) => {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice(undefined); setOperationError(undefined);
    try { await operation(); setNotice(success); setEditing(undefined); setAttempt(n => n + 1); }
    catch (e) { setOperationError(String((e as Error).message ?? e)); setAttempt(n => n + 1); }
    finally { locked.current = false; setBusy(false); }
  };
  const create = () => {
    if (!source.taskActions || !source.agentHome || !origin || !goal.trim() || uncertain) return;
    const request_id = crypto.randomUUID(), text = goal.trim();
    void act(async () => {
      const home = await source.agentHome!(origin);
      if (home.agent_id !== origin || !home.session_id) throw new Error("Origin conversation identity mismatch");
      const session_id = home.session_id;
      try {
        const receipt = await source.taskActions!.create({ session_id, goal: text, request_id, proposal: true });
        setGoal(""); setNotice(`Proposal ${receipt.task_id} saved (${receipt.status})`);
      } catch (e) {
        // The response can be lost after admission; no automatic create retry.
        setUncertain(request_id); throw e;
      }
    }, "Task proposal saved; approval is still required");
  };
  const check = async () => {
    if (!uncertain) return;
    await act(async () => {
      const rows = await source.tasks(); setTasks(rows);
      const found = rows.find(t => t.provenance?.request_id === uncertain);
      if (!found) throw new Error("Proposal outcome remains unknown. No work was resubmitted.");
      setUncertain(undefined); setGoal("");
    }, "Saved proposal found");
  };
  const agentName = (id?: string | null) => { const agent = agents.find(a => a.id === id); return agent ? label(agent) : id ?? "Unassigned"; };
  const known = COLUMNS.flatMap(c => c.states);
  const columns = [...COLUMNS, { id: "other", title: "Other states", states: [] as string[] }];
  return <div className="jg-tasks">
    <div className="jg-tasks__band" data-aether-window-drag-region><span className="jg-title-pill">Tasks</span></div>
    {error && <ErrorState compact={tasks !== null} title="Task operation or refresh failed" error={error} onRetry={() => setAttempt(n => n + 1)} />}
    {notice && <p role="status">{notice}</p>}
    {operationError && <p role="alert">{operationError}</p>}
    {source.taskActions && source.agentHome && <form className="jg-task-form" aria-label="New task proposal" onSubmit={e => { e.preventDefault(); create(); }}>
      <label>Return results to <select aria-label="Task originating bot" value={origin} onChange={e => setOrigin(e.target.value)} disabled={busy || Boolean(uncertain)}><option value="">Choose bot</option>{agents.filter(a => !a.hidden && !a.deleted).map(a => <option key={a.id} value={a.id}>{label(a)}</option>)}</select></label>
      <label>Objective <textarea aria-label="Task objective" value={goal} onChange={e => setGoal(e.target.value)} disabled={busy || Boolean(uncertain)} /></label>
      <p className="jg-muted">Creates a proposal for Jaeger's existing task runner. Approval and tool permissions still apply.</p>
      <button type="submit" disabled={busy || !origin || !goal.trim() || Boolean(uncertain)}>Create proposal</button>
      {uncertain && <p role="alert">Submission outcome is unknown. Nothing will be resubmitted. <button type="button" disabled={busy} onClick={() => void check()}>Check saved proposal</button></p>}
    </form>}
    {tasks === null && !error && <p role="status">Loading tasks…</p>}
    {tasks !== null && <div className="jg-board">{columns.map(col => {
      const items = tasks.filter(t => col.id === "other" ? !known.includes(String(t.state)) : col.states.includes(String(t.state)));
      if (col.id === "other" && !items.length) return null;
      return <section key={col.id} className="jg-board__col" aria-label={col.title}><h2 className="jg-board__title">{col.title} <span className="jg-muted">{items.length}</span></h2>
        {items.map(t => <article key={t.task_id} className={`jg-card jg-card--${t.state}`}>
          <div className="jg-card__goal">{t.goal ?? t.task_id}</div>
          <div className="jg-card__meta"><span>{agentName(t.agent_id ?? t.owning_agent)}</span><span>{t.state}</span>{runnerLabel(t.runner) && <span className="jg-tag">{runnerLabel(t.runner)}</span>}{t.eta && <span>ETA {t.eta}</span>}</div>
          {t.error && <p role="alert">{t.error}</p>}
          {t.result != null && <details><summary>Result</summary><pre>{typeof t.result === "string" ? t.result : JSON.stringify(t.result, null, 2)}</pre></details>}
          {source.taskActions && <div>
            {proposal(t) && typeof t.updated_at === "number" && <><button type="button" disabled={busy} onClick={() => { setEditing(t); setEditGoal(t.goal ?? ""); }}>Edit proposal</button><button type="button" disabled={busy} onClick={() => void act(() => source.taskActions!.approve(t.task_id, t.updated_at!), "Proposal approved; waiting for runner")}>Approve this version</button></>}
            {!terminal(t) && <button type="button" disabled={busy} onClick={() => void act(() => source.taskActions!.cancel(t.task_id), "Cancellation requested; awaiting task status")}>Cancel task</button>}
          </div>}
        </article>)}
      </section>;
    })}</div>}
    {editing && <form className="jg-task-form" aria-label="Edit task proposal" onSubmit={e => { e.preventDefault(); void act(() => source.taskActions!.edit(editing.task_id, editGoal.trim(), editing.updated_at!), "Proposal updated; approval still required"); }}>
      <textarea aria-label="Revised task objective" value={editGoal} onChange={e => setEditGoal(e.target.value)} disabled={busy} /><button disabled={busy || !editGoal.trim()}>Save proposal</button><button type="button" disabled={busy} onClick={() => setEditing(undefined)}>Close editor</button>
    </form>}
  </div>;
}
