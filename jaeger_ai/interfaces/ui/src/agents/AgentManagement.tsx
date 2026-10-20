/** Presentation only: archive never stops work, removes context, or changes identity. */
import type { Agent } from "../api/types";
import { label } from "./agentsLogic";

export function AgentManagement({ agents, busy, onRename, onArchive, onResetName, onPin, onImportPins, onPrimary, onProfile, onHistory, onIcon }: {
  onIcon?: (agent: Agent, preset: string | null) => void;
  onPrimary?: (agent: Agent) => void; onProfile?: (agent: Agent) => void; onHistory?: (agent: Agent) => void;
  agents: Agent[]; busy?: boolean; onImportPins?: () => void; onRename: (agent: Agent) => void;
  onArchive: (agent: Agent, archived: boolean) => void; onPin: (agent: Agent, pinned: boolean) => void; onResetName: (agent: Agent) => void;
}) {
  const managed = agents.filter((a) => a.ui_actions?.rename || a.ui_actions?.hide).sort((a, b) => Number(Boolean(a.deleted)) - Number(Boolean(b.deleted)));
  return <section aria-label="Manage agents">
    <p>Archive hides navigation only. Conversations, context and background work remain. Restore returns the same agent.</p>
    <p>Archived pins are preserved; unpin an archived agent here to free a pin slot.</p>
    <p>Pins are shared by authorized clients of this local operator, not isolated per WebUI login/profile.</p>
    {onImportPins && <button type="button" disabled={busy} onClick={onImportPins}>Import this device’s pins into available shared slots</button>}
    {!managed.length && <p>This server does not advertise agent presentation management.</p>}
    {managed.map((agent, index) => <section key={agent.id}>
      {agent.deleted && !managed[index - 1]?.deleted && <h3>Deleted bots</h3>}
      <div className="jg-sheet__card">
      <div className="jg-sheet__row"><span className="jg-sheet__row-label"><strong>{label(agent)}</strong><small>{agent.id}{agent.primary ? " · Primary" : ""}{agent.deleted ? " · Deleted (recoverable)" : agent.archived ? " · Hidden" : ""}</small></span>
        <div className="jg-agent-management-actions">
          {onIcon && agent.ui_actions?.icon && <label>Sidebar icon<select aria-label={`Icon for ${label(agent)}`} value={agent.icon_preset ?? ""} disabled={busy} onChange={(e) => onIcon(agent, e.target.value || null)}><option value="">Original avatar</option>{agent.icon_choices?.map((id) => <option key={id} value={id}>{id.replaceAll('-', ' ')}</option>)}</select></label>}
          {onProfile && <button type="button" onClick={() => onProfile(agent)}>Profile</button>}
          {onHistory && <button type="button" onClick={() => onHistory(agent)}>History</button>}
          {onPrimary && !agent.primary && agent.ui_actions?.primary && <button type="button" disabled={busy} onClick={() => onPrimary(agent)}>Make primary</button>}
          {agent.ui_actions?.rename && <button type="button" disabled={busy} onClick={() => onRename(agent)}>Rename</button>}
          {agent.presentation?.display_name && <button type="button" disabled={busy} onClick={() => onResetName(agent)}>Reset display name</button>}
          {agent.ui_actions?.pin && <button type="button" disabled={busy} onClick={() => onPin(agent, !agent.pinned)}>{agent.pinned ? "Unpin" : "Pin"}</button>}
          {agent.ui_actions?.hide && <button type="button" disabled={busy} onClick={() => onArchive(agent, !(agent.archived || agent.deleted))}>{agent.archived || agent.deleted ? "Restore" : "Hide from sidebar"}</button>}
        </div>
      </div>
    </div></section>)}
  </section>;
}
