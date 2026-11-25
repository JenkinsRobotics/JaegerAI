import { useCallback, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { loadPins, pin, savePins, unpin } from "../agents/pins";
import { useRobotIcons } from "../agents/RobotIcon";
import { AgentsActivityPage } from "../orchestration/AgentsActivityPage";
import { Badge, PageHead, Sheet, useToast } from "./ui";
import { createSpecialist } from "./agentCreate";
import { AgentFace } from "./AgentFace";
import { AgentInspector, CreateAgentSheet } from "./AgentsRoster";
import "./agentProfile.css";

type Props = { source: JaegerSource; agents: Agent[]; refresh: () => void | Promise<void>; onNavigate: (path: string) => void; initialAgent?: string; loading?: boolean; error?: string | null };
const isArchived = (a: Agent) => Boolean(a.archived || a.presentation?.archived);
export function AgentsHome({ source, agents, refresh, onNavigate, initialAgent, loading, error }: Props) {
  const [building, setBuilding] = useState(false);
  const [adding, setAdding] = useState(false);
  const [switchingPrimary, setSwitchingPrimary] = useState(false);
  const toast = useToast();
  const [profileId, setProfileId] = useState(initialAgent);
  const [query, setQuery] = useState("");
  const [robots, setRobots] = useRobotIcons();
  const [localPins, setLocalPins] = useState(loadPins);
  const closeProfile = useCallback(() => setProfileId(undefined), []);
  const roster = agents.filter(a => !a.deleted && !isArchived(a) && visible(a));
  const archived = agents.filter(a => !a.deleted && isArchived(a) && visible({ ...a, archived: false, hidden: false }));
  const profile = [...roster, ...archived].find(a => a.id === profileId);
  const sharedPins = Boolean(source.agentActions?.savePins) && agents.some(a => a.ui_actions?.pin);
  const pins = sharedPins ? agents.filter(a => a.pinned).sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0)).map(a => a.id) : localPins;
  const primary = roster.find(a => a.primary) ?? roster.find(a => a.id === "native:jaeger");
  const team = [...roster].sort((a, b) => Number(b.id === primary?.id) - Number(a.id === primary?.id) ||
    Number(pins.includes(b.id)) - Number(pins.includes(a.id)) || label(a).localeCompare(label(b)));
  const roleFor = (a: Agent) => typeof a.metadata?.specialty === "string" && a.metadata.specialty.trim() && a.metadata.specialty !== "lead" ? a.metadata.specialty : a.role === "lead" ? "General assistant" : "Team agent";
  const matches = (a: Agent) => `${label(a)} ${roleFor(a)}`.toLowerCase().includes(query.trim().toLowerCase());
  const togglePin = async (agent: Agent) => {
    const wasPinned = pins.includes(agent.id);
    const next = wasPinned ? unpin(pins, agent.id) : pin(pins, agent.id);
    try {
      if (sharedPins && source.agentActions?.savePins) {
        await source.agentActions.savePins(next, pins);
        await refresh();
      } else {
        savePins(next);
        setLocalPins(next);
      }
      toast(wasPinned ? "Agent unpinned" : "Agent pinned");
    } catch (e) { toast(`Couldn't save pins: ${(e as Error).message}`, "error"); }
  };
  const agentRows = (list: Agent[], name: string) => <ul className="jg-u-list" aria-label={name}>{list.map(a => <li key={a.id}>
    <button type="button" className="jg-u-row" onClick={() => setProfileId(a.id)}>
      <AgentFace agent={a} size={40} />
      <span className="jg-u-row__text"><strong>{label(a)}</strong><span>{roleFor(a)}</span></span>
      {a.id === primary?.id && <Badge>Primary agent</Badge>}
      {isArchived(a) && <Badge>Archived</Badge>}
    </button>
  </li>)}</ul>;
  const filtered = team.filter(matches);
  const changePrimary = async (agent: Agent) => {
    const actions = source.agentActions;
    if (!actions?.setPrimary || !primary || agent.id === primary.id || !agent.ui_actions?.primary || switchingPrimary) return;
    setSwitchingPrimary(true);
    try {
      await actions.setPrimary(agent.id, primary.id);
      await refresh();
      toast(`${label(agent)} is now the primary agent`);
    } catch (error) {
      toast(`Couldn't change the primary agent: ${error instanceof Error ? error.message : String(error)}`, "error");
      await Promise.resolve().then(refresh).catch(() => undefined);
    } finally { setSwitchingPrimary(false); }
  };
  return <div className="jg-u-page jg-stack jg-agents-home">
    <PageHead title="Agents" subtitle="Manage your team and see what your agents are working on." actions={<>
      <button className="jg-u-btn" onClick={() => setBuilding(true)}>Build a team</button>
      <button className="jg-u-btn jg-u-btn--primary" onClick={() => setAdding(true)}>Add agent</button>
    </>} />
    {error && <p className="jg-u-error" role="alert">Couldn't load agents. {error}</p>}
    <section className="jg-u-card" aria-label="Your team">
      <h2>Your team</h2>
      <p>Your primary agent is your usual starting point. Add agents for roles you want to use again.</p>
      {(team.length >= 6 || query) && <input className="jg-u-search" type="search" placeholder="Find an agent" aria-label="Find an agent" value={query} onChange={e => setQuery(e.target.value)} />}
      {filtered.length ? agentRows(filtered, "Active agents") : <p>{loading ? "Loading agents…" : query.trim() ? "No agents match that search." : "No saved agents to show."}</p>}
      <details><summary>When should I add an agent?</summary><p>Use a temporary helper for a clear, one-time assignment like checking a draft against its sources. Save an agent when it should own an ongoing responsibility with its own instructions and access. A schedule starts work on an existing agent or workflow.</p></details>
      <details><summary>Team options</summary>
        <label className="jg-u-check"><input type="checkbox" checked={robots} onChange={e => setRobots(e.target.checked)} /> Use robot icons</label>
        <h3>Archived agents{archived.length ? ` (${archived.length})` : ""}</h3>
        {archived.length ? agentRows(archived, "Archived agents") : <p className="jg-u-note">No archived agents.</p>}
      </details>
    </section>
    <AgentsActivityPage source={source} onNavigate={onNavigate} />
    {adding && <CreateAgentSheet simple source={source} onClose={() => setAdding(false)} onCreated={async agent => {
      setAdding(false);
      setProfileId(agent.id);
      await refresh();
    }} />}
    {building && <TeamBuilder primary={primary} source={source} refresh={refresh} onNavigate={onNavigate} onClose={() => setBuilding(false)} onSaved={setProfileId} />}
    {profile && <Sheet title={`${label(profile)} profile`} onClose={closeProfile} variant="agent-profile">
      <button type="button" className="jg-u-btn jg-agent-profile__close" onClick={closeProfile}>Close</button>
      <div className="jg-agent-profile__layout">
        <div className="jg-agent-profile__identity">
          <AgentFace agent={profile} size={96} />
          <strong>{label(profile)}</strong>
          <span>{roleFor(profile)}</span>
          {profile.id === primary?.id && <Badge>Primary agent</Badge>}
          {isArchived(profile) && <Badge>Archived</Badge>}
          {primary && profile.id !== primary.id && !isArchived(profile) && profile.ui_actions?.primary && source.agentActions?.setPrimary && <button type="button" className="jg-u-btn" disabled={switchingPrimary} onClick={() => void changePrimary(profile)}>{switchingPrimary ? "Saving…" : "Set as primary"}</button>}
        </div>
        <AgentInspector key={profile.id} profile agent={profile} source={source} refresh={refresh} onNavigate={path => { closeProfile(); onNavigate(path); }}
          pinned={pins.includes(profile.id)} onPin={profile.id !== primary?.id && !isArchived(profile) && (!sharedPins || profile.ui_actions?.pin) ? () => void togglePin(profile) : undefined} />
      </div>
    </Sheet>}
  </div>;
}

