import { GlyphBranch, GlyphCode, GlyphCube, PlusIcon, SearchIcon, TasksIcon } from "../icons";
import { ErrorState } from "../shell/ErrorState";
import type { SessionRow } from "../api/types";
import type { AgentsState } from "./agentsStore";
import { AgentRow } from "./AgentRow";
import { sidebarRows } from "./agentsLogic";
import { ChatList } from "./ChatList";
import { SupervisorTile } from "./SupervisorTile";
import { isUnread } from "./unread";

/** An agent, optionally one of its chats; or the Tasks board. */
export type Selection = { type: "agent"; agentId: string; sessionId?: string } | { type: "tasks" };

interface Props {
  state: AgentsState;
  selection: Selection;
  /** The selected agent's visible chats (chats.visibleChats). */
  chats: SessionRow[];
  onSelect: (selection: Selection) => void;
  /** The + button: opens the New chat menu anchored to it. */
  onNewChatMenu: (anchor: HTMLElement) => void;
  onRenameChat: (sessionId: string, title: string) => void;
  onArchiveChat: (sessionId: string) => void;
  onSearch: () => void;
  onConnectApps: () => void;
  onRetry: () => void;
  userInitials: string;
  /** Connection status, shown as a small dot on the user avatar (no tray). */
  status: { kind: "ok" | "warn" | "error"; label: string };
}

/** Sidebar content split into the AppShell slots: top / primary / sections / footer. */
export function agentsSidebarSlots({ state, selection, chats, onSelect, onNewChatMenu, onRenameChat, onArchiveChat, onSearch, onConnectApps, onRetry, userInitials, status }: Props) {
  const { lead, specialists } = sidebarRows(state.agents, state.summaries);
  const selectedAgent = selection.type === "agent" ? selection.agentId : undefined;
  const openId = selection.type === "agent" ? selection.sessionId : undefined;
  const chatsFor = (agentId: string) => selectedAgent === agentId && (
    <ChatList rows={chats} openId={openId} onRename={onRenameChat} onArchive={onArchiveChat}
      onOpen={(sessionId) => onSelect({ type: "agent", agentId, sessionId })} />
  );
  return {
    top: (
      <div className="jg-sidebar-header" data-aether-window-drag-region>
        <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
        <span className="jg-sidebar-header__spacer" />
        <button type="button" className="jg-round-button" aria-label="Search" title="Search" onClick={onSearch}><SearchIcon /></button>
        <button type="button" className="jg-round-button" aria-label="New chat" aria-haspopup="menu" title="New chat (⌘N)"
          onClick={(e) => onNewChatMenu(e.currentTarget)}><PlusIcon /></button>
      </div>
    ),
    primary: (
      <>
        {state.error && <ErrorState compact title="Couldn't load agents" error={state.error} onRetry={onRetry} />}
        {lead && <SupervisorTile row={lead} selected={selectedAgent === lead.agent.id} onSelect={() => onSelect({ type: "agent", agentId: lead.agent.id })} />}
        {lead && chatsFor(lead.agent.id)}
        <nav className="jg-agent-list" aria-label="Specialists">
          {specialists.map((row) => (
            <div key={row.agent.id}>
              <AgentRow
                row={row}
                selected={selectedAgent === row.agent.id}
                unread={selectedAgent !== row.agent.id && isUnread(row.agent.id, row.lastActivityAt, state.seen, row.summary?.unseen)}
                onSelect={() => onSelect({ type: "agent", agentId: row.agent.id })}
              />
              {chatsFor(row.agent.id)}
            </div>
          ))}
          {!state.loading && !state.error && !specialists.length && <p className="jg-muted jg-pad">No specialists yet.</p>}
        </nav>
      </>
    ),
    sections: (
        <button type="button" className={`jg-nav-entry${selection.type === "tasks" ? " is-selected" : ""}`} onClick={() => onSelect({ type: "tasks" })}>
          <TasksIcon width={14} height={14} /> <span>Tasks</span>
        </button>
    ),
    footer: (
      <div className="jg-sidebar-footer">
        <button type="button" className="jg-user-chip" aria-label={`Account · ${status.label}`} title={status.label}>
          {userInitials}
          <span className={`jg-user-chip__status jg-user-chip__status--${status.kind}`} />
        </button>
        <button type="button" className="jg-pill" onClick={onConnectApps}>
          <span>Connect apps</span>
          <span className="jg-pill__glyphs" aria-hidden="true"><GlyphCode width={12} height={12} /><GlyphBranch width={12} height={12} /><GlyphCube width={12} height={12} /></span>
        </button>
      </div>
    ),
  };
}
