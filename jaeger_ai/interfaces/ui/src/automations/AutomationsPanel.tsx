import { useEffect, useRef, useState } from "react";
import type { ControlResult, ScheduleAction, ScheduleControls, ScheduleJob } from "../api/source";
const KEY = "jaeger.ui.schedule-operation.v1";
interface Pending { version: 1; operationId: string; action: ScheduleAction }
/** Intent is device-local; definitions and outcomes belong exclusively to the existing Gateway owner. */
export function AutomationsPanel({ controls }: { controls: ScheduleControls }) {
  const [jobs, setJobs] = useState<ScheduleJob[]>(), [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [editing, setEditing] = useState<ScheduleJob | "new">();
  const [name, setName] = useState(""), [prompt, setPrompt] = useState(""), [cron, setCron] = useState("0 9 * * *");
  const [pending, setPending] = useState<Pending>(), [busy, setBusy] = useState(false), locked = useRef(false);
  const [history, setHistory] = useState<{ name: string; data: unknown }>();
  const [confirm, setConfirm] = useState<{ action: ScheduleAction; job: ScheduleJob }>();
  useEffect(() => {
    try { const raw = localStorage.getItem(KEY); if (raw) { const saved = JSON.parse(raw); if (saved.version !== 1 || typeof saved.operationId !== "string") throw new Error("Invalid saved operation; original record preserved"); setPending(saved); } }
    catch (e) { setError(`Operation recovery unavailable: ${String(e)}`); locked.current = true; }
  }, []);
  useEffect(() => {
    let live = true;
    void controls.list().then(value => { if (live) setJobs(value.jobs); }, e => { if (live) setError(String((e as Error).message ?? e)); });
    return () => { live = false; };
  }, [controls, attempt]);
  const acknowledge = (receipt: ControlResult) => {
    if (!receipt.ok) throw new Error(receipt.error ?? "Action rejected");
    setNotice(`Action recorded (${receipt.operation_id}). Execution results appear in run history and Tasks.`);
  };
  const mutate = async (action: ScheduleAction, job?: ScheduleJob) => {
    if (locked.current || pending) return; locked.current = true; setBusy(true); setError(undefined); setNotice(undefined); setConfirm(undefined);
    const intent: Pending = { version: 1, operationId: crypto.randomUUID(), action };
    let journaled = false;
    try {
      localStorage.setItem(KEY, JSON.stringify(intent)); journaled = true; setPending(intent);
      const body = { operation_id: intent.operationId, ...(job ? { job_id: job.name } : {}), ...(["create", "update"].includes(action) ? { name, prompt, schedule: cron } : {}) };
      const receipt = await controls.mutate(action, body);
      if (receipt.operation_id !== intent.operationId) throw new Error("Action identity mismatch");
      // A known rejection is a settled operation too; never retry this command ID.
      localStorage.removeItem(KEY); setPending(undefined); acknowledge(receipt); setEditing(undefined); setAttempt(n => n + 1);
    } catch (e) {
      setError(`${String((e as Error).message ?? e)}${journaled ? ". Check the saved operation; nothing is replayed automatically." : ". Nothing submitted."}`);
    } finally { locked.current = false; setBusy(false); }
  };
  const reconcile = async () => {
    if (!pending || locked.current) return; locked.current = true; setBusy(true); setError(undefined);
    try {
      const row = await controls.operation(pending.operationId);
      if (!row.receipt || row.receipt.operation_id !== pending.operationId) throw new Error("Operation remains unknown; inspect current definitions and history, do not resubmit");
      localStorage.removeItem(KEY); setPending(undefined); acknowledge(row.receipt); setAttempt(n => n + 1);
    } catch (e) { setError(String((e as Error).message ?? e)); }
    finally { locked.current = false; setBusy(false); }
  };
  const edit = (job: ScheduleJob | "new") => { setEditing(job); setName(job === "new" ? "" : job.name); setPrompt(job === "new" ? "" : job.prompt); setCron(job === "new" ? "0 9 * * *" : job.cron); };
  return <section aria-label="Automations">
    <p>Gateway-owned schedules. Cron expressions use the Gateway's timezone. Restore always leaves a cancelled schedule paused.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <p role="alert">A previous {pending.action} operation needs reconciliation. <button type="button" disabled={busy} onClick={() => void reconcile()}>Check saved operation</button></p>}
    <button type="button" disabled={busy || Boolean(pending)} onClick={() => edit("new")}>New automation</button><button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh automations</button>
    {!jobs && !error && <p role="status">Loading automations…</p>}
    {jobs?.map(job => <article key={job.id} className="jg-card"><strong>{job.name}</strong><p>{job.prompt}</p><p>{job.cron} · {job.state}{job.next_fire_at ? ` · Next ${job.next_fire_at}` : ""}</p>
      {job.state === "cancelled" ? <button type="button" disabled={busy || Boolean(pending)} onClick={() => void mutate("restore", job)}>Restore paused</button> : <>
        <button type="button" disabled={busy || Boolean(pending)} onClick={() => edit(job)}>Edit automation</button>
        <button type="button" disabled={busy || Boolean(pending)} onClick={() => void mutate(job.enabled ? "pause" : "resume", job)}>{job.enabled ? "Pause" : "Resume"}</button>
        <button type="button" disabled={busy || Boolean(pending)} onClick={() => setConfirm({ action: "run", job })}>Run now…</button>
        <button type="button" disabled={busy || Boolean(pending)} onClick={() => setConfirm({ action: "delete", job })}>Cancel schedule…</button>
      </>}
      <button type="button" disabled={busy} onClick={() => { setHistory(undefined); void controls.history(job.name).then(data => setHistory({ name: job.name, data }), e => setError(String(e))); }}>Run history</button>
    </article>)}
    {editing && <form className="jg-task-form" aria-label="Automation editor" onSubmit={e => { e.preventDefault(); void mutate(editing === "new" ? "create" : "update", editing === "new" ? undefined : editing); }}>
      <label>Name <input aria-label="Automation name" disabled={busy || editing !== "new"} value={name} onChange={e => setName(e.target.value)} required /></label>
      <label>Objective <textarea aria-label="Automation objective" disabled={busy} value={prompt} onChange={e => setPrompt(e.target.value)} required /></label>
      <label>Cron expression <input aria-label="Cron expression" disabled={busy} value={cron} onChange={e => setCron(e.target.value)} required /></label>
      <button disabled={busy || Boolean(pending) || !name.trim() || !prompt.trim() || !cron.trim()}>Save automation</button><button type="button" disabled={busy} onClick={() => setEditing(undefined)}>Close editor</button>
    </form>}
    {confirm && <section role="alertdialog" aria-label="Confirm automation action"><p>{confirm.action === "run" ? "Queue this automation once using existing task execution and tool permissions?" : "Cancel this schedule? Its definition and run history remain recoverable."}</p><button type="button" onClick={() => setConfirm(undefined)}>Back</button><button type="button" disabled={busy} onClick={() => void mutate(confirm.action, confirm.job)}>Confirm {confirm.action === "run" ? "run" : "cancellation"}</button></section>}
    {history && <details open><summary>Run history · {history.name}</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(history.data, null, 2)}</pre></details>}
  </section>;
}
