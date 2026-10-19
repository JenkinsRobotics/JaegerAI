import type { SidebarControl } from "../shell/AppShell";
import { GlyphBranch, GlyphCode, GlyphCube, PlusIcon, SearchIcon, SidebarIcon, TasksIcon } from "../icons";
import { ErrorState } from "../shell/ErrorState";
import type { SessionRow } from "../api/types";
import type { AgentsState } from "./agentsStore";
import { groupRows } from "./sections";
import { AgentRow } from "./AgentRow";
import { sidebarRows } from "./agentsLogic";
import { ChatList } from "./ChatList";
import { PinnedArea } from "./PinnedArea";
import { AGENT_DRAG_TYPE, splitPinned } from "./pins";
import { SpecialistList } from "./SpecialistList";
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
  onSettings?: () => void;
  onRetry: () => void;
  userInitials: string;
  /** Connection status, shown as a small dot on the user avatar (no tray). */
  status: { kind: "ok" | "warn" | "error"; label: string };
  /** Specialists pinned beside the supervisor (pins.ts), in order. */
  pins?: string[];
  onPin?: (agentId: string, index?: number) => void;
  onUnpin?: (agentId: string) => void;
  /** Agent right-click: "Show info" and "Chat history". */
  onInfo?: (agentId: string) => void;
  onHistory?: (agentId: string) => void;
  onMarkRead?: (agentId: string) => void;
  onAgentMenu?: (agentId: string, x: number, y: number) => void;
}

/** Sidebar content split into the AppShell slots: top / primary / sections / footer. */
export function agentsSidebarSlots({ state, selection, chats, onSelect, onNewChatMenu, onRenameChat, onArchiveChat, onSearch, onConnectApps, onSettings, onRetry, userInitials, status, pins = [], onPin = () => {}, onUnpin = () => {}, onInfo, onHistory, onMarkRead, onAgentMenu }: Props) {
  const { lead, specialists: all } = sidebarRows(state.agents, state.summaries);
  const { pinned, rest: specialists } = splitPinned(all, pins);
  const selectedAgent = selection.type === "agent" ? selection.agentId : undefined;
  const openId = selection.type === "agent" ? selection.sessionId : undefined;
  const chatsFor = (agentId: string) => selectedAgent === agentId && (
    <ChatList rows={chats} openId={openId} onRename={onRenameChat} onArchive={onArchiveChat}
      onOpen={(sessionId) => onSelect({ type: "agent", agentId, sessionId })} />
  );
  return {
    top: (sidebar: SidebarControl) => (
      <div className="jg-sidebar-header" data-aether-window-drag-region>
        <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
        <span className="jg-sidebar-header__spacer" />
        <button type="button" className="jg-icon-button" aria-label={sidebar.collapsed ? "Show sidebar" : "Hide sidebar"}
          aria-expanded={!sidebar.collapsed} title={sidebar.collapsed ? "Show sidebar" : "Hide sidebar"} onClick={sidebar.toggle}><SidebarIcon /></button>
        <button type="button" className="jg-round-button" aria-label="Search" title="Search" onClick={onSearch}><SearchIcon /></button>
        <button type="button" className="jg-round-button" aria-label="New chat" aria-haspopup="menu" title="New chat (⌘N)"
          onClick={(e) => onNewChatMenu(e.currentTarget)}><PlusIcon /></button>
      </div>
    ),
    primary: (
      <>
        {state.error && <ErrorState compact title="Couldn't load agents" error={state.error} onRetry={onRetry} />}
        {(lead || pinned.length > 0) && (
          <PinnedArea lead={lead} pinned={pinned} selectedId={selectedAgent}
            unread={(row) => selectedAgent !== row.agent.id && isUnread(row.agent.id, row.lastActivityAt, state.seen, row.summary?.unseen)}
            onSelect={(agentId) => onSelect({ type: "agent", agentId })} onPin={onPin} onUnpin={onUnpin}>
            {lead && chatsFor(lead.agent.id)}
            {pinned.map((row) => <div key={row.agent.id}>{chatsFor(row.agent.id)}</div>)}
          </PinnedArea>
        )}
        <SpecialistList dragType={AGENT_DRAG_TYPE} onPin={onPin} onUnpin={onUnpin} onInfo={onInfo} onHistory={onHistory} onMarkRead={onMarkRead} onAgentMenu={onAgentMenu} emptyDropHint={!specialists.length && pinned.length > 0}>
          {groupRows(specialists, state.sections ?? [], { pinnedGroup: false }).map((g) => [
            g.title && <div key={`h:${g.id}`} className="jg-agent-section" role="heading" aria-level={3}>{g.title}</div>,
            ...g.rows.map((row) => (
            <div key={row.agent.id} className="jg-agent-list__item" draggable
              onDragStart={(e) => { e.dataTransfer.setData(AGENT_DRAG_TYPE, row.agent.id); e.dataTransfer.effectAllowed = "move"; }}
              data-agent-id={row.agent.id}>
              <AgentRow
                row={row}
                selected={selectedAgent === row.agent.id}
                unread={selectedAgent !== row.agent.id && isUnread(row.agent.id, row.lastActivityAt, state.seen, row.summary?.unseen)}
                onSelect={() => onSelect({ type: "agent", agentId: row.agent.id })}
              />
              {chatsFor(row.agent.id)}
            </div>
          ))])}
          {!state.loading && !state.error && !all.length && <p className="jg-muted jg-pad">No specialists yet.</p>}
        </SpecialistList>
      </>
    ),
    sections: (
        <button type="button" className={`jg-nav-entry${selection.type === "tasks" ? " is-selected" : ""}`} onClick={() => onSelect({ type: "tasks" })}>
          <TasksIcon width={14} height={14} /> <span>Tasks</span>
        </button>
    ),
    footer: (
      <div className="jg-sidebar-footer">
        <button type="button" className="jg-user-chip" aria-label={`Account · ${status.label}`} title={`${status.label} · Settings (⌘,)`} onClick={onSettings}>
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
