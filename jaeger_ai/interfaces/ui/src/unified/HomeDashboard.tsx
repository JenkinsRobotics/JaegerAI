/**
 * Home (unified UI): what needs you now. Active agents, pending approvals (decide inline),
 * recent chats and open tasks, all from the live gateway. Widgets you arrange live on /workspace.
 */
import { useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { SessionRow, Task } from "../api/types";
import type { AgentsState } from "../agents/agentsStore";
import { label, visible } from "../agents/agentsLogic";
import { AgentFace } from "./AgentFace";
import { ApprovalList, useApprovalSessions } from "./ApprovalTray";

const OPEN_STATES = new Set(["queued", "running", "needs_owner", "paused", "blocked"]);
const ago = (t?: number | null) => {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - (t > 1e12 ? t / 1000 : t));
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
};

export function HomeDashboard({ source, store, onNavigate }: { source: JaegerSource; store: AgentsState; onNavigate: (to: string) => void }) {
  const approvals = useApprovalSessions(source);
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    const read = () => {
      source.sessions().then((s) => { if (live) setSessions(s.slice(0, 8)); }, (e: unknown) => { if (live) setError(String((e as Error).message ?? e)); });
      source.tasks().then((t) => { if (live) setTasks(t.filter((x) => OPEN_STATES.has(String(x.state))).slice(0, 8)); }, () => { if (live) setTasks([]); });
    };
    read();
    const t = setInterval(read, 15000);
    return () => { live = false; clearInterval(t); };
  }, [source]);
  const agents = useMemo(() => store.agents.filter(visible), [store.agents]);
  const status = (id: string) => store.summaries.find((s) => s.id === id)?.status;
  const active = agents.filter((a) => ["working", "waiting_approval", "blocked"].includes(String(status(a.id))));
  const name = (id?: string | null) => { const a = store.agents.find((x) => x.id === id); return a ? label(a) : undefined; };
  const chat = (agentId?: string | null) => onNavigate(agentId ? `/chat?agent=${encodeURIComponent(agentId)}` : "/chat");
  const pendingCount = approvals.reduce((n, a) => n + a.count, 0);
  return (
    <div className="jg-u-page jg-u-home">
      <header className="jg-u-page__head">
        <h1>Home</h1>
        <div className="jg-u-page__tools">
          <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => chat()}>New chat</button>
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/characters")}>New agent from character</button>
        </div>
      </header>
      {store.error && <p className="jg-u-error" role="alert">Gateway unreachable: {store.error}</p>}
      <div className="jg-u-grid">
        <section className="jg-u-card" aria-label="Agents">
          <h2>Agents <span className="jg-u-count">{active.length ? `${active.length} active` : `${agents.length} ready`}</span></h2>
          <ul className="jg-u-list">
            {(active.length ? active : agents.slice(0, 6)).map((a) => (
              <li key={a.id}><button type="button" className="jg-u-row" onClick={() => chat(a.id)}>
                <AgentFace agent={a} size={26} status={status(a.id)} />
                <span className="jg-u-row__text"><strong>{label(a)}</strong><span>{status(a.id) ?? "idle"}</span></span>
              </button></li>
            ))}
            {!agents.length && <li className="jg-u-empty">{store.loading ? "Loading agents…" : "No agents yet."}</li>}
          </ul>
          <button type="button" className="jg-u-link" onClick={() => onNavigate("/agents")}>All agents</button>
        </section>
        <section className="jg-u-card jg-u-card--wide" aria-label="Pending approvals">
          <h2>Approvals <span className="jg-u-count" data-alert={pendingCount > 0 || undefined}>{pendingCount} waiting</span></h2>
          {source.pendingApprovals ? <ApprovalList source={source} sessions={approvals} onOpenChat={chat} /> : <p className="jg-u-empty">This gateway does not expose approvals.</p>}
        </section>
        <section className="jg-u-card" aria-label="Recent chats">
          <h2>Recent chats</h2>
          {error && <p className="jg-u-error">{error}</p>}
          <ul className="jg-u-list">
            {(sessions ?? []).map((s) => (
              <li key={s.session_id}><button type="button" className="jg-u-row" onClick={() => chat(s.agent_id)}>
                <span className="jg-u-row__text"><strong>{s.title || name(s.agent_id) || "Conversation"}</strong><span>{[name(s.agent_id), ago(s.created_at)].filter(Boolean).join(" · ")}</span></span>
              </button></li>
            ))}
            {sessions?.length === 0 && <li className="jg-u-empty">No chats yet.</li>}
            {!sessions && !error && <li className="jg-u-empty">Loading…</li>}
          </ul>
        </section>
        <section className="jg-u-card" aria-label="Open tasks">
          <h2>Tasks</h2>
          <ul className="jg-u-list">
            {(tasks ?? []).map((t) => (
              <li key={t.task_id}><button type="button" className="jg-u-row" onClick={() => onNavigate("/tasks")}>
                <span className="jg-u-row__text"><strong>{t.goal || t.task_id}</strong><span>{[t.state, name(t.agent_id ?? t.owning_agent)].filter(Boolean).join(" · ")}</span></span>
              </button></li>
            ))}
            {tasks?.length === 0 && <li className="jg-u-empty">No open tasks.</li>}
            {!tasks && <li className="jg-u-empty">Loading…</li>}
          </ul>
          <button type="button" className="jg-u-link" onClick={() => onNavigate("/tasks")}>All tasks</button>
        </section>
      </div>
    </div>
  );
}
