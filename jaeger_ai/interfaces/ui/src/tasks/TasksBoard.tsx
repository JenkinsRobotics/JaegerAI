import { TaskArtifacts } from '../library/TaskArtifacts';
import { OwnedHandoffs } from "./OwnedHandoffs";
import { SpecialistHandoff } from "./SpecialistHandoff";
import { keysWithPrefix } from "../lib/storageKeys";
import { TaskWidget } from "./TaskWidget";
import { TaskInspector } from "./TaskInspector";
import { GatewayError } from "../api/gateway";
/** Projection of the existing Gateway durable task owner; never a second scheduler. */
import { useEffect, useRef, useState } from "react";
import { label } from "../agents/agentsLogic";
import type { JaegerSource } from "../api/source";
import type { Agent, Task } from "../api/types";
import { ErrorState } from "../shell/ErrorState";

const COLUMNS = [
  { id: "queued", title: "Queued", states: ["queued"] },
  { id: "running", title: "Working", states: ["running"] },
  { id: "waiting", title: "Needs you", states: ["needs_owner", "paused", "blocked"] },
  { id: "done", title: "Finished", states: ["done", "completed", "completed_verified", "failed", "cancelled"] },
];

interface ProposalIntent { requestId: string; sessionId: string; origin: string; goal: string }
const PROPOSAL_DRAFT = 'jaeger.ui.task-proposal.draft.v1';
const PROPOSAL_INTENTS = 'jaeger.ui.task-proposal.intent.v1.';
const editKey = (id: string) => 'jaeger.ui.task-proposal.edit.v1.' + encodeURIComponent(id);
const savedProposals = (): ProposalIntent[] => keysWithPrefix(PROPOSAL_INTENTS).map(key=>{const value=JSON.parse(localStorage.getItem(key)!);if(!value.requestId||!value.sessionId||!value.origin||typeof value.goal!=='string')throw Error('Invalid saved task identity; original retained');return value as ProposalIntent;});

