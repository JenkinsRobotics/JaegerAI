/** Calendar (unified UI): scheduled agent jobs on an agenda by next run, plus task due dates;
 * create, pause/resume, run now and delete through the gateway's schedule controls. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource, ScheduleJob } from "../api/source";
import type { Task } from "../api/types";
import { Badge, Empty, Sheet, SkeletonRows, useToast, PageHead } from "./ui";

const dayKey = (d: Date) => d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });

export function CalendarPage({ source, onNavigate }: { source: JaegerSource; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const [jobs, setJobs] = useState<ScheduleJob[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [err, setErr] = useState<string>();
  const [taskErr, setTaskErr] = useState<string>();
  const request = useRef(0);
  const [creating, setCreating] = useState(false);
  const [f, setF] = useState({ name: "", prompt: "", schedule: "0 9 * * 1-5", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
  const load = useCallback(() => {
    const id = ++request.current;
    setJobs(null); setTasks(null); setErr(undefined); setTaskErr(undefined);
    if (!source.schedules) setErr("This gateway has no scheduler.");
    else source.schedules.list().then((r) => { if (id === request.current) setJobs(r.jobs); }, (e: Error) => { if (id === request.current) setErr(`Schedules unavailable: ${e.message}`); });
    source.tasks().then((t) => { if (id === request.current) setTasks(t.filter((x) => x.eta && !["done", "succeeded", "cancelled", "failed"].includes(String(x.state)))); }, (e: Error) => { if (id === request.current) setTaskErr(`Task due dates unavailable: ${e.message}`); });
  }, [source]);
  useEffect(() => { load(); return () => { ++request.current; }; }, [load]);
  const agenda = useMemo(() => {
    const items: { at: Date; kind: "job" | "task"; job?: ScheduleJob; task?: Task }[] = [];
    for (const j of jobs ?? []) if (j.enabled && j.next_fire_at) items.push({ at: new Date(j.next_fire_at), kind: "job", job: j });
    for (const t of tasks ?? []) { const at = new Date(typeof t.eta === "number" ? t.eta * 1000 : String(t.eta)); if (!isNaN(+at)) items.push({ at, kind: "task", task: t }); }
    items.sort((a, b) => +a.at - +b.at);
    const days = new Map<string, typeof items>();
    for (const i of items) days.set(dayKey(i.at), [...(days.get(dayKey(i.at)) ?? []), i]);
    return [...days.entries()];
  }, [jobs, tasks]);
  const mutate = async (action: "pause" | "resume" | "run" | "delete" | "create", j?: ScheduleJob) => {
    if (!source.schedules) return;
    if (action === "delete" && !confirm(`Delete schedule “${j!.name}”?`)) return;
    try {
      const r = await source.schedules.mutate(action, action === "create" ? { operation_id: crypto.randomUUID(), ...f } : { operation_id: crypto.randomUUID(), job_id: j!.id, expected_revision: j!.config_revision });
      if (!r.ok) throw new Error(r.error ?? "rejected");
      toast(action === "create" ? "Schedule created" : action === "run" ? "Run requested" : `Schedule ${action}d`);
      if (action === "create") setCreating(false);
      load();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="jg-u-page">
      <PageHead title="Calendar" subtitle="Scheduled agent jobs and task due dates." actions={<><button type="button" className="jg-u-btn" onClick={load}>Refresh</button><button type="button" className="jg-u-btn" onClick={() => onNavigate("/work/tasks")}>Tasks</button>{source.schedules && <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => setCreating(true)}>New schedule</button>}</>} />
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {taskErr && <p className="jg-u-error" role="alert">{taskErr}</p>}
      <div className="jg-ui-split">
        <section className="jg-u-card" aria-label="Agenda">
          <h2>Upcoming</h2>
          {(!jobs && !err) || (!tasks && !taskErr) ? <SkeletonRows n={4} /> : !agenda.length ? (err || taskErr ? <p className="jg-u-note">Agenda incomplete. Refresh to retry unavailable sources.</p> : <Empty title="Nothing scheduled" action={source.schedules ? <button type="button" className="jg-u-btn" onClick={() => setCreating(true)}>Schedule a job</button> : undefined} />) : agenda.map(([day, items]) => (
            <div key={day} className="jg-kn__group"><h3>{day}</h3>
              <ul className="jg-u-list">{items.map((i, k) => (
                <li key={k} className="jg-cal__item"><time>{i.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time>
                  <span className="jg-u-row__text"><strong>{i.job?.name ?? i.task?.goal}</strong><span>{i.kind === "job" ? `Schedule · ${i.job!.cron}` : `Task due · ${i.task!.state}`}</span></span></li>))}</ul></div>))}
        </section>
        <aside className="jg-ui-inspector" aria-label="Schedules">
          <h3>All schedules</h3>
          {!jobs ? (err ? <p className="jg-u-note">Schedules unavailable.</p> : <SkeletonRows />) : !jobs.length ? <p className="jg-u-note">No schedules.</p> : (
            <ul className="jg-u-list">{jobs.map((j) => (
              <li key={j.id} className="jg-cal__job"><strong>{j.name}</strong> <Badge tone={j.enabled ? "ok" : undefined}>{j.enabled ? "On" : "Paused"}</Badge>
                <small>{j.cron}{j.timezone ? ` · ${j.timezone}` : ""}{j.next_fire_at ? ` · next ${new Date(j.next_fire_at).toLocaleString()}` : ""}</small>
                <small className="jg-cal__prompt">{j.prompt}</small>
                <div className="jg-ui-toolbar">
                  <button type="button" className="jg-u-icon-btn" onClick={() => void mutate(j.enabled ? "pause" : "resume", j)}>{j.enabled ? "Pause" : "Resume"}</button>
                  <button type="button" className="jg-u-icon-btn" onClick={() => void mutate("run", j)}>Run now</button>
                  <button type="button" className="jg-u-icon-btn" onClick={() => void mutate("delete", j)}>Delete</button>
                </div></li>))}</ul>)}
        </aside>
      </div>
      {creating && (
        <Sheet title="New schedule" onClose={() => setCreating(false)}>
          <form className="jg-stack" onSubmit={(e) => { e.preventDefault(); void mutate("create"); }}>
            <label className="jg-ui-field">Name<input required maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Morning briefing" /></label>
            <label className="jg-ui-field">What should Jaeger do?<textarea required rows={4} value={f.prompt} onChange={(e) => setF({ ...f, prompt: e.target.value })} /></label>
            <label className="jg-ui-field">Schedule (cron)<input required value={f.schedule} onChange={(e) => setF({ ...f, schedule: e.target.value })} /></label>
            <label className="jg-ui-field">Time zone<input value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></label>
            <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={() => setCreating(false)}>Cancel</button><button className="jg-u-btn jg-u-btn--primary" disabled={!f.name.trim() || !f.prompt.trim()}>Create</button></div>
          </form>
        </Sheet>)}
    </div>
  );
}
