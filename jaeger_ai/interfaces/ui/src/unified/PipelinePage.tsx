/**
 * Work › Pipeline (task hub), Work › Production, and the "current task" banner shown in Research,
 * Studio and Production. Real data only: gateway tasks + the WebUI pipeline store + task artifacts.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { JaegerSource, TaskArtifact } from "../api/source";
import type { Task } from "../api/types";
import { Badge, Empty, PageHead, SkeletonRows, useToast } from "./ui";
import { getJson } from "./webui";
import { STAGES, STAGE_LABEL, nextStage, pipelineApi, stagePath, type Attachment, type AttachKind, type PipelineRecord, type Stage } from "./pipeline";
import { RunnerQueue } from "./RunnerQueue";

const title = (t?: Task) => (t?.goal || t?.task_id || "Task").replace(/^Deep research: /, "");
const stateTone = (s?: string) => (s === "succeeded" ? "ok" : s === "failed" || s === "cancelled" ? "bad" : s === "running" ? "warn" : undefined);

export function usePipeline(source: JaegerSource) {
  const [tasks, setTasks] = useState<Task[]>();
  const [items, setItems] = useState<Record<string, PipelineRecord>>({});
  const [err, setErr] = useState<string>();
  const request = useRef(0);
  const load = useCallback(async () => {
    const id = ++request.current;
    setTasks(undefined); setItems({}); setErr(undefined);
    try {
      const [t, p] = await Promise.all([source.tasks(), pipelineApi.list()]);
      if (id !== request.current) return;
      // Pipeline tasks owned by WebUI jobs (e.g. YouTube research, id "yt:<playlist>") have no gateway task: list them too.
      const known = new Set(t.map((x) => x.task_id));
      const jobs = Object.values(p.items).filter((r) => !known.has(r.task_id)).map((r) => ({ task_id: r.task_id, goal: r.attachments.find((a) => a.kind === "source")?.label || r.task_id, state: "webui job" } as Task));
      setTasks([...t, ...jobs]); setItems(p.items); setErr(undefined);
    } catch (e) { if (id === request.current) setErr((e as Error).message); }
  }, [source]);
  useEffect(() => { void load(); return () => { ++request.current; }; }, [load]);
  return { tasks, items, err, load, setItems };
}

export function StageStepper({ stage, compact }: { stage: Stage | null; compact?: boolean }) {
  const at = stage ? STAGES.indexOf(stage) : -1;
  return (
    <ol className={`jg-stepper${compact ? " jg-stepper--compact" : ""}`} aria-label={`Stage: ${stage ? STAGE_LABEL[stage] : "not started"}`}>
      {STAGES.map((s, i) => (
        <li key={s} data-state={i < at ? "done" : i === at ? "current" : "todo"} aria-current={i === at ? "step" : undefined}>
          <span className="jg-stepper__dot" aria-hidden="true" /><span className="jg-stepper__label">{STAGE_LABEL[s]}</span>
        </li>
      ))}
    </ol>
  );
}

async function advance(rec: PipelineRecord | undefined, taskId: string, onNavigate: (to: string) => void, after: (r: PipelineRecord) => void, toast: (m: string, k?: "error") => void, isCurrent: () => boolean = () => true) {
  const to = nextStage(rec?.stage ?? null);
  if (!to) return;
  try {
    const r = await pipelineApi.setStage(taskId, to, rec?.revision);
    if (!isCurrent()) return;
    after(r);
    toast(`Moved to ${STAGE_LABEL[to]}`);
    onNavigate(stagePath(to, taskId));
  } catch (e) { if (isCurrent()) toast((e as Error).message, "error"); }
}

export function PipelinePage({ source, params, onNavigate }: { source: JaegerSource; params: URLSearchParams; onNavigate: (to: string) => void }) {
  const { tasks, items, err, load, setItems } = usePipeline(source);
  const toast = useToast();
  const [filter, setFilter] = useState<"active" | "all">("active");
  const selected = params.get("task");
  const rows = useMemo(() => (tasks ?? []).filter((t) => filter === "all" || items[t.task_id]?.stage !== "done").sort((a, b) => Number(!!items[b.task_id]) - Number(!!items[a.task_id]) || (b.updated_at ?? 0) - (a.updated_at ?? 0)), [tasks, items, filter]);
  const put = (r: PipelineRecord) => setItems((m) => ({ ...m, [r.task_id]: r }));
  const counts = STAGES.map((s) => Object.values(items).filter((r) => r.stage === s).length);
  return (
    <div className="jg-u-page">
      <PageHead title="Pipeline" subtitle="Every task moves Plan → Research → Studio → Production → Review → Done. Advancing opens the next tab with the task attached."
        actions={<>
          <select className="jg-ui-input" value={filter} onChange={(e) => setFilter(e.target.value as "active" | "all")} aria-label="Show"><option value="active">Not done</option><option value="all">All tasks</option></select>
          <button type="button" className="jg-u-btn" onClick={() => void load()}>Refresh</button>
        </>} />
      <RunnerQueue onNavigate={onNavigate} />
      {tasks && <div className="jg-pipe-summary" aria-label="Tasks per stage">{STAGES.map((s, i) => <span key={s}><strong>{counts[i]}</strong> {STAGE_LABEL[s]}</span>)}</div>}
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {!tasks && !err && <SkeletonRows n={4} />}
      {tasks && rows.length === 0 && <Empty title="No tasks yet">Create a task in Work › Tasks or ask Jaeger in Chat, then start it here.</Empty>}
      <ul className="jg-pipe-list">
        {rows.map((t) => {
          const rec = items[t.task_id];
          const nx = nextStage(rec?.stage ?? null);
          return (
            <li key={t.task_id} className="jg-u-card jg-pipe-card" data-selected={selected === t.task_id || undefined}>
              <div className="jg-pipe-card__head">
                <button type="button" className="jg-pipe-card__title" onClick={() => onNavigate(`/work/tasks?task=${encodeURIComponent(t.task_id)}`)}>{title(t)}</button>
                <Badge tone={stateTone(t.state)}>{t.state ?? "unknown"}</Badge>
              </div>
              <StageStepper stage={rec?.stage ?? null} />
              <div className="jg-pipe-card__foot">
                <span className="jg-u-note">{rec ? `${rec.attachments.length} attached · ${rec.history.length} stage change${rec.history.length === 1 ? "" : "s"}` : "Not in the pipeline yet"}</span>
                <div className="jg-ui-toolbar">
                  {rec?.stage && rec.stage !== "done" && rec.stage !== "intake" && <button type="button" className="jg-u-btn" onClick={() => onNavigate(stagePath(rec.stage!, t.task_id))}>Open {STAGE_LABEL[rec.stage]}</button>}
                  {nx && <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => void advance(rec, t.task_id, onNavigate, put, toast)}>{rec ? `Advance to ${STAGE_LABEL[nx]}` : "Start in Plan"}</button>}
                </div>
              </div>
              {selected === t.task_id && rec && <Attachments taskId={t.task_id} rec={rec} onChange={put} kinds={["note", "source"]} />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Attachments({ taskId, rec, onChange, kinds, filter }: { taskId: string; rec: PipelineRecord; onChange: (r: PipelineRecord) => void; kinds: AttachKind[]; filter?: AttachKind[] }) {
  const toast = useToast();
  const [kind, setKind] = useState<AttachKind>(kinds[0]);
  const [val, setVal] = useState("");
  const list = rec.attachments.filter((a) => !filter || filter.includes(a.kind));
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!val.trim()) return;
    try {
      const a = await pipelineApi.attach(taskId, kind === "note" ? { kind, text: val } : { kind, ref: val.trim(), label: val.trim() });
      onChange({ ...rec, attachments: [...rec.attachments, a] }); setVal("");
    } catch (er) { toast((er as Error).message, "error"); }
  };
  const remove = async (a: Attachment) => {
    try { await pipelineApi.detach(taskId, a.id); onChange({ ...rec, attachments: rec.attachments.filter((x) => x.id !== a.id) }); } catch (er) { toast((er as Error).message, "error"); }
  };
  return (
    <div className="jg-pipe-attach">
      {list.length === 0 ? <p className="jg-u-note">Nothing attached{filter ? ` (${filter.join(", ")})` : ""}.</p> : (
        <ul className="jg-u-list">{list.map((a) => (
          <li key={a.id} className="jg-pipe-attach__row">
            <Badge>{a.kind}</Badge>
            {a.kind === "source" && a.ref ? <a href={a.ref} target="_blank" rel="noreferrer noopener">{a.label || a.ref}</a> : <span>{a.text || a.label || a.ref}</span>}
            <span className="jg-u-note">{STAGE_LABEL[a.stage]}</span>
            <button type="button" className="jg-u-link" onClick={() => void remove(a)} aria-label={`Remove ${a.kind}`}>Remove</button>
          </li>))}
        </ul>)}
      {kinds.length > 0 && (
        <form className="jg-ui-toolbar" onSubmit={add}>
          {kinds.length > 1 && <select className="jg-ui-input" value={kind} onChange={(e) => setKind(e.target.value as AttachKind)} aria-label="Attachment kind">{kinds.map((k) => <option key={k} value={k}>{k === "note" ? "Note" : k === "source" ? "Source URL" : k}</option>)}</select>}
          <input className="jg-u-search" value={val} onChange={(e) => setVal(e.target.value)} placeholder={kind === "note" ? "Add a note…" : "https://…"} aria-label={kind === "note" ? "Note" : "Source URL"} />
          <button type="submit" className="jg-u-btn">Attach</button>
        </form>)}
    </div>
  );
}

/** The current task, shown above Research / Studio / Production when the URL carries ?task=. */
export function TaskBanner({ source, taskId, stage, onNavigate, clearTo }: { source: JaegerSource; taskId: string; stage: "research" | "studio" | "production"; onNavigate: (to: string) => void; clearTo: string }) {
  const toast = useToast();
  const [task, setTask] = useState<Task | null>();
  const [rec, setRec] = useState<PipelineRecord>();
  const [open, setOpen] = useState(false);
  const [picks, setPicks] = useState<{ ref: string; label: string }[]>();
  const [taskError, setTaskError] = useState<string>();
  const [recordError, setRecordError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [attempt, retry] = useState(0);
  const [pickError, setPickError] = useState<string>();
  const pickRequest = useRef(0);
  const contextGeneration = useRef(0);
  useEffect(() => {
    setTask(undefined); setRec(undefined); setPicks(undefined); setOpen(false); setPickError(undefined);
    ++pickRequest.current;
    ++contextGeneration.current;
    return () => { ++pickRequest.current; ++contextGeneration.current; };
  }, [source, taskId, stage]);
  useEffect(() => {
    let live = true;
    setLoading(true); setTaskError(undefined); setRecordError(undefined);
    void Promise.all([
      source.tasks().then((ts) => { if (live) setTask(ts.find((t) => t.task_id === taskId) ?? null); }, (e: Error) => { if (live) setTaskError(`Task details unavailable: ${e.message}`); }),
      pipelineApi.list().then((p) => { if (live) setRec(p.items[taskId]); }, (e: Error) => { if (live) setRecordError(`Task pipeline unavailable: ${e.message}`); }),
    ]).then(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [source, taskId, stage, attempt]);
  const pickKind: AttachKind = stage === "studio" ? "asset" : stage === "research" ? "document" : "deliverable";
  const loadPicks = async () => {
    const id = ++pickRequest.current;
    setPickError(undefined);
    try {
      let choices: { ref: string; label: string }[];
      if (stage === "studio" || stage === "production") {
        const [a, d] = await Promise.all([getJson<{ assets: { id: string; name: string }[] }>("/v1/studio/assets"), stage === "production" ? getJson<{ documents: { id: string; title: string }[] }>("/v1/documents") : Promise.resolve({ documents: [] })]);
        choices = [...a.assets.map((x) => ({ ref: `asset:${x.id}`, label: x.name })), ...d.documents.map((x) => ({ ref: `document:${x.id}`, label: x.title || "Untitled" }))];
      } else {
        const d = await getJson<{ documents: { id: string; title: string }[] }>("/v1/documents");
        choices = d.documents.map((x) => ({ ref: `document:${x.id}`, label: x.title || "Untitled" }));
      }
      if (id === pickRequest.current) setPicks(choices);
    } catch (e) { if (id === pickRequest.current) setPickError(`Attachments unavailable: ${(e as Error).message}`); }
  };
  const attach = async (p: { ref: string; label: string }) => {
    const generation = contextGeneration.current;
    try {
      const a = await pipelineApi.attach(taskId, { kind: pickKind, ref: p.ref, label: p.label });
      if (generation !== contextGeneration.current) return;
      setRec((r) => r?.task_id === taskId ? { ...r, attachments: [...r.attachments, a] } : r);
      retry((n) => n + 1);
      toast(`Attached “${p.label}”`);
    } catch (e) { if (generation === contextGeneration.current) toast((e as Error).message, "error"); }
  };
  const advanceCurrent = () => {
    const generation = contextGeneration.current;
    return advance(rec, taskId, onNavigate, setRec, toast, () => generation === contextGeneration.current);
  };
  const nx = nextStage(rec?.stage ?? null);
  const scoped = rec?.attachments.filter((a) => stage === "research" ? a.kind === "source" || a.kind === "note" || a.kind === "document" : stage === "studio" ? a.kind === "asset" || a.kind === "note" : a.kind === "deliverable" || a.kind === "artifact") ?? [];
  return (
    <section className="jg-taskbanner" aria-label="Current task">
      <div className="jg-taskbanner__row">
        <div className="jg-taskbanner__what"><span className="jg-u-note">Current task</span><strong>{task === undefined ? (taskError ? taskId : "Loading…") : task ? title(task) : taskId}</strong></div>
        {!rec && (loading || recordError) ? <span className="jg-u-note">{recordError ? "Stage unavailable" : "Loading stage…"}</span> : <StageStepper stage={rec?.stage ?? null} compact />}
        <div className="jg-ui-toolbar">
          <button type="button" className="jg-u-btn" disabled={loading || !!recordError} onClick={() => { setOpen(!open); if (!open && !picks) void loadPicks(); }} aria-expanded={open}>Attach {pickKind === "asset" ? "asset" : pickKind === "document" ? "document" : "deliverable"}</button>
          {nx && rec && <button type="button" disabled={loading || !!recordError} className="jg-u-btn jg-u-btn--primary" onClick={() => void advanceCurrent()}>Advance to {STAGE_LABEL[nx]}</button>}
          <button type="button" className="jg-u-link" onClick={() => onNavigate(clearTo)}>Clear</button>
        </div>
      </div>
      {(taskError || recordError) && <p className="jg-u-error" role="alert">{[taskError, recordError].filter(Boolean).join(". ")} Last-known details may be shown. <button type="button" className="jg-u-btn" onClick={() => retry((n) => n + 1)}>Retry task details</button></p>}
      {task === null && !taskError && <p className="jg-u-note">This task isn’t in the gateway’s task list any more; attachments still work.</p>}
      {scoped.length > 0 && <ul className="jg-taskbanner__chips">{scoped.map((a) => <li key={a.id}><Badge>{a.kind}</Badge> {a.kind === "source" && a.ref ? <a href={a.ref} target="_blank" rel="noreferrer noopener">{a.label || a.ref}</a> : a.text || a.label || a.ref}</li>)}</ul>}
      {open && (
        <div className="jg-taskbanner__picks">
          {pickError ? <p className="jg-u-error" role="alert">{pickError} <button type="button" className="jg-u-btn" onClick={() => void loadPicks()}>Retry attachments</button></p> : picks === undefined ? <SkeletonRows n={2} /> : picks.length === 0 ? <p className="jg-u-note">Nothing to attach yet.</p> : (
            <ul className="jg-u-list">{picks.map((p) => {
              const on = rec?.attachments.some((a) => a.ref === p.ref && a.kind === pickKind);
              return <li key={p.ref}><button type="button" className="jg-u-row" disabled={on || loading || !!recordError} onClick={() => void attach(p)}>{p.label}<span className="jg-u-note">{on ? "attached" : p.ref.split(":")[0]}</span></button></li>;
            })}</ul>)}
        </div>)}
    </section>
  );
}

/** Work › Production: a task's real outputs — gateway result, task artifacts, attached deliverables. */
export function ProductionPage({ source, params, onNavigate }: { source: JaegerSource; params: URLSearchParams; onNavigate: (to: string) => void }) {
  const { tasks, items, err, load, setItems } = usePipeline(source);
  const taskId = params.get("task");
  const inProd = (tasks ?? []).filter((t) => { const s = items[t.task_id]?.stage; return s === "production" || s === "review" || s === "done"; });
  const [arts, setArts] = useState<TaskArtifact[]>();
  const [artifactError, setArtifactError] = useState<string>();
  const [artifactAttempt, retryArtifacts] = useState(0);
  useEffect(() => {
    let live = true;
    setArts(undefined); setArtifactError(undefined);
    if (taskId && source.taskArtifacts) {
      source.taskArtifacts.list(taskId).then((r) => { if (live) setArts(r.artifacts); }, (e: Error) => { if (live) setArtifactError(e.message); });
    }
    return () => { live = false; };
  }, [source, taskId, artifactAttempt]);
  const task = tasks?.find((t) => t.task_id === taskId);
  const rec = taskId ? items[taskId] : undefined;
  return (
    <div className="jg-u-page">
      <PageHead title="Production" subtitle={taskId ? "Outputs and deliverables for the current task." : "Tasks in Production, Review or Done. Pick one to see its outputs."} actions={<button type="button" className="jg-u-btn" onClick={() => { void load(); retryArtifacts((n) => n + 1); }}>Refresh</button>} />
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {!taskId && !err && (!tasks ? <SkeletonRows n={3} /> : inProd.length === 0 ? <Empty title="Nothing in production">Advance a task from Work › Pipeline when it’s ready to produce.</Empty> : (
        <ul className="jg-pipe-list">{inProd.map((t) => (
          <li key={t.task_id} className="jg-u-card jg-pipe-card">
            <div className="jg-pipe-card__head"><button type="button" className="jg-pipe-card__title" onClick={() => onNavigate(`/work/production?task=${encodeURIComponent(t.task_id)}`)}>{title(t)}</button><Badge tone={stateTone(t.state)}>{t.state ?? "unknown"}</Badge></div>
            <StageStepper stage={items[t.task_id]?.stage ?? null} compact />
          </li>))}</ul>))}
      {taskId && (
        <div className="jg-u-grid">
          <section className="jg-u-card"><h2>Result</h2>
            {task ? (task.result != null ? <pre className="jg-pipe-result">{typeof task.result === "string" ? task.result : JSON.stringify(task.result, null, 2)}</pre> : <p className="jg-u-note">{task.error || `No result yet (gateway state: ${task.state ?? "unknown"}).`}</p>) : err ? <p className="jg-u-note">Result unavailable. Refresh to retry.</p> : tasks ? <p className="jg-u-note">This task is not in the current task list.</p> : <SkeletonRows n={2} />}
          </section>
          <section className="jg-u-card"><h2>Task artifacts <span className="jg-u-count">{arts?.length ?? ""}</span></h2>
            {!source.taskArtifacts ? <p className="jg-u-note">This gateway doesn’t expose task artifacts.</p> : artifactError ? <p className="jg-u-error" role="alert">Task artifacts unavailable: {artifactError} <button type="button" className="jg-u-btn" onClick={() => retryArtifacts((n) => n + 1)}>Retry artifacts</button></p> : arts === undefined ? <SkeletonRows n={2} /> : arts.length === 0 ? <p className="jg-u-note">No files produced by this task.</p> : (
              <ul className="jg-u-list">{arts.map((a) => <li key={a.attachment_id} className="jg-pipe-attach__row"><span>{a.name}</span><span className="jg-u-note">{a.mime} · {Math.round(a.size / 1024)} KB</span></li>)}</ul>)}
          </section>
          <section className="jg-u-card jg-u-card--wide"><h2>Deliverables</h2>
            {err ? <p className="jg-u-note">Deliverables unavailable. Refresh to retry.</p> : !tasks ? <SkeletonRows n={2} /> : rec ? <Attachments taskId={taskId} rec={rec} onChange={(r) => setItems((m) => ({ ...m, [r.task_id]: r }))} kinds={[]} filter={["deliverable", "asset", "document", "artifact"]} /> : <p className="jg-u-note">Use “Attach deliverable” above to add Studio assets or documents.</p>}
          </section>
        </div>)}
    </div>
  );
}
