import { useEffect, useMemo, useState } from "react";
import type { JaegerSource, ScheduleJob } from "../api/source";
import type { Task } from "../api/types";
import { Badge, Empty, Segmented, SkeletonRows, PageHead } from "./ui";
import "./workWorkspace.css";
import { WorkScheduleTabs } from "./WorkScheduleTabs";

const finished = new Set(["done", "completed", "completed_verified", "failed", "cancelled", "canceled", "denied", "rejected"]);
const dayLabel = (d: Date) => d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
type Entry = { id: string; title: string; kind: "schedule" | "task"; at: Date; href: string };

export function calendarEntries(schedules: ScheduleJob[], tasks: Task[]): Entry[] {
  const entries: Entry[] = [];
  for (const j of schedules) if (j.enabled && j.next_fire_at) entries.push({
    id: j.id, title: j.name, kind: "schedule", at: new Date(j.next_fire_at), href: `/automations?job=${encodeURIComponent(j.id)}`,
  });
  for (const t of tasks) if (t.eta && !finished.has(String(t.state))) entries.push({
    id: t.task_id, title: t.goal || "Untitled task", kind: "task",
    at: new Date(typeof t.eta === "number" ? t.eta * (t.eta < 1e12 ? 1000 : 1) : t.eta),
    href: `/work/tasks?task=${encodeURIComponent(t.task_id)}`,
  });
  return entries.filter(i => Number.isFinite(+i.at)).sort((a, b) => +a.at - +b.at);
}

export function CalendarPage({ source, onNavigate }: { source: JaegerSource; onNavigate: (to: string) => void }) {
  const [data, setData] = useState<{ schedules: ScheduleJob[]; tasks: Task[]; warnings: string[] }>();
  const [filter, setFilter] = useState<"all" | "schedule" | "task">("all");
  useEffect(() => {
    let alive = true;
    const schedules = source.schedules;
    void Promise.allSettled([schedules ? schedules.list().then(r => r.jobs) : Promise.resolve([]), source.tasks()]).then(([jobs, tasks]) => {
      if (!alive) return;
      setData({ schedules: jobs.status === "fulfilled" ? jobs.value : [], tasks: tasks.status === "fulfilled" ? tasks.value : [],
        warnings: [...(!schedules ? ["Automations aren’t available on this connection."] : jobs.status === "rejected" ? ["Couldn’t load automation times."] : []),
          ...(tasks.status === "rejected" ? ["Couldn’t load task due dates."] : [])] });
    });
    return () => { alive = false; };
  }, [source]);
  const entries = useMemo(() => calendarEntries(data?.schedules ?? [], data?.tasks ?? []).filter(i => filter === "all" || i.kind === filter), [data, filter]);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const overdue = entries.filter(i => i.kind === "task" && i.at < today);
  const days = new Map<string, Entry[]>();
  for (const i of entries) if (i.at >= today || i.kind === "schedule") {
    const label = i.at.toDateString() === today.toDateString() ? "Today" : dayLabel(i.at);
    days.set(label, [...(days.get(label) ?? []), i]);
  }
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const rows = (items: Entry[], showDate = false) => <ul className="jg-work-list">{items.map(i => <li key={`${i.kind}:${i.id}`}>
    <time dateTime={i.at.toISOString()}>{showDate ? i.at.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : i.at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</time>
    <span><strong>{i.title}</strong><small>{i.kind === "task" ? "Task due" : "Automation run"}</small></span>
    <button type="button" className="jg-u-btn" onClick={() => onNavigate(i.href)}>{i.kind === "task" ? "Open task" : "Open automation"}</button>
  </li>)}</ul>;
  return <div className="jg-u-page jg-work-density">
    <PageHead title="Schedule" subtitle="See upcoming runs and task deadlines by day." actions={source.schedules && <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => onNavigate("/automations?new=1")}>New automation</button>} />
    <WorkScheduleTabs active="agenda" onNavigate={onNavigate} />
    <div className="jg-work-toolbar">
      <Segmented label="Calendar entries" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "schedule", label: "Automations" }, { value: "task", label: "Task deadlines" }]} />
      <small className="jg-u-note">{timeZone}</small>
    </div>
    {data?.warnings.map(w => <p className="jg-u-note" role="status" key={w}>{w}</p>)}
    <div className="jg-work-agenda" aria-label="Work agenda">
      {!data ? <SkeletonRows /> : !entries.length ? <Empty title={data.warnings.length ? "No dates available to show" : "No dates to show"}>Due dates and the next run of each active automation appear here.</Empty> : <>
        {overdue.length > 0 && <section aria-label="Overdue tasks"><h2>Overdue <Badge tone="warn">{overdue.length}</Badge></h2>{rows(overdue, true)}</section>}
        {[...days].map(([day, items]) => <section key={day} aria-label={day}><h2>{day}</h2>{rows(items)}</section>)}
      </>}
    </div>
  </div>;
}
