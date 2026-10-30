/**
 * Agents (unified UI): the real roster from the gateway — every agent with its robot icon,
 * status, unread state and pin. One pin system (agents/pins + the gateway's shared pins when
 * it has them), the same one the chat sidebar uses. Right-click or "…" for the agent menu.
 */
import { useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import type { AgentsState } from "../agents/agentsStore";
import { label, visible, ROLE_TEXT } from "../agents/agentsLogic";
import { loadPins, pin, savePins, unpin } from "../agents/pins";
import { useRobotIcons } from "../agents/RobotIcon";
import { fuzzyMatch } from "../agents/JumpTo";
import { AgentFace } from "./AgentFace";

export function AgentsRoster({ source, store, refresh, onNavigate }: { source: JaegerSource; store: AgentsState; refresh: () => Promise<void> | void; onNavigate: (to: string) => void }) {
  const [query, setQuery] = useState("");
  const [robots, setRobots] = useRobotIcons();
  const [notice, setNotice] = useState<string>();
  const shared = Boolean(source.agentActions?.savePins) && store.agents.some((a) => a.ui_actions?.pin);
  const pins = shared ? store.agents.filter((a) => a.pinned).sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0)).map((a) => a.id) : loadPins();
  const agents = useMemo(() => store.agents.filter(visible)
    .filter((a) => !query || fuzzyMatch(query, label(a)) > 0)
    .sort((a, b) => Number(Boolean(b.primary)) - Number(Boolean(a.primary)) || Number(pins.includes(b.id)) - Number(pins.includes(a.id)) || label(a).localeCompare(label(b))),
  [store.agents, query, pins]);
  const togglePin = async (agent: Agent) => {
    const next = pins.includes(agent.id) ? unpin(pins, agent.id) : pin(pins, agent.id);
    try {
      if (shared) { await source.agentActions!.savePins!(next, pins); await refresh(); } else { savePins(next); await refresh(); }
    } catch (e) { setNotice(`Couldn't save pins: ${String((e as Error).message ?? e)}`); }
  };
  const status = (id: string) => store.summaries.find((s) => s.id === id)?.status;
  return (
    <div className="jg-u-page">
      <header className="jg-u-page__head">
        <h1>Agents</h1>
        <div className="jg-u-page__tools">
          <input className="jg-u-search" placeholder="Filter agents" aria-label="Filter agents" value={query} onChange={(e) => setQuery(e.target.value)} />
          <label className="jg-u-check"><input type="checkbox" checked={robots} onChange={(e) => setRobots(e.target.checked)} /> Robot icons</label>
          <button type="button" className="jg-u-btn" onClick={() => onNavigate("/settings/agents")}>Manage</button>
          <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => onNavigate("/characters")}>New from character</button>
        </div>
      </header>
      {notice && <p className="jg-u-error" role="alert">{notice}</p>}
      {store.error && <p className="jg-u-error" role="alert">Gateway unreachable: {store.error}</p>}
      <ul className="jg-u-roster">
        {agents.map((a) => {
          const pinned = pins.includes(a.id);
          const unread = store.summaries.find((s) => s.id === a.id)?.unseen;
          return (
            <li key={a.id} className="jg-u-agent" data-pinned={pinned || undefined}>
              <button type="button" className="jg-u-agent__open" onClick={() => onNavigate(`/chat?agent=${encodeURIComponent(a.id)}`)}>
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
        {!agents.length && <li className="jg-u-empty">{store.loading ? "Loading agents…" : query ? `No agents match "${query}"` : "No agents yet."}</li>}
      </ul>
    </div>
  );
}
