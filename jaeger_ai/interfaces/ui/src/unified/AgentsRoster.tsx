/**
 * Agents (unified UI): roster + inspector. The list shows every agent with its robot icon,
 * status, pin and unread state; the inspector shows the selected agent's status, model, skills,
 * recent conversations, and its configuration, memory and knowledge editors. Create, rename,
 * pin, archive and the robot-icon picker go through the gateway's agent APIs (only where the
 * agent's ui_actions allow it); the robot head choice is per device.
 */
import { useEffect, useMemo, useState } from "react";
import type { JaegerSource, ModelChoiceSnapshot } from "../api/source";
import type { Agent, SessionRow } from "../api/types";
import type { AgentsState } from "../agents/agentsStore";
import { label, visible, ROLE_TEXT } from "../agents/agentsLogic";
import { loadPins, pin, savePins, unpin } from "../agents/pins";
import { RobotIcon, ROBOT_VARIANTS, robotVariant, setRobotVariant, useRobotIcons } from "../agents/RobotIcon";
import { fuzzyMatch } from "../agents/JumpTo";
import { SpecialistConfiguration } from "../agents/SpecialistConfiguration";
import { AgentMemory } from "../agents/AgentMemory";
import { AgentKnowledge } from "../agents/AgentKnowledge";
import { AgentFace } from "./AgentFace";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast, PageHead } from "./ui";
import { createSpecialist } from "./agentCreate";
import { CharacterRoster } from "./CharacterRoster";
import { AvatarStudio } from "../avatar/AvatarStudio";

const statusTone = (s?: string) => (s === "working" ? "ok" : s === "waiting_approval" ? "warn" : s === "error" || s === "blocked" ? "bad" : undefined);
const when = (t?: number | null) => (t ? new Date((t > 1e12 ? t : t * 1000)).toLocaleString() : "–");
type Show = "active" | "archived";

