/* Details panel (Grok Bot: click the Bot's name at the top of the chat):
 * who the agent is, what it is doing now, and its chats. Read-only. */
import type { Agent, AgentSummary, SessionRow } from "../api/types";
import { AgentAvatar } from "./AgentAvatar";
import { label, ROLE_TEXT, runnerLabel } from "./agentsLogic";
import { activityAt, chatTitle, shortTime } from "./chats";

const STATUS_TEXT: Record<string, string> = {
  idle: "Idle", working: "Working", waiting_approval: "Needs your approval", blocked: "Blocked", error: "Error",
};

interface Props {
  agent: Agent;
  summary?: AgentSummary;
  chats: SessionRow[];
  openId?: string;
  onOpenChat: (sessionId: string) => void;
  onNewChat: () => void;
  onClose: () => void;
}

export function AgentDetails({ agent, summary, chats, openId, onOpenChat, onNewChat, onClose }: Props) {
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
      <section className="jg-details__section">
        <div className="jg-details__row">
          <h3>Chats</h3>
          <button type="button" className="aui-button" onClick={onNewChat}>New chat</button>
        </div>
        {chats.length ? (
          <ul className="jg-chat-list">
            {chats.map((row) => (
              <li key={row.session_id}>
                <button type="button" className={`jg-chat-row${row.session_id === openId ? " is-open" : ""}`} onClick={() => onOpenChat(row.session_id)}>
                  <span className="jg-chat-row__title">{chatTitle(row)}</span>
                  <span className="jg-chat-row__time">{shortTime(activityAt(row))}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="jg-muted">No chats yet.</p>}
      </section>
    </aside>
  );
}
