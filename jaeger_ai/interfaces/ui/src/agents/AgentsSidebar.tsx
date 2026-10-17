import { AppsIcon, PlusIcon, SearchIcon, TasksIcon } from "../icons";
import type { AgentsState } from "./agentsStore";
import { AgentRow } from "./AgentRow";
import { sidebarRows } from "./agentsLogic";
import { SupervisorTile } from "./SupervisorTile";
import { isUnread } from "./unread";

export type Selection = { type: "agent"; agentId: string } | { type: "tasks" };

interface Props {
  state: AgentsState;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  onNewChat: () => void;
  onSearch: () => void;
  onConnectApps: () => void;
  userInitials: string;
}

/** Sidebar content split into the AppShell slots: top / primary / sections / footer. */
export function agentsSidebarSlots({ state, selection, onSelect, onNewChat, onSearch, onConnectApps, userInitials }: Props) {
  const { lead, specialists } = sidebarRows(state.agents, state.summaries);
  const selectedAgent = selection.type === "agent" ? selection.agentId : undefined;
  return {
    top: (
      <div className="jg-sidebar-header" data-aether-window-drag-region>
        <span className="jg-sidebar-header__spacer" />
        <button type="button" className="jg-round-button" aria-label="Search" title="Search" onClick={onSearch}><SearchIcon /></button>
        <button type="button" className="jg-round-button" aria-label="New chat" title="New chat (⌘N)" onClick={onNewChat}><PlusIcon /></button>
      </div>
    ),
    primary: (
      <>
        {lead && <SupervisorTile row={lead} selected={selectedAgent === lead.agent.id} onSelect={() => onSelect({ type: "agent", agentId: lead.agent.id })} />}
        <nav className="jg-agent-list" aria-label="Specialists">
          {specialists.map((row) => (
            <AgentRow
              key={row.agent.id}
              row={row}
              selected={selectedAgent === row.agent.id}
              unread={selectedAgent !== row.agent.id && isUnread(row.agent.id, row.lastActivityAt, state.seen, row.summary?.unseen)}
              onSelect={() => onSelect({ type: "agent", agentId: row.agent.id })}
            />
          ))}
          {!state.loading && !specialists.length && <p className="jg-muted jg-pad">No specialists yet.</p>}
        </nav>
      </>
    ),
    sections: (
        <button type="button" className={`jg-nav-entry${selection.type === "tasks" ? " is-selected" : ""}`} onClick={() => onSelect({ type: "tasks" })}>
          <TasksIcon /> <span>Tasks</span>
        </button>
    ),
    footer: (
      <div className="jg-sidebar-footer">
        <button type="button" className="jg-user-chip" aria-label="Account">{userInitials}</button>
        <button type="button" className="jg-pill" onClick={onConnectApps}><AppsIcon /> Connect apps</button>
      </div>
    ),
  };
}