export function AgentsRoster({ source, store, refresh, onNavigate, avatarFor }: { source: JaegerSource; store: AgentsState; refresh: () => Promise<void> | void; onNavigate: (to: string) => void; avatarFor?: string | null }) {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<Show>("active");
  const [robots, setRobots] = useRobotIcons();
  const [selected, setSelected] = useState<string>();
  const [creating, setCreating] = useState(false);
  const shared = Boolean(source.agentActions?.savePins) && store.agents.some((a) => a.ui_actions?.pin);
  const pins = shared ? store.agents.filter((a) => a.pinned).sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0)).map((a) => a.id) : loadPins();
  const pool = useMemo(() => show === "archived" ? store.agents.filter((a) => !a.deleted && (a.archived || a.presentation?.archived)) : store.agents.filter(visible), [store.agents, show]);
  const agents = useMemo(() => pool
    .filter((a) => !query || fuzzyMatch(query, label(a)) > 0)
    .sort((a, b) => Number(Boolean(b.primary)) - Number(Boolean(a.primary)) || Number(pins.includes(b.id)) - Number(pins.includes(a.id)) || label(a).localeCompare(label(b))),
  [pool, query, pins]);
  useEffect(() => { if (!selected && agents[0]) setSelected(agents[0].id); }, [agents, selected]);
  const agent = store.agents.find((a) => a.id === selected);
  const status = (id: string) => store.summaries.find((s) => s.id === id)?.status;

  const togglePin = async (a: Agent) => {
    const next = pins.includes(a.id) ? unpin(pins, a.id) : pin(pins, a.id);
    try {
      if (shared) await source.agentActions!.savePins!(next, pins); else savePins(next);
      await refresh();
      toast(pins.includes(a.id) ? `Unpinned ${label(a)}` : `Pinned ${label(a)}`);
    } catch (e) { toast(`Couldn't save pins: ${(e as Error).message}`, "error"); }
  };

  if (avatarFor) { for (let i = 0; i < 3 && /%[0-9A-Fa-f]{2}/.test(avatarFor); i++) { try { avatarFor = decodeURIComponent(avatarFor); } catch { break; } } }
  const avatarAgent = avatarFor ? store.agents.find((a) => a.id === avatarFor) : undefined;
  if (avatarFor) {
    return avatarAgent
      ? <AvatarStudio key={avatarAgent.id} agent={avatarAgent} presence={status(avatarAgent.id)} onBack={() => onNavigate("/agents")} />
      : <div className="jg-u-page"><Empty title={store.loading ? "Loading agent…" : "Agent not found"}>{avatarFor}</Empty></div>;
  }
  return (
    <div className="jg-u-page">
      <PageHead title="Agents" subtitle={<>{store.agents.filter(visible).length} agents · select one to inspect it.</>} actions={<>
          <input className="jg-u-search" type="search" placeholder="Filter agents" aria-label="Filter agents" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Segmented label="Show" value={show} onChange={(v) => { setShow(v); setSelected(undefined); }} options={[{ value: "active", label: "Active" }, { value: "archived", label: "Archived" }]} />
          <label className="jg-u-check"><input type="checkbox" checked={robots} onChange={(e) => setRobots(e.target.checked)} /> Robot icons</label>
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/agents/activity")}>Activity</button>
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/agents/characters")}>From character</button>
          <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => setCreating(true)}>New agent</button>
        </>} />
      <CharacterRoster onNavigate={onNavigate} />
      {store.error && <p className="jg-u-error" role="alert">Gateway unreachable: {store.error}</p>}
      <div className="jg-ui-split">
        <ul className="jg-u-roster" aria-label="Agents">
          {agents.map((a) => {
            const pinned = pins.includes(a.id);
            const unread = store.summaries.find((s) => s.id === a.id)?.unseen;
            return (
              <li key={a.id} className="jg-u-agent" data-pinned={pinned || undefined} aria-current={a.id === selected || undefined}>
                <button type="button" className="jg-u-agent__open" onClick={() => setSelected(a.id)} onDoubleClick={() => onNavigate(`/chat?agent=${encodeURIComponent(a.id)}`)}>
                  <AgentFace agent={a} size={40} status={status(a.id)} />
                  <span className="jg-u-agent__text">
                    <strong>{label(a)}{a.primary && <span className="jg-u-tag">Primary</span>}{unread && <span className="jg-u-dot" aria-label="Unread" />}</strong>
                    <span>{(typeof a.metadata?.specialty === "string" && a.metadata.specialty) || (a.role ? ROLE_TEXT[a.role] ?? a.role : "Specialist")}</span>
                    <span className="jg-u-agent__status" data-status={status(a.id) ?? "idle"}>{status(a.id) ?? "idle"}</span>
                  </span>
                </button>
                {!a.primary && (shared ? a.ui_actions?.pin : true) && (
                  <button type="button" className="jg-u-icon-btn" aria-pressed={pinned} aria-label={pinned ? `Unpin ${label(a)}` : `Pin ${label(a)}`} onClick={() => void togglePin(a)}>{pinned ? "Unpin" : "Pin"}</button>
                )}
              </li>
            );
          })}
          {!agents.length && <li>{store.loading ? <SkeletonRows /> : <Empty title={query ? `No agents match "${query}"` : show === "archived" ? "No archived agents" : "No agents yet"} />}</li>}
        </ul>
        {agent ? <AgentInspector key={agent.id} source={source} agent={agent} status={status(agent.id)} refresh={refresh} onNavigate={onNavigate} pinned={pins.includes(agent.id)} onPin={() => void togglePin(agent)} />
          : <aside className="jg-ui-inspector"><Empty title="No agent selected">Pick an agent to see its model, skills and conversations.</Empty></aside>}
      </div>
      {creating && <CreateAgentSheet source={source} onClose={() => setCreating(false)} onCreated={async (a) => { setCreating(false); await refresh(); setShow("active"); setSelected(a.id); }} />}
    </div>
  );
}

