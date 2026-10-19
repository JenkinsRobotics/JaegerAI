/* The specialist list: a drop target that unpins a dragged tile, and a right-click "Pin to top" on
 * each row (the keyboard/VoiceOver path to the same thing). */
import { type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useState, type DragEvent, type MouseEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon";

// Grok's Bot actions, scoped to what Jaeger has: Pin, Mark as read (per-device seen mark), the info pane, older
// chats, Copy agent ID. Grok's open agent menu was never captured: its order/extra items need the phase-B capture.
// Rename / Delete / Hide aren't offered: the gateway has no endpoint for them yet.
const ROW_MENU: MenuItem[] = [
  { id: "pin", label: "Pin to top", icon: <Icon name="pin" size={14} /> },
  { id: "read", label: "Mark as read", icon: <Icon name="mail-read" size={14} /> },
  { id: "info", label: "Show info", icon: <Icon name="info" size={14} />, separatorBefore: true },
  { id: "history", label: "Chat history", icon: <Icon name="history" size={14} /> },
  { id: "copy-id", label: "Copy agent ID", icon: <Icon name="copy" size={14} />, separatorBefore: true },
];

export function SpecialistList({ dragType, onPin, onUnpin, onInfo, onHistory, onMarkRead, onAgentMenu, emptyDropHint = false, children }: {
  dragType: string; onPin: (agentId: string) => void; onUnpin: (agentId: string) => void;
  onInfo?: (agentId: string) => void; onHistory?: (agentId: string) => void; onMarkRead?: (agentId: string) => void;
  /** Grok-style agent context menu (AgentContextMenu, owned by App); replaces the small menu below when set. */
  onAgentMenu?: (agentId: string, x: number, y: number) => void;
  /** Every specialist is pinned: keep a visible zone so a tile can still be dragged back. */
  emptyDropHint?: boolean; children: ReactNode;
}) {
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [over, setOver] = useState(false);
  const carries = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes(dragType);
  const onContextMenu = (e: MouseEvent<HTMLElement>) => {
    const item = (e.target as HTMLElement).closest<HTMLElement>("[data-agent-id]");
    if (!item?.dataset.agentId) return;
    e.preventDefault();
    if (onAgentMenu) { onAgentMenu(item.dataset.agentId, e.clientX, e.clientY); return; }
    setMenu({ id: item.dataset.agentId, x: e.clientX, y: e.clientY });
  };
  return (
    <nav className={`jg-agent-list${over ? " is-drop-target" : ""}`} aria-label="Specialists" onContextMenu={onContextMenu}
      onDragOver={(e) => { if (carries(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); }}
      onDrop={(e) => { if (!carries(e)) return; e.preventDefault(); setOver(false); const id = e.dataTransfer.getData(dragType); if (id) onUnpin(id); }}>
      {children}
      {emptyDropHint && <p className="jg-agent-list__drop-hint">Drag a pinned agent here to unpin it</p>}
      <Menu open={Boolean(menu)} anchor={menu ? { x: menu.x, y: menu.y } : null} items={ROW_MENU.filter((i) => (i.id !== "info" || onInfo) && (i.id !== "history" || onHistory) && (i.id !== "read" || onMarkRead))} ariaLabel="Agent actions"
        onClose={() => setMenu(null)} onSelect={(action) => {
          if (menu && action === "copy-id") void navigator.clipboard?.writeText(menu.id).catch(() => {});
          else if (menu) (action === "info" ? onInfo : action === "history" ? onHistory : action === "read" ? onMarkRead : onPin)?.(menu.id);
          setMenu(null);
        }} />
    </nav>
  );
}
