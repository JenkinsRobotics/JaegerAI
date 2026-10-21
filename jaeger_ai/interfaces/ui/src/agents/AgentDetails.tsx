/* Details panel (Grok Bot: click the Bot's name at the top of the chat):
 * who the agent is, what it is doing now, its skills and tools, and a way into its history. Read-only. */
import type { Agent, AgentSummary } from "../api/types";
import { AgentAvatar } from "./AgentAvatar";
import { label, ROLE_TEXT, runnerLabel } from "./agentsLogic";

const STATUS_TEXT: Record<string, string> = {
  idle: "Idle", working: "Working", waiting_approval: "Needs your approval", blocked: "Blocked", error: "Error",
};

interface Props {
  agent: Agent;
  summary?: AgentSummary;
  /** Opens the agent's older chats (read-only); the home chat is the only live one. */
  onCopyConversationLink?:()=>void;
  onSearch?: () => void;
  onOpenHistory?: () => void;
  onClose: () => void;
}

export function AgentDetails({ agent, summary, onOpenHistory, onSearch, onClose, onCopyConversationLink }: Props) {
  const name = label(agent);
  const task = summary?.task;
  const runner = runnerLabel(task?.runner ?? agent.runner);
  const specialty = typeof agent.metadata?.specialty === "string" ? agent.metadata.specialty : undefined;
  return (
    <aside className="jg-details" aria-label={`${name} details`}>
      <header className="jg-details__head">
        <AgentAvatar id={agent.id} name={name} src={agent.avatar_url} size={44} />
        <div className="jg-details__who">
          <strong>{name}</strong>
          <span className="jg-muted">{ROLE_TEXT[agent.role ?? ""] ?? specialty ?? "Specialist"}</span>
        </div>
        <button type="button" className="jg-round-button" aria-label="Close details" onClick={onClose}>×</button>
      </header>
      <section className="jg-details__section">
        <h3>Now</h3>
        <p>{STATUS_TEXT[summary?.status ?? "idle"] ?? summary?.status}</p>
        {task?.goal && <p className="jg-muted">{task.goal}{task.eta ? ` · ETA ${String(task.eta)}` : ""}</p>}
        {runner && <p className="jg-muted">Runs on {runner}</p>}
      </section>
      {(agent.skills?.length ?? 0) > 0 && (
        <section className="jg-details__section" aria-label="Skills">
          <h3>Skills</h3>
          <ul className="jg-skill-list">
            {agent.skills!.map((s) => (
              <li key={s.id} className="jg-skill" title={s.source_path}>
                <span className="jg-skill__name">{s.name}</span>
                {s.description && <span className="jg-skill__desc">{s.description}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {(agent.allowed_tools?.length ?? 0) > 0 && (
        <section className="jg-details__section" aria-label="Tools">
          <h3>Tools</h3>
          <ul className="jg-tool-chips">{agent.allowed_tools!.map((t) => <li key={t} className="jg-tool-chip">{t}</li>)}</ul>
        </section>
      )}
      <section className="jg-details__section" aria-label="Bot access">
        <h3>Access</h3>
        {agent.access?.scope === 'local_operator' ? <>
          <p>Local operator access. Sections, pins and primary selection organize navigation; they do not grant membership or share conversations.</p>
          <p>Cross-account sharing is unavailable: {agent.access.reason}.</p>
        </> : <p>This adapter does not advertise a supported account-sharing authority.</p>}
      </section>
      {onCopyConversationLink&&<button type="button" onClick={onCopyConversationLink}>Copy local conversation link</button>}
      {onSearch && <button type="button" className="aui-button" onClick={onSearch}>Search messages</button>}
      {onOpenHistory && (
        <section className="jg-details__section">
          <button type="button" className="aui-button jg-details__history" onClick={onOpenHistory}>History</button>
        </section>
      )}
    </aside>
  );
}