function AgentInspector({ source, agent, status, refresh, onNavigate, pinned, onPin }: { source: JaegerSource; agent: Agent; status?: string; refresh: () => Promise<void> | void; onNavigate: (to: string) => void; pinned: boolean; onPin: () => void }) {
  const toast = useToast();
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [model, setModel] = useState<ModelChoiceSnapshot | null | undefined>();
  const [panel, setPanel] = useState<"config" | "memory" | "knowledge" | "rename">();
  const [name, setName] = useState(label(agent));
  const [busy, setBusy] = useState(false);
  const caps = agent.ui_actions ?? {};
  const actions = source.agentActions;
  useEffect(() => {
    let live = true;
    source.sessions({ agent_id: agent.id }).then((s) => { if (live) setSessions(s.slice(0, 6)); }, () => { if (live) setSessions([]); });
    if (source.agentHome && source.modelSettings) {
      source.agentHome(agent.id).then((h) => source.modelSettings!.read(h.session_id)).then((m) => { if (live) setModel(m); }, () => { if (live) setModel(null); });
    } else setModel(null);
    return () => { live = false; };
  }, [source, agent.id]);
  const archived = Boolean(agent.archived || agent.presentation?.archived);
  const patch = async (body: Parameters<NonNullable<typeof actions>["patchAgent"]>[1], done: string) => {
    if (!actions) return;
    setBusy(true);
    try { await actions.patchAgent(agent.id, body); await refresh(); toast(done); }
    catch (e) { toast(`${label(agent)}: ${(e as Error).message}`, "error"); }
    finally { setBusy(false); }
  };
  const variant = robotVariant(agent.id);
  return (
    <aside className="jg-ui-inspector" aria-label={`${label(agent)} details`}>
      <div className="jg-agent-hero">
        <AgentFace agent={agent} size={56} status={status} />
        <div>
          <strong>{label(agent)}</strong>
          <span>{(typeof agent.metadata?.specialty === "string" && agent.metadata.specialty) || (agent.role ? ROLE_TEXT[agent.role] ?? agent.role : "Specialist")}</span>
          <span className="jg-row jg-mt-1"><Badge tone={statusTone(status)}>{status ?? "idle"}</Badge>{agent.primary && <Badge>Primary</Badge>}{archived && <Badge tone="warn">Archived</Badge>}</span>
        </div>
      </div>
      <div className="jg-ui-toolbar">
        <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => onNavigate(`/chat?agent=${encodeURIComponent(agent.id)}`)}>Open chat</button>
        <button type="button" className="jg-u-btn" onClick={() => onNavigate(`/agents/${encodeURIComponent(agent.id)}/avatar`)}>Avatar</button>
        {!agent.primary && <button type="button" className="jg-u-btn" aria-pressed={pinned} onClick={onPin}>{pinned ? "Unpin" : "Pin"}</button>}
        {caps.rename && actions && <button type="button" className="jg-u-btn" onClick={() => setPanel("rename")}>Rename</button>}
        {caps.hide && actions && !agent.primary && <button type="button" className="jg-u-btn" disabled={busy} onClick={() => void patch({ archived: !archived }, archived ? "Restored" : "Archived")}>{archived ? "Restore" : "Archive"}</button>}
      </div>
      <section><h3>Overview</h3>
        <dl className="jg-ui-kv">
          <dt>Model</dt><dd>{model === undefined ? "…" : model?.model ? `${model.model}${model.provider ? ` · ${model.provider}` : ""}` : "Gateway default"}</dd>
          <dt>Kind</dt><dd>{agent.kind ?? "–"}</dd>
          <dt>Runner</dt><dd>{agent.runner ? String((agent.runner as { kind?: string }).kind ?? "custom") : "Jaeger"}</dd>
          <dt>ID</dt><dd><code>{agent.id}</code></dd>
        </dl>
      </section>
      <section><h3>Skills &amp; tools</h3>
        {agent.skills?.length ? <div className="jg-row jg-row--wrap jg-mt-2">{agent.skills.map((s) => <Badge key={s.id}>{s.name}</Badge>)}</div>
          : <p className="jg-u-note">No skills reported for this agent.{agent.delegation ? ` Tools: ${agent.delegation.tools}.` : ""}</p>}
      </section>
      <section><h3>Configure</h3>
        <div className="jg-ui-toolbar jg-mt-2">
          {source.specialistControls && <button type="button" className="jg-u-btn" onClick={() => setPanel("config")}>Instructions</button>}
          {source.agentMemory && <button type="button" className="jg-u-btn" onClick={() => setPanel("memory")}>Memory</button>}
          {source.agentKnowledge && <button type="button" className="jg-u-btn" onClick={() => setPanel("knowledge")}>Knowledge</button>}
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/settings/agents")}>All settings</button>
        </div>
      </section>
      <section><h3>Robot icon (this device)</h3>
        <div className="jg-robot-pick" role="radiogroup" aria-label="Robot icon">
          {ROBOT_VARIANTS.map((v) => (
            <button key={v} type="button" role="radio" aria-checked={v === variant} aria-label={v} onClick={() => setRobotVariant(agent.id, v)}>
              <RobotIcon id={agent.id} name={v} size={32} variant={v} />
            </button>))}
        </div>
      </section>
      <section><h3>Recent conversations</h3>
        {!sessions ? <SkeletonRows n={2} /> : sessions.length ? (
          <ul className="jg-u-list">{sessions.map((s) => (
            <li key={s.session_id}><button type="button" className="jg-u-row" onClick={() => onNavigate(`/chat?agent=${encodeURIComponent(agent.id)}`)}>
              <span className="jg-u-row__text"><strong>{s.title || "Conversation"}</strong><span>{when(s.created_at)}</span></span>
            </button></li>))}
          </ul>) : <p className="jg-u-note">No conversations yet.</p>}
      </section>
      {panel === "config" && source.specialistControls && <SpecialistConfiguration agentId={agent.id} controls={source.specialistControls} onClose={() => setPanel(undefined)} onSaved={() => { toast("Instructions saved"); void refresh(); }} />}
      {panel === "memory" && source.agentMemory && <AgentMemory agentId={agent.id} controls={source.agentMemory} onClose={() => setPanel(undefined)} />}
      {panel === "knowledge" && source.agentKnowledge && <AgentKnowledge agentId={agent.id} controls={source.agentKnowledge} onClose={() => setPanel(undefined)} onSaved={() => toast("Knowledge saved")} />}
      {panel === "rename" && (
        <Sheet title={`Rename ${label(agent)}`} onClose={() => setPanel(undefined)}>
          <form className="jg-stack" onSubmit={(e) => { e.preventDefault(); void patch({ display_name: name.trim() || null }, "Renamed").then(() => setPanel(undefined)); }}>
            <label className="jg-ui-field">Display name<input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
            <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={() => setPanel(undefined)}>Cancel</button><button className="jg-u-btn jg-u-btn--primary" disabled={busy || !name.trim()}>Save</button></div>
          </form>
        </Sheet>)}
    </aside>
  );
}

