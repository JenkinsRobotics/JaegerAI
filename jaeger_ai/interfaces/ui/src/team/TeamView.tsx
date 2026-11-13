/* Team / Inner workings — Jaeger's specialists and how it works with them.
 * Collaboration mode decides the page: in One mind (default) it is "Inner
 * workings" — helper profiles Jaeger delegates to and the delegation history;
 * in Team / Auto it is the roster and rooms below.
 * Team — the agents that work together, and the rooms where they do it.
 * Roster cards (persona, skills, tools, live status) and a room view: post to a
 * room and every addressed member takes a real turn on its own Gateway session;
 * a member that writes @Name hands the room to that teammate. Everything here is
 * read from the live Gateway (/v1/team, the room's session stream) — no demo data.
 * Layout language matches the Process view (cards, status marks, tokens). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowRight, Bot, Brain, CheckCircle2, GitBranch, Loader2, MessagesSquare, Plus, Send, Sparkles, Users, Wrench, XCircle } from "lucide-react";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";
import type { RoomDetail, TeamAgent, TeamRoom, TeamSnapshot } from "../api/team";
import { AgentAvatar } from "./AgentAvatar";
import "./team.css";

type Working = Record<string, { agent: string; since: number }>;

function timeAgo(ts?: number) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`;
}

function StatusPill({ status }: { status: string }) {
  const working = status === "working" || status === "running" || status === "busy";
  return <span className={`jg-team-pill${working ? " is-working" : status === "failed" ? " is-failed" : ""}`}>
    {working ? <Loader2 size={12} className="jg-team-spin" /> : <i className="jg-team-dot" />}{working ? "Working" : status === "idle" || !status ? "Idle" : status.startsWith("waiting") ? "Waiting" : status.replace(/_/g, " ")}
  </span>;
}

function AgentCard({ agent, picking, picked, onPick }: { agent: TeamAgent; picking: boolean; picked: boolean; onPick: () => void }) {
  const status = agent.activity?.status ?? agent.status;
  return (
    <article className={`jg-team-card${picked ? " is-picked" : ""}${agent.role === "lead" ? " is-lead" : ""}`} aria-label={agent.display_name}>
      <header className="jg-team-card__head">
        <AgentAvatar name={agent.display_name} seed={agent.avatar.seed} url={agent.avatar.url} size={44} status={status} />
        <div className="jg-team-card__who">
          <h3 title={agent.display_name}>{agent.display_name}</h3>
          <span className="jg-team-card__role">{agent.role === "lead" ? "Lead" : agent.team ? `Team · ${agent.team}` : agent.role}</span>
        </div>
        <StatusPill status={status} />
      </header>
      <p className="jg-team-card__desc">{agent.description || agent.persona || "No role description yet."}</p>
      <footer className="jg-team-card__foot">
        <span title={agent.skills.join(", ") || "no skills"}><Sparkles size={13} /> {agent.skills.length} skill{agent.skills.length === 1 ? "" : "s"}</span>
        <span title={agent.tools.join(", ") || "inherits the lead's tools"}><Wrench size={13} /> {agent.tools.length ? `${agent.tools.length} tools` : "lead tools"}</span>
        {agent.pack && <span className="jg-team-card__pack">{agent.pack}</span>}
        {picking && agent.role !== "lead" && (
          <label className="jg-team-card__pick"><input type="checkbox" checked={picked} onChange={onPick} /> In room</label>
        )}
      </footer>
    </article>
  );
}

function RoomTranscript({ detail, agents, working }: { detail: RoomDetail | null; agents: Map<string, TeamAgent>; working: Working }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [detail?.messages.length, Object.keys(working).length]);
  if (!detail) return <p className="jg-team__empty">Pick a room or start one.</p>;
  return (
    <div className="jg-team-transcript" aria-live="polite">
      {detail.messages.length === 0 && <p className="jg-team__empty">No messages yet. Write to the room; use @Name to address one member.</p>}
      {detail.messages.map((m) => {
        const agent = m.sender_agent_id ? agents.get(m.sender_agent_id) : undefined;
        if (!m.sender_agent_id) return (
          <div key={m.id} className="jg-team-msg is-person"><div className="jg-team-msg__bubble">{m.content}</div></div>);
        return (
          <div key={m.id} className="jg-team-msg">
            <AgentAvatar name={agent?.display_name ?? m.sender_agent_id} seed={agent?.avatar.seed} url={agent?.avatar.url} size={30} />
            <div className="jg-team-msg__body">
              <div className="jg-team-msg__who">{agent?.display_name ?? m.sender_agent_id}<time>{timeAgo(m.created_at ?? m.timestamp)}</time></div>
              <div className="jg-team-msg__bubble">{m.content}</div>
            </div>
          </div>);
      })}
      {Object.entries(working).map(([turn, w]) => {
        const agent = agents.get(w.agent);
        return (
          <div key={turn} className="jg-team-msg is-working">
            <AgentAvatar name={agent?.display_name ?? w.agent} seed={agent?.avatar.seed} url={agent?.avatar.url} size={30} status="working" />
            <div className="jg-team-msg__body"><div className="jg-team-msg__who">{agent?.display_name ?? w.agent}</div>
              <div className="jg-team-msg__typing"><i /><i /><i /> working…</div></div>
          </div>);
      })}
      <div ref={end} />
    </div>
  );
}

export function TeamView({ source, onNavigate }: { source: JaegerSource; onNavigate?: (to: string) => void }) {
  const api = source.team;
  const [snap, setSnap] = useState<TeamSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RoomDetail | null>(null);
  const [working, setWorking] = useState<Working>({});
  const [notes, setNotes] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [showProbes, setShowProbes] = useState(false);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [title, setTitle] = useState("");

  const refresh = useCallback(async () => {
    if (!api) return;
    try { setSnap(await api.snapshot()); setError(null); } catch (e) { setError((e as Error).message); }
  }, [api]);
  useEffect(() => { void refresh(); const t = setInterval(refresh, 8000); return () => clearInterval(t); }, [refresh]);

  const agents = useMemo(() => new Map((snap?.agents ?? []).map((a) => [a.id, a])), [snap]);
  // Jaeger always runs as one lead with internal helpers; rooms stay off in the UI.
  const oneMind = true;
  const rooms = useMemo(() => (oneMind ? [] : (snap?.rooms ?? []).filter((r) => showProbes || !r.probe)), [snap, showProbes, oneMind]);
  useEffect(() => { if (oneMind) { if (roomId) setRoomId(null); return; } if (!roomId && rooms[0]) setRoomId(rooms[0].session_id); }, [rooms, roomId, oneMind]);

  const loadRoom = useCallback(async (id: string) => {
    if (!api) return;
    try { setDetail(await api.room(id)); } catch (e) { setError((e as Error).message); }
  }, [api]);

  // Live: the room's own session stream (room.turn / message.created / room.finished).
  useEffect(() => {
    if (!roomId || !api) return;
    setWorking({}); setNotes([]); void loadRoom(roomId);
    if (!source.processStream) return;
    const abort = new AbortController();
    const onEvent = (e: GatewayEvent) => {
      const p = (e.payload ?? {}) as Record<string, unknown>;
      if (e.event === "room.turn") {
        const turn = String(p.turn_id ?? "");
        setWorking((w) => { const n = { ...w }; if (p.status === "running") n[turn] = { agent: String(p.agent_id), since: Date.now() }; else delete n[turn]; return n; });
        if (p.status === "passed") setNotes((n) => [...n.slice(-4), `${String(p.agent_name)} passed`]);
        if (p.status === "failed") setNotes((n) => [...n.slice(-4), `${String(p.agent_name)} failed: ${String(p.error ?? "")}`]);
      } else if (e.event === "message.created" || e.event === "room.finished") {
        void loadRoom(roomId); if (e.event === "room.finished") { setWorking({}); void refresh(); }
      } else if (e.event === "policy.decision" && p.tool === "@mention" && p.decision === "deny") {
        setNotes((n) => [...n.slice(-4), String(p.reason ?? "hand-off refused")]);
      }
    };
    void (async () => {
      let cursor = 0;
      try { const h = await source.processHistory?.(roomId, undefined, 1); cursor = h?.events.at(-1)?.event_id ?? 0; } catch { /* history optional */ }
      while (!abort.signal.aborted) {
        try { await source.processStream!(roomId, cursor, (e) => { if (e.event_id) cursor = e.event_id; onEvent(e); }, abort.signal); } catch { /* reconnect */ }
        if (!abort.signal.aborted) await new Promise((r) => setTimeout(r, 1500));
      }
    })();
    return () => abort.abort();
  }, [roomId, api, source, loadRoom, refresh]);

  const send = async () => {
    if (!api || !roomId || !draft.trim()) return;
    setSending(true);
    try { await api.say(roomId, draft.trim()); setDraft(""); await loadRoom(roomId); } catch (e) { setError((e as Error).message); } finally { setSending(false); }
  };
  const create = async () => {
    if (!api || picked.length < 2) return;
    try {
      const room = await api.createRoom({ title: title.trim() || "Team room", members: picked });
      setPicking(false); setPicked([]); setTitle(""); await refresh(); setRoomId(room.session_id);
    } catch (e) { setError((e as Error).message); }
  };

  if (!api) return <section className="jg-team"><p className="jg-team__empty">The Team page needs the live Gateway.</p></section>;
  const members = (detail?.room.members ?? []).map((id) => agents.get(id)).filter((a): a is TeamAgent => !!a);
  const workingCount = (snap?.agents ?? []).filter((a) => (a.activity?.status ?? a.status) === "working").length;
  const currentRoom: TeamRoom | undefined = rooms.find((r) => r.session_id === roomId) ?? snap?.rooms.find((r) => r.session_id === roomId);

  const helpers = (snap?.agents ?? []).filter((a) => a.role !== "lead");
  const delegations = (snap?.handoffs ?? []).filter((h) => h.kind === "delegate");
  const shownAgents = oneMind ? helpers : (snap?.agents ?? []);
  const shownHandoffs = oneMind ? delegations : (snap?.handoffs ?? []);
  return (
    <section className="jg-team" aria-label={oneMind ? "Inner workings" : "Team"}>
      <header className="jg-team__bar">
        <div className="jg-team__title">{oneMind ? <><Brain size={16} /> Inner workings</> : <><Users size={16} /> Team</>}</div>
        <span className="jg-team__meta">{!snap ? "loading…" : oneMind
          ? `${helpers.length} helpers · ${workingCount} working · ${delegations.length} delegations`
          : `${snap.agents.length} agents · ${workingCount} working · ${snap.rooms.filter((r) => !r.probe).length} rooms`}</span>
        {error && <span className="jg-team__error" role="alert"><XCircle size={14} /> {error}</span>}
        {!oneMind && <button type="button" className="jg-team-btn is-primary" onClick={() => { setPicking((p) => !p); setPicked([]); }}>
          <Plus size={14} /> {picking ? "Cancel" : "New room"}</button>}
      </header>

      <div className="jg-team__body">
        <div className="jg-team__left">
          <div className="jg-team__section-head"><Bot size={14} /> {oneMind ? "Helper profiles" : "Roster"} {picking && <em>· pick at least two members</em>}</div>
          {oneMind && <p className="jg-team-inner__note">You talk to Jaeger. It calls these helpers itself; each works from a brief with Jaeger's tools narrowed to its profile and returns a result only to Jaeger.</p>}
          <div className="jg-team__roster" role="list">
            {shownAgents.map((a) => (
              <AgentCard key={a.id} agent={a} picking={picking} picked={picked.includes(a.id)}
                onPick={() => setPicked((p) => (p.includes(a.id) ? p.filter((x) => x !== a.id) : [...p, a.id]))} />))}
          </div>
          {picking && (
            <div className="jg-team-new">
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Room name" aria-label="Room name" />
              <button type="button" className="jg-team-btn is-primary" disabled={picked.length < 2} onClick={() => void create()}>Create room · {picked.length}</button>
            </div>)}
          <div className="jg-team__section-head"><GitBranch size={14} /> {oneMind ? "Delegation history" : "Recent hand-offs"}</div>
          <ol className="jg-team-handoffs">
            {shownHandoffs.length === 0 && <li className="jg-team__empty">{oneMind ? "Jaeger has not delegated to a helper yet." : "No hand-offs between these agents yet."}</li>}
            {shownHandoffs.slice(0, 8).map((h) => {
              const from = agents.get(h.from_agent_id), to = agents.get(h.to_agent_id);
              return (
                <li key={h.id}>
                  <AgentAvatar name={from?.display_name ?? h.from_agent_id} seed={from?.avatar.seed} url={from?.avatar.url} size={22} />
                  <ArrowRight size={13} className="jg-team-handoffs__arrow" />
                  <AgentAvatar name={to?.display_name ?? h.to_agent_id} seed={to?.avatar.seed} url={to?.avatar.url} size={22} />
                  <span className="jg-team-handoffs__kind">{h.kind === "room" ? "room" : h.kind === "delegate" ? "helper" : "call"}</span>
                  <span className="jg-team-handoffs__task" title={h.summary ? `${h.task}\n\n→ ${h.summary}` : h.task}>{h.task}</span>
                  {h.tokens && h.tokens.total > 0 && <span className="jg-team-handoffs__tokens">{h.tokens.total.toLocaleString()} tok</span>}
                  <span className={`jg-team-pill is-${h.status === "completed" ? "done" : h.status}`}>{h.status === "completed" ? <CheckCircle2 size={12} /> : null}{h.status.replace(/_/g, " ")}</span>
                  {h.session_id && onNavigate && <button type="button" className="jg-team-link" onClick={() => onNavigate(`/work/process?session=${encodeURIComponent(h.session_id!)}`)}>trace</button>}
                </li>);
            })}
          </ol>
        </div>

        {oneMind ? (
        <aside className="jg-team__room" aria-label="How Jaeger thinks">
          <div className="jg-team-room__head"><Brain size={15} /> One mind</div>
          <p className="jg-team__empty">Every message goes to Jaeger, which answers in one voice. When a focused review or a side task helps, it delegates to a helper; the helper's run shows as its own node under that step in the Process view.</p>
        </aside>
        ) : (
        <aside className="jg-team__room" aria-label="Room">
          <div className="jg-team-room__head">
            <MessagesSquare size={15} />
            <select value={roomId ?? ""} onChange={(e) => setRoomId(e.target.value || null)} aria-label="Room">
              {rooms.length === 0 && <option value="">No rooms yet</option>}
              {rooms.map((r) => <option key={r.session_id} value={r.session_id}>{r.title || r.session_id}</option>)}
            </select>
            <label className="jg-team__check"><input type="checkbox" checked={showProbes} onChange={(e) => setShowProbes(e.target.checked)} /> Show test sessions</label>
          </div>
          {currentRoom && (
            <div className="jg-team-room__members">
              <span className="jg-team-room__faces">{members.map((m) => <AgentAvatar key={m.id} name={m.display_name} seed={m.avatar.seed} url={m.avatar.url} size={26}
                status={Object.values(working).some((w) => w.agent === m.id) ? "working" : undefined} />)}</span>
              <span className="jg-team-room__names">{members.map((m) => m.display_name).join(" · ")}</span>
              {onNavigate && <button type="button" className="jg-team-link" onClick={() => onNavigate(`/work/process?session=${encodeURIComponent(currentRoom.session_id)}`)}><Activity size={13} /> Process view</button>}
            </div>)}
          <RoomTranscript detail={detail} agents={agents} working={working} />
          {notes.length > 0 && <ul className="jg-team-notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          <form className="jg-team-compose" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={2} disabled={!roomId || sending}
              placeholder={roomId ? "Write to the room… @Name addresses one member" : "Start a room first"} aria-label="Message the room"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
            <button type="submit" className="jg-team-btn is-primary" disabled={!roomId || sending || !draft.trim() || Object.keys(working).length > 0} aria-label="Send">
              {sending ? <Loader2 size={14} className="jg-team-spin" /> : <Send size={14} />}</button>
          </form>
        </aside>
        )}
      </div>
    </section>
  );
}

export default TeamView;
