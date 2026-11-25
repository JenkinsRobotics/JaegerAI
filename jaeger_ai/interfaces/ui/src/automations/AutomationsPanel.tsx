import { useCallback, useEffect, useRef, useState } from "react";
import type { ControlResult, ScheduleAction, ScheduleControls, ScheduleJob } from "../api/source";
import { Badge, Empty, PageHead, Sheet, SkeletonRows } from "../unified/ui";
import { WorkScheduleTabs } from "../unified/WorkScheduleTabs";
import "../unified/workWorkspace.css";
const KEY = "jaeger.ui.schedule-operation.v1";
interface Pending { version: 1; operationId: string; action: ScheduleAction }
/** Intent is device-local; definitions and outcomes belong exclusively to the existing Gateway owner. */
export function AutomationsPanel({ controls, initialNew = false, initialJob, onNavigate }: { controls: ScheduleControls; initialNew?: boolean; initialJob?: string | null; onNavigate?: (path: string) => void }) {
  const [jobs, setJobs] = useState<ScheduleJob[]>(), [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [editing, setEditing] = useState<ScheduleJob | "new" | undefined>(initialNew ? "new" : undefined);
  const [name, setName] = useState(""), [prompt, setPrompt] = useState(""), [cron, setCron] = useState("0 9 * * *");
  const [customTiming, setCustomTiming] = useState(false);
  const [zone, setZone] = useState("");
  const [pending, setPending] = useState<Pending>(), [busy, setBusy] = useState(false), locked = useRef(false);
  const [history, setHistory] = useState<{ name: string; data: Awaited<ReturnType<ScheduleControls["history"]>> }>();
  const [openingHistory, setOpeningHistory] = useState<string>();
  const [jobFocus, setJobFocus] = useState(initialJob);
  const [confirm, setConfirm] = useState<{ action: ScheduleAction; job: ScheduleJob }>();
  const closeEdit = useCallback(() => { if (!busy) setEditing(undefined); }, [busy]);
  const closeHistory = useCallback(() => setHistory(undefined), []);
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
      const body = { operation_id: intent.operationId, ...(job ? { job_id: job.name } : {}), ...(["create", "update"].includes(action) ? { name, prompt, schedule: cron, timezone: zone, ...(job && typeof job.config_revision === "number" ? {expected_revision:job.config_revision} : {}) } : {}) };
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
  const edit = (job: ScheduleJob | "new") => {
    const rule = job === "new" ? "0 9 * * *" : job.cron;
    setEditing(job); setName(job === "new" ? "" : job.name); setPrompt(job === "new" ? "" : job.prompt);
    setCron(rule); setCustomTiming(!simpleTiming(rule)); setZone(job === "new" ? "" : job.timezone ?? "");
  };
  const timing = simpleTiming(cron);
  const shown = jobs?.filter(job => !jobFocus || job.id === jobFocus || job.name === jobFocus);
  const recorded = history ? new Set(history.data.tasks.map(t => t.provenance?.request_id).filter(Boolean)) : new Set();
  return <section aria-label="Automations" className="jg-u-page jg-work-density">
    <PageHead title={onNavigate ? "Schedule" : "Automations"} subtitle="Set up recurring work and check what happened on past runs." actions={<>
      <button className="jg-u-btn jg-u-btn--primary" type="button" disabled={busy || Boolean(pending)} onClick={() => edit("new")}>New automation</button>
    </>} />
    {onNavigate && <WorkScheduleTabs active="automations" onNavigate={onNavigate} />}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <p role="alert">A previous {pending.action} operation needs reconciliation. <button type="button" disabled={busy} onClick={() => void reconcile()}>Check saved operation</button></p>}
    <div className="jg-work-toolbar">
      {jobFocus && <button type="button" className="jg-u-btn" onClick={() => { setJobFocus(null); onNavigate?.("/automations"); }}>All automations</button>}
      <button type="button" className="jg-u-btn" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh automations</button>
    </div>
    {!jobs && !error && <SkeletonRows />}
    {shown?.length === 0 && <Empty title={jobFocus ? "Automation not found" : "No automations yet"}>{jobFocus ? "Check the full list for this schedule." : "Create an automation for work you want Jaeger to repeat."}</Empty>}
    {Boolean(shown?.length) && <ul className="jg-work-list" aria-label="Schedules">{shown?.map(job => <li key={job.id}>
      <div className="jg-work-rule">
        <strong>{job.name}</strong> <Badge tone={job.enabled && job.state !== "cancelled" ? "ok" : undefined}>{job.state === "cancelled" ? "Cancelled" : job.enabled ? "On" : "Paused"}</Badge>
        <small>{job.enabled && job.next_fire_at ? <>Next run <time dateTime={job.next_fire_at}>{new Date(job.next_fire_at).toLocaleString()}</time></> : "No next run scheduled"}</small>
        <details><summary>Schedule and instructions</summary><small>{job.cron} · {job.timezone ?? "Gateway local time"}</small><small>{job.prompt}</small></details>
      </div>
      <div className="jg-work-actions">
        <button type="button" className="jg-u-btn" disabled={busy || Boolean(openingHistory)} onClick={() => {
          setOpeningHistory(job.name);
          void controls.history(job.name).then(data => setHistory({ name: job.name, data }), e => setError(String(e))).finally(() => setOpeningHistory(undefined));
        }}>{openingHistory === job.name ? "Loading history…" : "Run history"}</button>
        {job.state === "cancelled" ? <button className="jg-u-btn" type="button" disabled={busy || Boolean(pending)} onClick={() => void mutate("restore", job)}>Restore paused</button> : <>
          <button className="jg-u-btn" type="button" disabled={busy || Boolean(pending)} onClick={() => edit(job)}>Edit automation</button>
          <details className="jg-work-more"><summary>More actions</summary><div className="jg-work-actions">
            <button className="jg-u-btn" type="button" disabled={busy || Boolean(pending)} onClick={() => void mutate(job.enabled ? "pause" : "resume", job)}>{job.enabled ? "Pause" : "Resume"}</button>
            <button className="jg-u-btn" type="button" disabled={busy || Boolean(pending)} onClick={() => setConfirm({ action: "run", job })}>Run now…</button>
            <button className="jg-u-btn" type="button" disabled={busy || Boolean(pending)} onClick={() => setConfirm({ action: "delete", job })}>Cancel schedule…</button>
          </div></details>
        </>}
      </div>
    </li>)}</ul>}
    {editing && <Sheet title={editing === "new" ? "New automation" : "Edit automation"} onClose={closeEdit}>
      <form className="jg-stack" aria-label="Automation editor" onSubmit={e => { e.preventDefault(); void mutate(editing === "new" ? "create" : "update", editing === "new" ? undefined : editing); }}>
        <label className="jg-ui-field">Name<input aria-label="Automation name" disabled={busy || editing !== "new"} value={name} onChange={e => setName(e.target.value)} required /></label>
        <label className="jg-ui-field">What should Jaeger do?<textarea aria-label="Automation objective" disabled={busy} value={prompt} onChange={e => setPrompt(e.target.value)} required /></label>
        <div className="jg-work-toolbar">
          <label className="jg-ui-field">Repeat<select disabled={busy} value={customTiming ? "custom" : timing?.days ?? "*"} onChange={e => {
            if (e.target.value === "custom") { setCustomTiming(true); return; }
            setCustomTiming(false);
            setCron(`${timing?.minute ?? 0} ${timing?.hour ?? 9} * * ${e.target.value}`);
          }}><option value="*">Every day</option><option value="1-5">Weekdays</option><option value="custom">Custom schedule</option></select></label>
          {!customTiming && <label className="jg-ui-field">At<input type="time" required disabled={busy} value={timing ? `${String(timing.hour).padStart(2, "0")}:${String(timing.minute).padStart(2, "0")}` : ""} onChange={e => {
            const [h, m] = e.target.value.split(":");
            setCron(h && m ? `${Number(m)} ${Number(h)} * * ${timing?.days ?? "*"}` : "");
          }} /></label>}
        </div>
        {customTiming && <label className="jg-ui-field">Cron expression<input aria-label="Cron expression" disabled={busy} value={cron} onChange={e => setCron(e.target.value)} required /></label>}
        <label className="jg-ui-field">Time zone<input aria-label="Automation timezone" disabled={busy} value={zone} onChange={e => setZone(e.target.value)} placeholder="Gateway local, or America/Los_Angeles" /></label>
        <p className="jg-u-note">{customTiming && "For example, 0 9 * * 1-5 runs at 9 AM on weekdays. "}Leave the time zone blank to use the Gateway’s time zone.</p>
        <div className="jg-work-actions"><button className="jg-u-btn jg-u-btn--primary" disabled={busy || Boolean(pending) || !name.trim() || !prompt.trim() || !cron.trim()}>Save automation</button><button className="jg-u-btn" type="button" disabled={busy} onClick={closeEdit}>Close editor</button></div>
      </form>
    </Sheet>}
    {confirm && <section role="alertdialog" aria-label="Confirm automation action"><p>{confirm.action === "run" ? "Queue this automation once using existing task execution and tool permissions?" : "Cancel this schedule? Its definition and run history remain recoverable."}</p><button type="button" onClick={() => setConfirm(undefined)}>Back</button><button type="button" disabled={busy} onClick={() => void mutate(confirm.action, confirm.job)}>Confirm {confirm.action === "run" ? "run" : "cancellation"}</button></section>}
    {history && <Sheet title={`Run history · ${history.name}`} onClose={closeHistory}>
      {!history.data.tasks.length && !history.data.requests.length ? <Empty title="No recorded runs yet" /> :
        <ul className="jg-work-list" aria-label="Recorded runs">
          {history.data.tasks.map(t => <li key={t.task_id}><div><strong>{t.goal || "Automation run"}</strong><small>{t.updated_at ? new Date(t.updated_at * 1000).toLocaleString() : ""}</small></div><Badge>{runStatus(t.state)}</Badge></li>)}
          {history.data.requests.filter(r => !recorded.has(r.request_id)).map(r => <li key={r.request_id}><strong>Automation run</strong><Badge>{runStatus(r.status)}</Badge></li>)}
        </ul>}
      <details className="jg-work-secondary"><summary>Technical details</summary><pre className="jg-work-raw">{JSON.stringify(history.data, null, 2)}</pre></details>
      <button type="button" className="jg-u-btn" onClick={closeHistory}>Close history</button>
    </Sheet>}
  </section>;
}
const runStatus = (state?: string) => state ? state.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : "Status unavailable";
export function simpleTiming(rule: string) {
  const parts = /^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+(\*|1-5)$/.exec(rule.trim());
  if (!parts || Number(parts[1]) > 59 || Number(parts[2]) > 23) return undefined;
  return { minute: Number(parts[1]), hour: Number(parts[2]), days: parts[3] };
}