function CreateAgentSheet({ source, onClose, onCreated }: { source: JaegerSource; onClose: () => void; onCreated: (a: Agent) => void }) {
  const toast = useToast();
  const [f, setF] = useState({ displayName: "", specialty: "", summary: "", instructions: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const submit = async () => {
    setBusy(true); setErr(undefined);
    try {
      const { agent, configured } = await createSpecialist(source, f);
      toast(configured || !f.instructions.trim() ? `Created ${f.displayName}` : `Created ${f.displayName}; instructions couldn't be saved — open Instructions to add them.`, configured || !f.instructions.trim() ? undefined : "error");
      onCreated(agent);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Sheet title="New agent" onClose={onClose}>
      <form className="jg-stack" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <label className="jg-ui-field">Name<input required maxLength={80} value={f.displayName} onChange={set("displayName")} placeholder="Research assistant" /></label>
        <label className="jg-ui-field">Specialty<input maxLength={200} value={f.specialty} onChange={set("specialty")} placeholder="What it's good at" /></label>
        <label className="jg-ui-field">Summary<input maxLength={2000} value={f.summary} onChange={set("summary")} /></label>
        <label className="jg-ui-field">Instructions<textarea rows={6} maxLength={12000} value={f.instructions} onChange={set("instructions")} placeholder="How it should behave" /></label>
        {err && <p className="jg-u-error" role="alert">{err}</p>}
        <div className="jg-ui-actions"><button type="button" className="jg-u-btn" onClick={onClose}>Cancel</button><button className="jg-u-btn jg-u-btn--primary" disabled={busy || !f.displayName.trim()}>{busy ? "Creating…" : "Create agent"}</button></div>
      </form>
    </Sheet>
  );
}
