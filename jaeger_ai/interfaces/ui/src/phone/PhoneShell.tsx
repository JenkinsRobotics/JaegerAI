/* Phone layout (≤ 700px or touch), rebuilt from Matthew's description of Grok Bot's iOS app — no window chrome.
 * List: top bar (user avatar + presence dot; round Search and New buttons), the lead featured large with a star
 * badge, then full-width agent rows (avatar + active dot, bold name, time, a one-line preview with a type icon,
 * unread dot) and a floating "N unread" pill that jumps to the first unread row.
 * Chat: a translucent floating bar (back, centred avatar+name pill, … for info) over the chat; back or a swipe
 * from the left edge returns to the list. Data is the real roster/summaries; the preview type comes from the
 * gateway's last_source (handoff / task / chat) and falls back to no icon. */
import { useRef, type ReactNode, type TouchEvent } from "react";
import { AgentAvatar } from "../agents/AgentAvatar";
import { label, sidebarRows, type SidebarRow } from "../agents/agentsLogic";
import { isUnread } from "../agents/unread";
import { Icon, type IconName } from "../icons/Icon";
import type { AgentsState } from "../agents/agentsStore";
import { rowTime } from "./usePhone";

const SOURCE_ICON: Record<string, IconName> = { chat: "comment", message: "comment", handoff: "arrow-right", sent: "arrow-right", task: "checklist" };

/** Seconds since epoch from last_message.created_at (ISO string or seconds/ms number). */
export function epochOf(v: string | number | undefined | null): number {
  if (v === undefined || v === null || v === "") return 0;
  if (typeof v === "number") return v > 1e12 ? v / 1000 : v;
  const t = Date.parse(v); return Number.isNaN(t) ? 0 : t / 1000;
}
/** Row data: the proposed last_message / unread_count / primary when the gateway sends them, else the summary. */
export function rowView(r: SidebarRow, seen: Record<string, number>) {
  const m = r.agent.last_message ?? undefined;
  const at = m ? epochOf(m.created_at) || r.lastActivityAt : r.lastActivityAt;
  const kind = m?.kind ?? r.summary?.last_source ?? undefined;
  return {
    preview: m?.preview ?? r.summary?.last_preview ?? "",
    at,
    icon: kind ? SOURCE_ICON[kind] : undefined,
    unread: typeof r.agent.unread_count === "number" ? r.agent.unread_count > 0 : isUnread(r.agent.id, r.lastActivityAt, seen, r.summary?.unseen),
  };
}
const ACTIVE = new Set(["working", "running", "busy", "thinking"]);


export function PhoneList({ state, userInitials, onOpen, onSearch, onNew, onSettings, statusOk }: {
  state: Pick<AgentsState, "agents" | "summaries" | "seen">; userInitials: string; statusOk: boolean;
  onOpen: (agentId: string) => void; onSearch: () => void; onNew: (anchor: HTMLElement) => void; onSettings: () => void;
}) {
  const rows = sidebarRows(state.agents, state.summaries);
  const all = [...(rows.lead ? [rows.lead] : []), ...rows.specialists];
  const lead = all.find((r) => r.agent.primary) ?? rows.lead;
  const specialists = all.filter((r) => r !== lead).sort((a, b) => rowView(b, state.seen).at - rowView(a, state.seen).at);
  const list = useRef<HTMLDivElement>(null);
  const unread = (r: SidebarRow) => rowView(r, state.seen).unread;
  const unreadCount = specialists.filter(unread).length;
  const jump = () => list.current?.querySelector<HTMLElement>(".jg-prow.is-unread")?.scrollIntoView({ block: "center", behavior: "smooth" });
  return (
    <div className="jg-phone-screen jg-phone-list" ref={list}>
      <header className="jg-ptop">
        <button type="button" className="jg-pme" aria-label="Settings" onClick={onSettings}>
          {userInitials}{statusOk && <span className="jg-pme__dot" aria-hidden />}
        </button>
        <span className="jg-ptop__spacer" />
        <button type="button" className="jg-pround" aria-label="Search" onClick={onSearch}><Icon name="search" size={18} /></button>
        <button type="button" className="jg-pround" aria-label="New chat" onClick={(e) => onNew(e.currentTarget)}><Icon name="add" size={18} /></button>
      </header>
      {lead && (
        <button type="button" className="jg-plead" onClick={() => onOpen(lead.agent.id)} aria-label={`Open ${label(lead.agent)}`}>
          <span className="jg-plead__art">
            <AgentAvatar id={lead.agent.id} name={label(lead.agent)} src={lead.agent.avatar_url} size={110} />
            <span className="jg-plead__badge" aria-hidden><Icon name="star-full" size={11} /></span>
          </span>
          <span className="jg-plead__name">{label(lead.agent)}</span>
        </button>
      )}
      <nav className="jg-prows" aria-label="Agents">
        {specialists.map((r) => {
          const v = rowView(r, state.seen); const u = v.unread;
          const name = label(r.agent);
          return (
            <button key={r.agent.id} type="button" className={`jg-prow${u ? " is-unread" : ""}`} onClick={() => onOpen(r.agent.id)}>
              <span className="jg-prow__art">
                <AgentAvatar id={r.agent.id} name={name} src={r.agent.avatar_url} size={48} />
                {r.summary?.status && ACTIVE.has(String(r.summary.status)) && <span className="jg-prow__active" aria-label="Active" />}
              </span>
              <span className="jg-prow__body">
                <span className="jg-prow__line"><span className="jg-prow__name">{name}</span><span className="jg-prow__time">{rowTime(v.at)}</span></span>
                <span className="jg-prow__line">
                  <span className="jg-prow__preview">{v.icon && <Icon name={v.icon} size={13} className="jg-prow__type" />}{v.preview || "No activity yet"}</span>
                  {u && <span className="jg-prow__dot" aria-label="Unread" />}
                </span>
              </span>
            </button>
          );
        })}
      </nav>
      {unreadCount > 0 && (
        <button type="button" className="jg-punread" onClick={jump}><Icon name="chevron-down" size={14} />{unreadCount} unread</button>
      )}
    </div>
  );
}

export function PhoneChat({ agentId, agentName, avatarUrl, onBack, onInfo, children }: {
  agentId: string; agentName: string; avatarUrl?: string; onBack: () => void; onInfo: () => void; children: ReactNode;
}) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const onTouchStart = (e: TouchEvent) => { const t = e.touches[0]; start.current = t.clientX < 24 ? { x: t.clientX, y: t.clientY } : null; };
  const onTouchEnd = (e: TouchEvent) => {
    const s = start.current; start.current = null; const t = e.changedTouches[0];
    if (s && t.clientX - s.x > 80 && Math.abs(t.clientY - s.y) < 60) onBack();
  };
  return (
    <div className="jg-phone-screen jg-phone-chat" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <header className="jg-pbar">
        <button type="button" className="jg-pround" aria-label="Back" onClick={onBack}><Icon name="chevron-left" size={18} /></button>
        <span className="jg-pbar__pill"><AgentAvatar id={agentId} name={agentName} src={avatarUrl} size={22} /><span>{agentName}</span></span>
        <button type="button" className="jg-pround" aria-label="Agent info" onClick={onInfo}><Icon name="ellipsis" size={18} /></button>
      </header>
      <div className="jg-pchat">{children}</div>
    </div>
  );
}
