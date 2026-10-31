/**
 * Home (unified UI): Grafana-style live panels + an Apple Control Center strip. Live data only:
 * host metrics and gateway latency from /v1/system/metrics (psutil + ioreg, sampled server-side
 * every 10s), service status from /v1/system/status (gateway + read-only Tailscale), agents,
 * tasks, approvals and sessions from the gateway. Panels can be rearranged (drag, or Edit →
 * arrows) and the order persists per device. Focus mode is the gateway notification preference.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource, NotificationPreferences } from "../api/source";
import type { SessionRow, Task } from "../api/types";
import type { AgentsState } from "../agents/agentsStore";
import { label, visible } from "../agents/agentsLogic";
import { AgentFace } from "./AgentFace";
import { ApprovalList, useApprovalSessions } from "./ApprovalTray";
import { Badge, Empty, SkeletonRows, Sparkline, useToast, type Tone, PageHead } from "./ui";
import { getJson, type Metrics, type SystemStatus } from "./webui";
import { loadPanels, movePanel, savePanels, type HomePanel } from "./homeLayout";
import { Cloud, Globe, Mic, MessageSquare, Moon, Sparkles, Zap, ChevronLeft, ChevronRight } from "../components/Icons";

const OPEN_STATES = new Set(["queued", "running", "needs_owner", "paused", "blocked", "waiting_approval"]);
const ACTIVE = new Set(["working", "waiting_approval", "blocked"]);
const ago = (t?: number | null) => {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - (t > 1e12 ? t / 1000 : t));
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
};
const gb = (b?: number) => (b == null ? "–" : `${(b / 2 ** 30).toFixed(1)} GB`);
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v)}%`);
const toneFor = (v: number | null | undefined): Tone => (v == null ? undefined : v >= 90 ? "bad" : v >= 75 ? "warn" : "ok");

function useMetrics() {
  const [m, setM] = useState<Metrics>();
  const [err, setErr] = useState<string>();
  useEffect(() => {
    let live = true;
    const read = () => getJson<Metrics>("/v1/system/metrics").then((x) => { if (live) { setM(x); setErr(undefined); } }, (e: Error) => { if (live) setErr(e.message); });
    read();
    const t = setInterval(read, 10000);
    return () => { live = false; clearInterval(t); };
  }, []);
  return { m, err };
}

function useStatus() {
  const [s, setS] = useState<SystemStatus>();
  useEffect(() => {
    let live = true;
    const read = () => getJson<SystemStatus>("/v1/system/status").then((x) => { if (live) setS(x); }, () => { if (live) setS(undefined); });
    read();
    const t = setInterval(read, 30000);
    return () => { live = false; clearInterval(t); };
  }, []);
  return s;
}

/** Client-side series for gateway counts (agents active, open tasks) since this page opened. */
function useSeries(value: number | null, keep = 120) {
  const [vals, setVals] = useState<(number | null)[]>([]);
  const last = useRef(value);
  last.current = value;
  useEffect(() => {
    const push = () => setVals((v) => [...v.slice(-(keep - 1)), last.current]);
    push();
    const t = setInterval(push, 15000);
    return () => clearInterval(t);
  }, [keep]);
  return vals;
}

function Tile({ icon, title, value, tone, on, onClick, disabled, hint }: { icon: React.ReactNode; title: string; value: string; tone?: Tone; on?: boolean; onClick?: () => void; disabled?: boolean; hint?: string }) {
  const body = (<><span className="jg-cc__icon" data-tone={tone}>{icon}</span><span className="jg-cc__text"><strong>{title}</strong><span>{value}</span></span></>);
  return onClick
    ? <button type="button" className="jg-cc__tile" aria-pressed={on} onClick={onClick} disabled={disabled} title={hint}>{body}</button>
    : <div className="jg-cc__tile" role="status" title={hint}>{body}</div>;
}

