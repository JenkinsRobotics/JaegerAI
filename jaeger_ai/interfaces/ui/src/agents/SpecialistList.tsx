/* The specialist list: a drop target that unpins a dragged tile, and a right-click "Pin to top" on
 * each row (the keyboard/VoiceOver path to the same thing). */
import { type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useState, type DragEvent, type MouseEvent, type ReactNode } from "react";

// Grok's Bot actions, scoped to what Jaeger has (Pin, plus the info pane and older chats).
const ROW_MENU: MenuItem[] = [
  { id: "pin", label: "Pin to top" },
  { id: "info", label: "Show info", separatorBefore: true },
  { id: "history", label: "Chat history" },
];

export function SpecialistList({ dragType, onPin, onUnpin, onInfo, onHistory, emptyDropHint = false, children }: {
  dragType: string; onPin: (agentId: string) => void; onUnpin: (agentId: string) => void;
  onInfo?: (agentId: string) => void; onHistory?: (agentId: string) => void;
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
    setMenu({ id: item.dataset.agentId, x: e.clientX, y: e.clientY });
  };
  return (
    <nav className={`jg-agent-list${over ? " is-drop-target" : ""}`} aria-label="Specialists" onContextMenu={onContextMenu}
      onDragOver={(e) => { if (carries(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); }}
      onDrop={(e) => { if (!carries(e)) return; e.preventDefault(); setOver(false); const id = e.dataTransfer.getData(dragType); if (id) onUnpin(id); }}>
      {children}
      {emptyDropHint && <p className="jg-agent-list__drop-hint">Drag a pinned agent here to unpin it</p>}
      <Menu open={Boolean(menu)} anchor={menu ? { x: menu.x, y: menu.y } : null} items={ROW_MENU.filter((i) => (i.id !== "info" || onInfo) && (i.id !== "history" || onHistory))} ariaLabel="Agent actions"
        onClose={() => setMenu(null)} onSelect={(action) => {
          if (menu) (action === "info" ? onInfo : action === "history" ? onHistory : onPin)?.(menu.id);
          setMenu(null);
        }} />
    </nav>
  );
}
