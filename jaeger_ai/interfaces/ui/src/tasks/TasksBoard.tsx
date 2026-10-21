import {TaskPresentationControls} from "./TaskPresentationControls";
import { GatewayError } from "../api/gateway";
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
  { id: "done", title: "Finished", states: ["done", "completed", "completed_verified", "failed", "cancelled"] },
];
const terminal = (task: Task) => ["done", "completed", "completed_verified", "needs_owner", "blocked", "failed", "cancelled"].includes(String(task.state));
const proposal = (task: Task) => task.state === "paused" && task.provenance?.authorized === false && !task.run_history?.length;

interface ProposalIntent { requestId: string; sessionId: string; origin: string; goal: string }
const PROPOSAL_DRAFT = 'jaeger.ui.task-proposal.draft.v1';
const PROPOSAL_INTENTS = 'jaeger.ui.task-proposal.intent.v1.';
const editKey = (id: string) => 'jaeger.ui.task-proposal.edit.v1.' + encodeURIComponent(id);
const savedProposals = (): ProposalIntent[] => Object.keys(localStorage).filter(key=>key.startsWith(PROPOSAL_INTENTS)).map(key=>{const value=JSON.parse(localStorage.getItem(key)!);if(!value.requestId||!value.sessionId||!value.origin||typeof value.goal!=='string')throw Error('Invalid saved task identity; original retained');return value as ProposalIntent;});