function TeamBuilder({ primary, source, refresh, onNavigate, onClose, onSaved }: Pick<Props, "source" | "refresh" | "onNavigate"> & { primary?: Agent; onClose: () => void; onSaved: (id: string) => void }) {
  const primaryName = primary ? label(primary) : "Your primary agent";
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState<"solo" | "helper" | "saved">("solo");
  const [role, setRole] = useState("");
  const [assignment, setAssignment] = useState("");
  const [result, setResult] = useState("");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const toast = useToast();
  const run = async () => {
    setBusy(true); setError("");
    try {
      if (mode === "saved") {
        const saved = await createSpecialist(source, { displayName: role, specialty: role, summary: assignment, instructions: `Goal: ${goal}\nResponsibility: ${assignment}\nExpected result: ${result}` });
        toast(saved.configured ? "Agent saved" : "Agent created, but its instructions did not save. Check its configuration.", saved.configured ? undefined : "error");
        await refresh();
        onClose();
        onSaved(saved.agent.id);
      } else {
        if (!primary) throw new Error("No primary agent is available for this trial.");
        const session = await source.createSession({ agent_id: primary.id, title: "Team trial" });
        await source.send(session.session_id, `Try a small task for this goal: ${goal}\nExpected result: ${result}\n${mode === "helper" ? `If delegation is available, delegate only this bounded assignment to a temporary ${role}: ${assignment}. If delegation is unavailable, report that clearly.` : "Work directly without delegating."}\nUse the current authorization limits. Keep this a read-only trial. Do not change files, publish, create saved agents, or set up schedules.`, crypto.randomUUID());
        onClose();
        onNavigate(`/chat?session=${encodeURIComponent(session.session_id)}`);
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return <Sheet title="Build a team" onClose={() => { if (!busy) onClose(); }}>
    <form className="jg-stack" onSubmit={e => { e.preventDefault(); if (!busy) { if (review) void run(); else setReview(true); } }}>
      {!review ? <>
        <label className="jg-ui-field">What do you want to get done?<textarea required maxLength={2000} value={goal} onChange={e => setGoal(e.target.value)} placeholder="Make a tutorial someone can follow" /></label>
        <label className="jg-ui-field">Who should do it?<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}>
          <option value="solo">{primaryName} alone</option><option value="helper">{primaryName} with a temporary helper</option><option value="saved">Save an agent for ongoing work</option>
        </select></label>
        {mode !== "solo" && <>
          <label className="jg-ui-field">Role<input required maxLength={80} value={role} onChange={e => setRole(e.target.value)} placeholder="Source checker" /></label>
          <label className="jg-ui-field">{mode === "saved" ? "Ongoing responsibility" : "Helper’s assignment"}<textarea required maxLength={1800} value={assignment} onChange={e => setAssignment(e.target.value)} /></label>
        </>}
        <label className="jg-ui-field">What should come back?<input required maxLength={1000} value={result} onChange={e => setResult(e.target.value)} placeholder="A list of claims and supporting sources" /></label>
      </> : <>
        <p><strong>{goal}</strong></p>
        <p>{mode === "solo" ? `${primaryName} works directly.` : mode === "helper" ? `${primaryName} coordinates. ${role} helps with: ${assignment}` : `${role} will own: ${assignment}`}</p>
        <p>Expected result: {result}</p>
        <p>{mode === "saved" ? "Saving creates a reusable profile. It does not start work or add a schedule. Review tool access in its settings before assigning work." : `This sends a read-only trial brief to a new chat with ${primaryName}. Existing permissions still apply.`}</p>
      </>}
      {error && <p role="alert" className="jg-u-error">{error}</p>}
      <div className="jg-ui-actions">{review && <button type="button" className="jg-u-btn" disabled={busy} onClick={() => { setReview(false); setError(""); }}>Back</button>}
        <button className="jg-u-btn jg-u-btn--primary" disabled={busy || !goal.trim() || !result.trim() || (mode !== "solo" && (!role.trim() || !assignment.trim()))}>{busy ? "Working…" : !review ? "Review plan" : mode === "saved" ? "Save agent" : "Try a small task"}</button></div>
    </form>
  </Sheet>;
}