export function TasksBoard({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [artifactTask, setArtifactTask] = useState<string>();
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const [error, setError] = useState<string>();
  const [operationError, setOperationError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false), locked = useRef(false);
  const [goal, setGoal] = useState(""), [origin, setOrigin] = useState("");
  const [editing, setEditing] = useState<Task>(), [editGoal, setEditGoal] = useState("");
  const [uncertain, setUncertain] = useState<ProposalIntent>();
  const [draftReady, setDraftReady] = useState(false), [proposalError, setProposalError] = useState<string>();
  const [notice, setNotice] = useState<string>();

  useEffect(() => {
    try {
      const raw = localStorage.getItem(PROPOSAL_DRAFT);
      if (raw) {
        const value = JSON.parse(raw);
        if (typeof value.goal !== 'string' || typeof value.origin !== 'string')
          throw Error('Invalid proposal draft; original retained');
        setGoal(value.goal);
        setOrigin(value.origin);
      }
      setUncertain(savedProposals()[0]);
      setDraftReady(true);
    } catch(e) {
      setProposalError(`Task proposal recovery unavailable: ${String(e)}`);
    }
  }, []);

  const changeDraft = (nextGoal: string, nextOrigin: string) => {
    setGoal(nextGoal);
    setOrigin(nextOrigin);
    try {
      localStorage.setItem(PROPOSAL_DRAFT, JSON.stringify({ goal: nextGoal, origin: nextOrigin }));
      setProposalError(undefined);
    } catch(e) {
      setProposalError(`Proposal draft is not saved: ${String(e)}. No submission is allowed without recovery storage.`);
    }
  };

  const accepted = (intent: ProposalIntent, taskId: string, state: string) => {
    const raw = localStorage.getItem(PROPOSAL_DRAFT), saved = raw ? JSON.parse(raw) : undefined;
    if (saved && typeof saved.goal === 'string' && typeof saved.origin === 'string') {
      if (saved.goal === intent.goal && saved.origin === intent.origin) {
        localStorage.setItem(PROPOSAL_DRAFT, JSON.stringify({ goal: '', origin: saved.origin }));
        setGoal('');
      } else {
        setGoal(saved.goal);
        setOrigin(saved.origin);
      }
    }
    localStorage.removeItem(PROPOSAL_INTENTS + intent.requestId);
    setUncertain(savedProposals()[0]);
    setNotice(`Saved proposal ${taskId}: ${state}. Approval and execution status remain Gateway-owned.`);
  };

  useEffect(() => {
    let live = true, reading = false;
    const load = async () => {
      if (reading) return; reading = true;
      try {
        const rows = await source.tasks();
        if (live) {
          setTasks(rows);
          setError(undefined);
        }
      } catch (e) {
        if (live) setError(String((e as Error).message ?? e));
      } finally {
        reading = false;
      }
    };
    void load();
    const timer = setInterval(load, 15_000);
    return () => { live = false; clearInterval(timer); };
  }, [source, attempt]);

  const act = async (operation: () => Promise<unknown>, success: string) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setNotice(undefined);
    setOperationError(undefined);
    try {
      await operation();
      setNotice(success);
      setAttempt(n => n + 1);
    } catch (e) {
      setOperationError(String((e as Error).message ?? e));
      setAttempt(n => n + 1);
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };

  const create = () => {
    if (!source.taskActions || !source.agentHome || !draftReady || proposalError || !origin || !goal.trim() || uncertain) return;
    const requestId = crypto.randomUUID(), text = goal.trim(), originId = origin;
    void act(async () => {
      const home = await source.agentHome!(originId);
      if (home.agent_id !== originId || !home.session_id) throw Error('Origin conversation identity mismatch');
      const intent: ProposalIntent = { requestId, sessionId: home.session_id, origin: originId, goal };
      const existing = savedProposals()[0];
      if (existing) {
        setUncertain(existing);
        throw Error('A saved task proposal needs reconciliation first');
      }
      localStorage.setItem(PROPOSAL_DRAFT, JSON.stringify({ goal, origin: originId }));
      localStorage.setItem(PROPOSAL_INTENTS + requestId, JSON.stringify(intent));
      setUncertain(intent);
      try {
        const receipt = await source.taskActions!.create({ session_id: intent.sessionId, goal: text, request_id: requestId, proposal: true });
        if (receipt.request_id !== requestId || receipt.origin_session_id !== intent.sessionId || !receipt.task_id)
          throw Error('Task receipt identity mismatch');
        accepted(intent, receipt.task_id, receipt.status);
      } catch(e) {
        if (e instanceof GatewayError && [400, 401, 403, 404, 405, 423].includes(e.status)) {
          localStorage.removeItem(PROPOSAL_INTENTS + requestId);
          setUncertain(savedProposals()[0]);
          throw Error(`Proposal rejected: ${e.message}. Draft retained.`);
        }
        throw e;
      }
    }, 'Task submission receipt read; see Gateway task status');
  };

  const check = async () => {
    if (!uncertain) return;
    const intent = uncertain;
    await act(async () => {
      let rows: Task[];
      if (source.taskActions?.lookup) {
        const result = await source.taskActions.lookup(intent.sessionId, intent.requestId);
        if (result.session_id !== intent.sessionId || result.request_id !== intent.requestId)
          throw Error('Task lookup identity mismatch');
        rows = result.tasks;
      } else {
        rows = (await source.tasks()).filter(task => task.provenance?.request_id === intent.requestId && task.provenance?.session_id === intent.sessionId);
      }
      if (rows.length !== 1)
        throw Error(rows.length ? 'Multiple saved tasks share this legacy submission; inspect them without replay' : 'Proposal outcome remains unknown. Nothing was resubmitted.');
      if ((rows[0].provenance?.submission_goal ?? rows[0].goal) !== intent.goal.trim())
        throw Error('Saved task objective differs from this submission; draft and identity retained for review');
      accepted(intent, rows[0].task_id, String(rows[0].state));
    }, 'Saved proposal found; nothing was resubmitted');
  };

  const openEditor = (task: Task) => {
    try {
      const raw = localStorage.getItem(editKey(task.task_id));
      const saved = raw ? JSON.parse(raw) : undefined;
      if (saved && (typeof saved.goal !== 'string' || typeof saved.expected_updated_at !== 'number'))
        throw Error('Invalid saved edit; original retained');
      setEditing(saved ? { ...task, updated_at: saved.expected_updated_at } : task);
      setEditGoal(saved?.goal ?? task.goal ?? '');
    } catch(e) {
      setOperationError(String(e));
    }
  };

  const changeEdit = (value: string) => {
    setEditGoal(value);
    try {
      localStorage.setItem(editKey(editing!.task_id), JSON.stringify({ goal: value, expected_updated_at: editing!.updated_at }));
    } catch(e) {
      setOperationError(`Task edit draft not saved: ${String(e)}`);
    }
  };

  const saveEdit = () => {
    if (!editing || !source.taskActions) return;
    const task = editing, text = editGoal;
    void act(async () => {
      localStorage.setItem(editKey(task.task_id), JSON.stringify({ goal: text, expected_updated_at: task.updated_at }));
      const saved = await source.taskActions!.edit(task.task_id, text.trim(), task.updated_at!);
      if (saved.task_id !== task.task_id || saved.goal !== text.trim())
        throw Error("Edited proposal receipt mismatch; draft retained");
      const raw = localStorage.getItem(editKey(task.task_id));
      if (raw && JSON.parse(raw).goal === text) localStorage.removeItem(editKey(task.task_id));
      setEditing(undefined);
    }, 'Proposal updated; approval still required');
  };

  const known = COLUMNS.flatMap(c => c.states);
  const columns = [...COLUMNS, { id: "other", title: "Other states", states: [] as string[] }];

  // Active selected task resolution
  const selectedTask = tasks?.find(t => t.task_id === selectedTaskId);

  return (
    <div className="jg-tasks">
      <div className="jg-tasks__band" data-aether-window-drag-region>
        <span className="jg-title-pill">Tasks</span>
      </div>

      {error && (
        <ErrorState
          compact={tasks !== null}
          title="Task operation or refresh failed"
          error={error}
          onRetry={() => setAttempt(n => n + 1)}
        />
      )}

      {notice && <p role="status">{notice}</p>}
      {operationError && <p role="alert">{operationError}</p>}
      {proposalError && <p role="alert">{proposalError}</p>}

      <OwnedHandoffs source={source} />
      {source.delegation && source.agentHome && <SpecialistHandoff source={source} agents={agents} />}

      {source.taskActions && source.agentHome && (
        <form
          className="jg-task-form"
          aria-label="New task proposal"
          onSubmit={e => { e.preventDefault(); create(); }}
        >
          <label>
            Return results to
            <select
              aria-label="Task originating bot"
              value={origin}
              onChange={e => changeDraft(goal, e.target.value)}
              disabled={busy || Boolean(uncertain) || !draftReady}
            >
              <option value="">Choose bot</option>
              {origin && !agents.some(a => a.id === origin && !a.hidden && !a.deleted) && (
                <option value={origin}>Saved bot · {origin}</option>
              )}
              {agents.filter(a => !a.hidden && !a.deleted).map(a => (
                <option key={a.id} value={a.id}>{label(a)}</option>
              ))}
            </select>
          </label>
          <label>
            Objective
            <textarea
              aria-label="Task objective"
              value={goal}
              onChange={e => changeDraft(e.target.value, origin)}
              disabled={busy || Boolean(uncertain) || !draftReady}
            />
          </label>
          <p className="jg-muted">
            Creates a proposal for Jaeger's existing task runner. Approval and tool permissions still apply.
          </p>
          <button
            type="submit"
            disabled={busy || !origin || !goal.trim() || Boolean(uncertain) || !draftReady || Boolean(proposalError)}
          >
            Create proposal
          </button>
          {uncertain && (
            <p role="alert">
              Submission outcome is unknown. Nothing will be resubmitted.
              <button type="button" disabled={busy} onClick={() => void check()}>Check saved proposal</button>
            </p>
          )}
        </form>
      )}

      {tasks === null && !error && <p role="status">Loading tasks…</p>}

      {tasks !== null && (
        <div className="jg-tasks-workspace">
          {/* Master List: Mission widgets grouped by category */}
          <div className="jg-board">
            {columns.map(col => {
              const items = tasks
                .filter(t => col.id === "other" ? !known.includes(String(t.state)) : col.states.includes(String(t.state)))
                .sort((a, b) => Number(Boolean(b.presentation?.pinned)) - Number(Boolean(a.presentation?.pinned)));
              if (col.id === "other" && !items.length) return null;

              return (
                <section key={col.id} className="jg-board__col" aria-label={col.title}>
                  <h2 className="jg-board__title">
                    {col.title} <span className="jg-muted">{items.length}</span>
                  </h2>
                  <div className="jg-board__items">
                    {items.length === 0 ? (
                      <p className="jg-muted" style={{ padding: '12px 8px', fontSize: '11px', textAlign: 'center' }}>
                        No {col.title.toLowerCase()} tasks
                      </p>
                    ) : (
                      items.map(t => (
                        <TaskWidget
                          key={t.task_id}
                          task={t}
                          agents={agents}
                          selected={selectedTask?.task_id === t.task_id}
                          busy={busy}
                          onSelect={setSelectedTaskId}
                          onApprove={
                            source.taskActions
                              ? task =>
                                  void act(
                                    () => source.taskActions!.approve(task.task_id, task.updated_at!),
                                    "Proposal approved; waiting for runner"
                                  )
                              : undefined
                          }
                          onEdit={openEditor}
                          onCancel={
                            source.taskActions
                              ? taskId =>
                                  void act(
                                    () => source.taskActions!.cancel(taskId),
                                    "Cancellation requested; awaiting task status"
                                  )
                              : undefined
                          }
                        />
                      ))
                    )}
                  </div>
                </section>
              );
            })}
          </div>

          {/* Detail Inspector Pane. Rendered only when a task is selected: an
              always-open 420px pane left the board 474px wide, which forced the
              four status columns down to 110px each. */}
          {selectedTask && (
          <aside className="jg-tasks-inspector-pane">
            <TaskInspector
              task={selectedTask}
              agents={agents}
              source={source}
              busy={busy}
              onClose={() => setSelectedTaskId(undefined)}
              onApprove={
                source.taskActions
                  ? task =>
                      void act(
                        () => source.taskActions!.approve(task.task_id, task.updated_at!),
                        "Proposal approved; waiting for runner"
                      )
                  : undefined
              }
              onEdit={openEditor}
              onCancel={
                source.taskActions
                  ? taskId =>
                      void act(
                        () => source.taskActions!.cancel(taskId),
                        "Cancellation requested; awaiting task status"
                      )
                  : undefined
              }
              onPresentationChange={() => setAttempt(n => n + 1)}
            />
          </aside>
          )}
        </div>
      )}

      {artifactTask && source.taskArtifacts && (
        <div className="jg-tasks__artifact-overlay">
          <button onClick={() => setArtifactTask(undefined)}>Close task artifacts</button>
          <TaskArtifacts controls={source.taskArtifacts} taskId={artifactTask} />
        </div>
      )}

      {editing && (
        <form
          className="jg-task-form"
          aria-label="Edit task proposal"
          onSubmit={e => { e.preventDefault(); saveEdit(); }}
        >
          <textarea
            aria-label="Revised task objective"
            value={editGoal}
            onChange={e => changeEdit(e.target.value)}
            disabled={busy}
          />
          <button disabled={busy || !editGoal.trim()}>Save proposal</button>
          <button type="button" disabled={busy} onClick={() => setEditing(undefined)}>Close editor</button>
        </form>
      )}
    </div>
  );
}