export function TasksBoard({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
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
    try { const raw=localStorage.getItem(PROPOSAL_DRAFT);if(raw){const value=JSON.parse(raw);if(typeof value.goal!=='string'||typeof value.origin!=='string')throw Error('Invalid proposal draft; original retained');setGoal(value.goal);setOrigin(value.origin);}setUncertain(savedProposals()[0]);setDraftReady(true); }
    catch(e){setProposalError(`Task proposal recovery unavailable: ${String(e)}`);}
  }, []);
  const changeDraft = (nextGoal: string, nextOrigin: string) => { setGoal(nextGoal);setOrigin(nextOrigin);try{localStorage.setItem(PROPOSAL_DRAFT,JSON.stringify({goal:nextGoal,origin:nextOrigin}));setProposalError(undefined);}catch(e){setProposalError(`Proposal draft is not saved: ${String(e)}. No submission is allowed without recovery storage.`);} };
  const accepted = (intent: ProposalIntent, taskId: string, state: string) => {
    const raw=localStorage.getItem(PROPOSAL_DRAFT), saved=raw?JSON.parse(raw):undefined;
    if(saved&&typeof saved.goal==='string'&&typeof saved.origin==='string'){
      if(saved.goal===intent.goal&&saved.origin===intent.origin){localStorage.setItem(PROPOSAL_DRAFT,JSON.stringify({goal:'',origin:saved.origin}));setGoal('');}
      else {setGoal(saved.goal);setOrigin(saved.origin);}
    }
    localStorage.removeItem(PROPOSAL_INTENTS+intent.requestId);setUncertain(savedProposals()[0]);setNotice(`Saved proposal ${taskId}: ${state}. Approval and execution status remain Gateway-owned.`);
  };
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
    try { await operation(); setNotice(success); setAttempt(n => n + 1); }
    catch (e) { setOperationError(String((e as Error).message ?? e)); setAttempt(n => n + 1); }
    finally { locked.current = false; setBusy(false); }
  };
  const create = () => {
    if (!source.taskActions || !source.agentHome || !draftReady || proposalError || !origin || !goal.trim() || uncertain) return;
    const requestId=crypto.randomUUID(), text=goal.trim(), originId=origin;
    void act(async () => {
      const home=await source.agentHome!(originId);
      if(home.agent_id!==originId||!home.session_id)throw Error('Origin conversation identity mismatch');
      const intent:ProposalIntent={requestId,sessionId:home.session_id,origin:originId,goal};
      const existing=savedProposals()[0];if(existing){setUncertain(existing);throw Error('A saved task proposal needs reconciliation first');}
      // Persist the immutable command before dispatch; no replay on mount/check.
      localStorage.setItem(PROPOSAL_DRAFT,JSON.stringify({goal,origin:originId}));
      localStorage.setItem(PROPOSAL_INTENTS+requestId,JSON.stringify(intent));setUncertain(intent);
      try{
        const receipt=await source.taskActions!.create({session_id:intent.sessionId,goal:text,request_id:requestId,proposal:true});
        if(receipt.request_id!==requestId||receipt.origin_session_id!==intent.sessionId||!receipt.task_id)throw Error('Task receipt identity mismatch');
        accepted(intent,receipt.task_id,receipt.status);
      }catch(e){
        if(e instanceof GatewayError&&[400,401,403,404,405,423].includes(e.status)){localStorage.removeItem(PROPOSAL_INTENTS+requestId);setUncertain(savedProposals()[0]);throw Error(`Proposal rejected: ${e.message}. Draft retained.`);}
        throw e;
      }
    }, 'Task submission receipt read; see Gateway task status');
  };
  const check = async () => {
    if(!uncertain)return;const intent=uncertain;
    await act(async()=>{
      let rows:Task[];
      if(source.taskActions?.lookup){const result=await source.taskActions.lookup(intent.sessionId,intent.requestId);if(result.session_id!==intent.sessionId||result.request_id!==intent.requestId)throw Error('Task lookup identity mismatch');rows=result.tasks;}
      else rows=(await source.tasks()).filter(task=>task.provenance?.request_id===intent.requestId&&task.provenance?.session_id===intent.sessionId);
      if(rows.length!==1)throw Error(rows.length?'Multiple saved tasks share this legacy submission; inspect them without replay':'Proposal outcome remains unknown. Nothing was resubmitted.');
      if((rows[0].provenance?.submission_goal??rows[0].goal)!==intent.goal.trim())throw Error('Saved task objective differs from this submission; draft and identity retained for review');
      accepted(intent,rows[0].task_id,String(rows[0].state));
    },'Saved proposal found; nothing was resubmitted');
  };
  const openEditor = (task:Task) => {
    try{const raw=localStorage.getItem(editKey(task.task_id));const saved=raw?JSON.parse(raw):undefined;if(saved&&(typeof saved.goal!=='string'||typeof saved.expected_updated_at!=='number'))throw Error('Invalid saved edit; original retained');setEditing(saved?{...task,updated_at:saved.expected_updated_at}:task);setEditGoal(saved?.goal??task.goal??'');}
    catch(e){setOperationError(String(e));}
  };
  const changeEdit = (value:string) => {setEditGoal(value);try{localStorage.setItem(editKey(editing!.task_id),JSON.stringify({goal:value,expected_updated_at:editing!.updated_at}));}catch(e){setOperationError(`Task edit draft not saved: ${String(e)}`);} };
  const saveEdit = () => {if(!editing||!source.taskActions)return;const task=editing,text=editGoal;void act(async()=>{localStorage.setItem(editKey(task.task_id),JSON.stringify({goal:text,expected_updated_at:task.updated_at}));const saved=await source.taskActions!.edit(task.task_id,text.trim(),task.updated_at!);if(saved.task_id!==task.task_id||saved.goal!==text.trim())throw Error("Edited proposal receipt mismatch; draft retained");const raw=localStorage.getItem(editKey(task.task_id));if(raw&&JSON.parse(raw).goal===text)localStorage.removeItem(editKey(task.task_id));setEditing(undefined);},'Proposal updated; approval still required');};
  const agentName = (id?: string | null) => { const agent = agents.find(a => a.id === id); return agent ? label(agent) : id ?? "Unassigned"; };
  const known = COLUMNS.flatMap(c => c.states);
  const columns = [...COLUMNS, { id: "other", title: "Other states", states: [] as string[] }];
  return <div className="jg-tasks">
    <div className="jg-tasks__band" data-aether-window-drag-region><span className="jg-title-pill">Tasks</span></div>
    {error && <ErrorState compact={tasks !== null} title="Task operation or refresh failed" error={error} onRetry={() => setAttempt(n => n + 1)} />}
    {notice && <p role="status">{notice}</p>}
    {operationError && <p role="alert">{operationError}</p>}{proposalError && <p role="alert">{proposalError}</p>}
    {source.taskActions && source.agentHome && <form className="jg-task-form" aria-label="New task proposal" onSubmit={e => { e.preventDefault(); create(); }}>
      <label>Return results to <select aria-label="Task originating bot" value={origin} onChange={e => changeDraft(goal,e.target.value)} disabled={busy || Boolean(uncertain) || !draftReady}><option value="">Choose bot</option>{origin&&!agents.some(a=>a.id===origin&&!a.hidden&&!a.deleted)&&<option value={origin}>Saved bot · {origin}</option>}{agents.filter(a => !a.hidden && !a.deleted).map(a => <option key={a.id} value={a.id}>{label(a)}</option>)}</select></label>
      <label>Objective <textarea aria-label="Task objective" value={goal} onChange={e => changeDraft(e.target.value,origin)} disabled={busy || Boolean(uncertain) || !draftReady} /></label>
      <p className="jg-muted">Creates a proposal for Jaeger's existing task runner. Approval and tool permissions still apply.</p>
      <button type="submit" disabled={busy || !origin || !goal.trim() || Boolean(uncertain) || !draftReady || Boolean(proposalError)}>Create proposal</button>
      {uncertain && <p role="alert">Submission outcome is unknown. Nothing will be resubmitted. <button type="button" disabled={busy} onClick={() => void check()}>Check saved proposal</button></p>}
    </form>}
    {tasks === null && !error && <p role="status">Loading tasks…</p>}
    {tasks !== null && <div className="jg-board">{columns.map(col => {
      const items = tasks.filter(t => col.id === "other" ? !known.includes(String(t.state)) : col.states.includes(String(t.state))).sort((a,b)=>Number(Boolean(b.presentation?.pinned))-Number(Boolean(a.presentation?.pinned)));
      if (col.id === "other" && !items.length) return null;
      return <section key={col.id} className="jg-board__col" aria-label={col.title}><h2 className="jg-board__title">{col.title} <span className="jg-muted">{items.length}</span></h2>
        {items.map(t => <article key={t.task_id} className={`jg-card jg-card--${t.state}`}>
          <div className="jg-card__goal">{t.goal ?? t.task_id}</div>
          <div className="jg-card__meta"><span>{agentName(t.agent_id ?? t.owning_agent)}</span><span>{t.state}</span>{runnerLabel(t.runner) && <span className="jg-tag">{runnerLabel(t.runner)}</span>}{t.eta && <span>ETA {t.eta}</span>}</div>
          <details><summary>Task details · {t.task_id}</summary><p>Last observed task revision {t.updated_at ?? "unknown"}. Board refreshes every15 seconds; this is not a live execution guarantee.</p><p>Origin conversation: {t.provenance?.session_id ?? "not recorded"} · Origin request: {t.provenance?.request_id ?? "not recorded"}</p><pre>{JSON.stringify(t.run_history ?? [],null,2)}</pre></details>
          {source.taskPresentation && t.presentation && typeof t.updated_at==='number' && <TaskPresentationControls task={t} controls={source.taskPresentation} changed={()=>setAttempt(n=>n+1)}/>}
          {t.error && <p role="alert">{t.error}</p>}
          {t.result != null && <details><summary>Result</summary><pre>{typeof t.result === "string" ? t.result : JSON.stringify(t.result, null, 2)}</pre></details>}
          {source.taskActions && <div>
            {proposal(t) && typeof t.updated_at === "number" && <><button type="button" disabled={busy} onClick={() => openEditor(t)}>Edit proposal</button><button type="button" disabled={busy || (editing?.task_id===t.task_id && editGoal.trim()!==t.goal)} onClick={() => void act(() => source.taskActions!.approve(t.task_id, t.updated_at!), "Proposal approved; waiting for runner")}>Approve this version</button></>}
            {!terminal(t) && <button type="button" disabled={busy} onClick={() => void act(() => source.taskActions!.cancel(t.task_id), "Cancellation requested; awaiting task status")}>Cancel task</button>}
          </div>}
        </article>)}
      </section>;
    })}</div>}
    {editing && <form className="jg-task-form" aria-label="Edit task proposal" onSubmit={e => { e.preventDefault(); saveEdit(); }}>
      <textarea aria-label="Revised task objective" value={editGoal} onChange={e => changeEdit(e.target.value)} disabled={busy} /><button disabled={busy || !editGoal.trim()}>Save proposal</button><button type="button" disabled={busy} onClick={() => setEditing(undefined)}>Close editor</button>
    </form>}
  </div>;
}