export function HomeDashboard({ source, store, onNavigate }: { source: JaegerSource; store: AgentsState; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const approvals = useApprovalSessions(source);
  const { m, err: metricsErr } = useMetrics();
  const status = useStatus();
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [sessionsErr, setSessionsErr] = useState<string>();
  const [prefs, setPrefs] = useState<NotificationPreferences>();
  const [order, setOrder] = useState<HomePanel[]>(() => loadPanels());
  const [editing, setEditing] = useState(false);
  const [drag, setDrag] = useState<HomePanel>();
  useEffect(() => savePanels(order), [order]);

  useEffect(() => {
    let live = true;
    const read = () => {
      source.sessions().then((s) => { if (live) { setSessions(s.slice(0, 8)); setSessionsErr(undefined); } }, (e: unknown) => { if (live) setSessionsErr(String((e as Error).message ?? e)); });
      source.tasks().then((t) => { if (live) setTasks(t); }, () => { if (live) setTasks([]); });
    };
    read();
    const t = setInterval(read, 15000);
    source.notifications?.read().then((n) => { if (live) setPrefs(n.preferences); }, () => {});
    return () => { live = false; clearInterval(t); };
  }, [source]);

  const agents = useMemo(() => store.agents.filter(visible), [store.agents]);
  const statusOf = useCallback((id: string) => store.summaries.find((s) => s.id === id)?.status, [store.summaries]);
  const active = agents.filter((a) => ACTIVE.has(String(statusOf(a.id))));
  const openTasks = (tasks ?? []).filter((x) => OPEN_STATES.has(String(x.state)));
  const needsYou = openTasks.filter((x) => ["needs_owner", "paused", "blocked", "waiting_approval"].includes(String(x.state)));
  const pendingCount = approvals.reduce((n, a) => n + a.count, 0);
  const agentSeries = useSeries(store.loading ? null : active.length);
  const taskSeries = useSeries(tasks ? openTasks.length : null);
  const name = (id?: string | null) => { const a = store.agents.find((x) => x.id === id); return a ? label(a) : undefined; };
  const chat = (agentId?: string | null) => onNavigate(agentId ? `/chat?agent=${encodeURIComponent(agentId)}` : "/chat");

  const hist = m?.history ?? [];
  const series = (k: "cpu" | "mem" | "disk" | "gpu") => hist.map((s) => s[k]);
  const lat = hist.map((s) => s.gateway.latency_ms);
  const gw = status?.gateway ?? m?.now.gateway;
  const ts = status?.tailscale;
  const focusOn = prefs ? !prefs.enabled : false;

  const toggleFocus = async () => {
    if (!source.notifications || !prefs) return;
    try {
      const r = await source.notifications.save({ expected_revision: prefs.revision, enabled: !prefs.enabled, muted_agent_ids: prefs.muted_agent_ids });
      setPrefs(r.preferences);
      toast(r.preferences.enabled ? "Focus off: notifications on" : "Focus on: notifications paused");
    } catch (e) { toast(`Couldn't change Focus: ${(e as Error).message}`, "error"); }
  };

  const metricPanel = (title: string, k: "cpu" | "mem" | "disk" | "gpu", detail: string) => (
    <>
      <h2>{title} <Badge tone={toneFor(m?.now[k])}>{pct(m?.now[k])}</Badge></h2>
      {!m && !metricsErr ? <SkeletonRows n={2} /> : m?.now[k] == null ? <Empty title="Not available">This Mac didn't report {title.toLowerCase()}.</Empty> : <Sparkline values={series(k)} max={100} label={title} />}
      <p className="jg-home__foot">{detail}</p>
    </>
  );

  const panels: Record<HomePanel, { title: string; wide?: boolean; body: React.ReactNode }> = {
    gateway: { title: "Gateway latency", wide: true, body: (
      <>
        <h2>Gateway latency <Badge tone={gw ? (gw.ok ? "ok" : "bad") : undefined}>{gw ? (gw.ok ? `${gw.latency_ms} ms` : "down") : "…"}</Badge></h2>
        {!m && !metricsErr ? <SkeletonRows n={2} /> : <Sparkline values={lat} label="Gateway latency (ms)" color="var(--jg-ok)" />}
        <p className="jg-home__foot">GET /health on 127.0.0.1:33418, every {m?.interval ?? 10}s · last hour</p>
      </>) },
    cpu: { title: "CPU", body: metricPanel("CPU", "cpu", `${m?.now.cores ?? "–"} cores · last hour`) },
    mem: { title: "Memory", body: metricPanel("Memory", "mem", `${gb(m?.now.mem_used)} of ${gb(m?.now.mem_total)}`) },
    gpu: { title: "GPU", body: metricPanel("GPU", "gpu", "Apple GPU device utilisation") },
    disk: { title: "Disk", body: metricPanel("Disk", "disk", `${gb(m?.now.disk_used)} of ${gb(m?.now.disk_total)} on the data volume`) },
    agents: { title: "Agent activity", body: (
      <>
        <h2>Agent activity <Badge tone={active.length ? "ok" : undefined}>{active.length} active</Badge></h2>
        <Sparkline values={agentSeries} label="Active agents" />
        <ul className="jg-u-list">
          {(active.length ? active : agents.slice(0, 4)).map((a) => (
            <li key={a.id}><button type="button" className="jg-u-row" onClick={() => chat(a.id)}>
              <AgentFace agent={a} size={24} status={statusOf(a.id)} />
              <span className="jg-u-row__text"><strong>{label(a)}</strong><span>{statusOf(a.id) ?? "idle"}</span></span>
            </button></li>))}
        </ul>
        {!agents.length && (store.loading ? <SkeletonRows /> : <Empty title="No agents yet" action={<button type="button" className="jg-u-btn" onClick={() => onNavigate("/agents/characters")}>Create one</button>} />)}
      </>) },
    tasks: { title: "Tasks", body: (
      <>
        <h2>Tasks <Badge tone={needsYou.length ? "warn" : undefined}>{openTasks.length} open · {needsYou.length} need you</Badge></h2>
        <Sparkline values={taskSeries} label="Open tasks" />
        <ul className="jg-u-list">
          {openTasks.slice(0, 4).map((t) => (
            <li key={t.task_id}><button type="button" className="jg-u-row" onClick={() => onNavigate(`/work/tasks?task=${encodeURIComponent(t.task_id)}`)}>
              <span className="jg-u-row__text"><strong>{t.goal || t.task_id}</strong><span>{[t.state, name(t.agent_id ?? t.owning_agent)].filter(Boolean).join(" · ")}</span></span>
            </button></li>))}
        </ul>
        {!tasks ? <SkeletonRows /> : !openTasks.length && <Empty title="No open tasks" />}
      </>) },
    approvals: { title: "Approvals", wide: true, body: (
      <>
        <h2>Approvals <Badge tone={pendingCount ? "warn" : "ok"}>{pendingCount} waiting</Badge></h2>
        {source.pendingApprovals ? <ApprovalList source={source} sessions={approvals} onOpenChat={chat} /> : <Empty title="Approvals unavailable">This gateway does not expose approvals.</Empty>}
      </>) },
    recent: { title: "Recent chats", body: (
      <>
        <h2>Recent chats</h2>
        {sessionsErr && <p className="jg-u-error">{sessionsErr}</p>}
        {!sessions && !sessionsErr && <SkeletonRows />}
        <ul className="jg-u-list">
          {(sessions ?? []).map((s) => (
            <li key={s.session_id}><button type="button" className="jg-u-row" onClick={() => chat(s.agent_id)}>
              <span className="jg-u-row__text"><strong>{s.title || name(s.agent_id) || "Conversation"}</strong><span>{[name(s.agent_id), ago(s.created_at)].filter(Boolean).join(" · ")}</span></span>
            </button></li>))}
        </ul>
        {sessions?.length === 0 && <Empty title="No chats yet" action={<button type="button" className="jg-u-btn" onClick={() => chat()}>Start one</button>} />}
      </>) },
  };

  return (
    <div className="jg-u-page jg-u-home">
      <PageHead title="Home" subtitle="Live status of this Mac, the gateway and your agents." actions={<>
          <button type="button" className="jg-u-btn" aria-pressed={editing} onClick={() => setEditing((v) => !v)}>{editing ? "Done" : "Edit layout"}</button>
          <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => chat()}>New chat</button>
        </>} />
      {store.error && <p className="jg-u-error" role="alert">Gateway unreachable: {store.error}</p>}
      {metricsErr && <p className="jg-u-error" role="alert">Metrics unavailable: {metricsErr}</p>}

      <section className="jg-cc" aria-label="Control Center">
        <Tile icon={<Zap size={18} />} title="Gateway" value={gw ? (gw.ok ? `Healthy · ${gw.latency_ms} ms` : "Unreachable") : "Checking…"} tone={gw ? (gw.ok ? "ok" : "bad") : undefined} hint="Read-only: GET /health" />
        <Tile icon={<Globe size={18} />} title="Tailscale" value={!ts ? "Checking…" : !ts.available ? "Not available" : `${ts.online ? "Online" : ts.state ?? "Offline"} · ${ts.peers_online ?? 0}/${ts.peers ?? 0} peers`} tone={ts?.available ? (ts.online ? "ok" : "warn") : undefined} hint={ts?.host ? `This Mac: ${ts.host} (read-only)` : "Read-only"} />
        <Tile icon={<Moon size={18} />} title="Focus" value={!source.notifications ? "Unavailable" : !prefs ? "…" : focusOn ? "On · notifications paused" : "Off"} on={focusOn} onClick={source.notifications && prefs ? () => void toggleFocus() : undefined} />
        <Tile icon={<Mic size={18} />} title="Voice" value="Voice settings" onClick={() => onNavigate("/settings/voice")} />
        <Tile icon={<Sparkles size={18} />} title="Approvals" value={`${pendingCount + needsYou.length} need you`} tone={pendingCount + needsYou.length ? "warn" : "ok"} onClick={() => onNavigate("/work/tasks?filter=needs")} />
        <Tile icon={<MessageSquare size={18} />} title="New chat" value="Talk to Jaeger" onClick={() => chat()} />
        <Tile icon={<Cloud size={18} />} title="New agent" value="From a character" onClick={() => onNavigate("/agents/characters")} />
      </section>

      <div className="jg-home__grid" data-editing={editing || undefined}>
        {order.map((id, i) => (
          <section key={id} className={`jg-u-card jg-home__panel${panels[id].wide ? " jg-u-card--wide" : ""}`} aria-label={panels[id].title}
            draggable={editing} data-drag={drag === id || undefined}
            onDragStart={() => setDrag(id)} onDragEnd={() => setDrag(undefined)}
            onDragOver={(e) => { if (drag) e.preventDefault(); }}
            onDrop={(e) => { e.preventDefault(); if (drag && drag !== id) setOrder((o) => movePanel(o, drag, o.indexOf(id))); setDrag(undefined); }}>
            {editing && (
              <div className="jg-home__move">
                <button type="button" className="jg-u-icon-btn" aria-label={`Move ${panels[id].title} earlier`} disabled={i === 0} onClick={() => setOrder((o) => movePanel(o, id, i - 1))}><ChevronLeft size={14} /></button>
                <button type="button" className="jg-u-icon-btn" aria-label={`Move ${panels[id].title} later`} disabled={i === order.length - 1} onClick={() => setOrder((o) => movePanel(o, id, i + 1))}><ChevronRight size={14} /></button>
              </div>
            )}
            {panels[id].body}
          </section>
        ))}
      </div>
    </div>
  );
}
