/**
 * Work › Backlog: Matthew's project task list (gateway /v1/backlog, SQLite source of truth).
 * Filter by status, priority and worker; inline priority/status; Approve for needs_ok; Assign
 * makes a real hub handoff to ARES, Muse, the rack PC or Grok Bot. Live: new activity rows
 * (backlog.updated / handoff.*) trigger a reload. Deep links: /work/backlog?status=needs_ok&worker=ares.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Badge, Empty, PageHead, Segmented, SkeletonRows, useToast, type Tone } from "./ui";
import { getJson } from "./webui";
import { backlogApi, matchBacklog, PRIORITIES, STATUSES, statusLabel, WORKERS, workerLabel, type BacklogList, type BacklogPriority, type BacklogStatus, type BacklogTask } from "./backlog";

const tone: Record<BacklogStatus, Tone> = { needs_ok: "warn", in_progress: undefined, open: undefined, done: "ok" };
const ago = (t: number) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };
const LIVE_KINDS = /^(backlog\.updated|handoff\.)/;

export function BacklogPage({ params }: { params: URLSearchParams }) {
  const toast = useToast();
  const [data, setData] = useState<BacklogList>();
  const [err, setErr] = useState<string>();
  const [status, setStatus] = useState(params.get("status") ?? "active");
  const [priority, setPriority] = useState(params.get("priority") ?? "");
  const [worker, setWorker] = useState(params.get("worker") ?? "");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(params.get("task"));
  const [busy, setBusy] = useState<string>();
  const lastEvent = useRef<number>(0);

  const load = useCallback(async () => {
    try { setData(await backlogApi.list()); setErr(undefined); } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  // Live status: poll the activity feed (cheap) and reload only when a backlog or handoff row lands.
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const page = await getJson<{ items: { event_id: number; kind: string }[] }>("/v1/activity?limit=20");
        const fresh = page.items.filter((i) => i.event_id > lastEvent.current);
        if (lastEvent.current && fresh.some((i) => LIVE_KINDS.test(i.kind))) void load();
        lastEvent.current = Math.max(lastEvent.current, ...page.items.map((i) => i.event_id), 0);
      } catch { /* feed unavailable: manual refresh still works */ }
      if (!stop) timer = setTimeout(tick, 5000);
    };
    let timer = setTimeout(tick, 0);
    return () => { stop = true; clearTimeout(timer); };
  }, [load]);

  const rows = useMemo(() => (data?.tasks ?? []).filter(matchBacklog({ status, priority, worker, q })), [data, status, priority, worker, q]);
  const put = (t: BacklogTask) => setData((d) => d && { ...d, tasks: d.tasks.map((x) => (x.id === t.id ? t : x)) });
  const act = async (id: string, fn: () => Promise<{ task: BacklogTask }>, ok: string) => {
    setBusy(id);
    try { put((await fn()).task); toast(ok); void load(); } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(undefined); }
  };
  const counts = data?.counts ?? {};

  return (
    <div className="jg-u-page jg-backlog">
      <PageHead title="Backlog" subtitle={data ? `${rows.length} of ${data.tasks.length} tasks · ${counts.needs_ok ?? 0} need your OK · ${counts.in_progress ?? 0} in progress` : "Every Jaeger project task, who has it and what needs your OK."}
        actions={<>
          <input className="jg-u-search" type="search" placeholder="Search backlog" aria-label="Search backlog" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="button" className="jg-u-btn" onClick={() => void load()}>Refresh</button>
          <button type="button" className="jg-u-btn jg-u-btn--primary" aria-pressed={adding} onClick={() => setAdding((v) => !v)}>{adding ? "Close" : "New task"}</button>
        </>} />
      <div className="jg-backlog__filters">
        <Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "active", label: "Not done" }, ...STATUSES, { value: "", label: "All" }]} />
        <select className="jg-ui-input" aria-label="Filter by priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">All priorities</option>{PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select className="jg-ui-input" aria-label="Filter by worker" value={worker} onChange={(e) => setWorker(e.target.value)}>
          <option value="">All workers</option>{WORKERS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}<option value="none">Unassigned</option>
        </select>
      </div>
      {adding && <NewTask onDone={(t) => { setAdding(false); setData((d) => d && { ...d, tasks: [t, ...d.tasks] }); toast("Added to backlog"); void load(); }} />}
      {err && <p className="jg-u-error" role="alert">{err}</p>}
      {!data && !err && <SkeletonRows n={5} />}
      {data && data.tasks.length === 0 && <Empty title="Backlog is empty" action={<button type="button" className="jg-u-btn" onClick={() => void backlogApi.importFile().then((r) => { toast(`Imported ${r.added} tasks`); void load(); }, (e: Error) => toast(e.message, "error"))}>Import ~/Documents/Jaeger-Backlog.md</button>}>Add a task, or import the backlog file.</Empty>}
      {data && data.tasks.length > 0 && rows.length === 0 && <Empty title="No tasks match these filters" />}
      <ul className="jg-backlog__list">
        {rows.map((t) => (
          <li key={t.id} className="jg-u-card jg-backlog__card" data-status={t.status} data-busy={busy === t.id || undefined}>
            <div className="jg-backlog__head">
              <select className="jg-ui-input jg-backlog__prio" data-prio={t.priority} aria-label={`Priority of ${t.title}`} value={t.priority} disabled={busy === t.id}
                onChange={(e) => void act(t.id, () => backlogApi.update(t.id, { priority: e.target.value as BacklogPriority }), `Priority ${e.target.value}`)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <button type="button" className="jg-backlog__title" aria-expanded={open === t.id} onClick={() => setOpen((o) => (o === t.id ? null : t.id))}>{t.title}</button>
              <Badge tone={tone[t.status]}>{statusLabel(t.status)}</Badge>
            </div>
            <div className="jg-backlog__meta">
              <span>{workerLabel(t.worker)}</span>
              {t.last_note && <span title={t.last_note}>· {t.last_note}</span>}
              <span>· {ago(t.updated_at)}</span>
            </div>
            {open === t.id && (
              <div className="jg-backlog__detail">
                {t.detail && <p>{t.detail}</p>}
                <dl>
                  <dt>Source</dt><dd>{t.source || "—"}</dd>
                  <dt>Task id</dt><dd><code>{t.id}</code></dd>
                  {t.handoff_id && <><dt>Handoff</dt><dd><code>{t.handoff_id}</code></dd></>}
                </dl>
              </div>
            )}
            <div className="jg-backlog__actions">
              {t.status === "needs_ok" && <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={busy === t.id}
                onClick={() => void act(t.id, () => backlogApi.update(t.id, { status: t.handoff_id ? "in_progress" : "open" }), "Approved")}>Approve</button>}
              <select className="jg-ui-input" aria-label={`Status of ${t.title}`} value={t.status} disabled={busy === t.id}
                onChange={(e) => void act(t.id, () => backlogApi.update(t.id, { status: e.target.value as BacklogStatus }), `Marked ${statusLabel(e.target.value)}`)}>
                {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              <select className="jg-ui-input" aria-label={`Assign ${t.title}`} value="" disabled={busy === t.id || t.status === "done"}
                onChange={(e) => { const w = e.target.value; if (w) void act(t.id, () => backlogApi.assign(t.id, w), `Handed to ${workerLabel(w)}`); }}>
                <option value="">{t.handoff_id ? "Reassign…" : "Assign to…"}</option>
                {WORKERS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
              </select>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NewTask({ onDone }: { onDone: (t: BacklogTask) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [priority, setPriority] = useState<BacklogPriority>("P1");
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try { onDone((await backlogApi.add({ title: title.trim(), detail: detail.trim(), priority })).task); } catch (err) { toast((err as Error).message, "error"); } finally { setSaving(false); }
  };
  return (
    <form className="jg-u-card jg-backlog__new" onSubmit={(e) => void submit(e)} aria-label="New backlog task">
      <input className="jg-ui-input" placeholder="What needs doing?" aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required />
      <textarea className="jg-ui-input" placeholder="Details (optional)" aria-label="Details" value={detail} onChange={(e) => setDetail(e.target.value)} rows={3} maxLength={8000} />
      <div className="jg-backlog__actions">
        <select className="jg-ui-input" aria-label="Priority" value={priority} onChange={(e) => setPriority(e.target.value as BacklogPriority)}>{PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}</select>
        <button type="submit" className="jg-u-btn jg-u-btn--primary" disabled={saving || !title.trim()}>Add</button>
      </div>
    </form>
  );
}
