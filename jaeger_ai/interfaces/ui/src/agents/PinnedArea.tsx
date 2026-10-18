/* The pinned strip: the supervisor's tile, then pinned specialists. Drop an agent row here to pin it
 * (at the tile it's dropped on); drag a tile back to the list, or right-click it, to unpin. */
import { type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useState, type DragEvent, type ReactNode } from "react";
import type { SidebarRow } from "./agentsLogic";
import { AGENT_DRAG_TYPE } from "./pins";
import { SupervisorTile } from "./SupervisorTile";

const TILE_MENU: MenuItem[] = [{ id: "unpin", label: "Unpin" }];
const carriesAgent = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes(AGENT_DRAG_TYPE);

interface Props {
  lead?: SidebarRow;
  pinned: SidebarRow[];
  selectedId?: string;
  unread: (row: SidebarRow) => boolean;
  onSelect: (agentId: string) => void;
  onPin: (agentId: string, index?: number) => void;
  onUnpin: (agentId: string) => void;
  children?: ReactNode;
}

export function PinnedArea({ lead, pinned, selectedId, unread, onSelect, onPin, onUnpin, children }: Props) {
  const [over, setOver] = useState(false);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const onDragOver = (e: DragEvent<HTMLDivElement>) => { if (!carriesAgent(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(true); };
  const onDragLeave = (e: DragEvent<HTMLDivElement>) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); };
  const dropAt = (index?: number) => (e: DragEvent<HTMLElement>) => {
    if (!carriesAgent(e)) return;
    e.preventDefault();
    e.stopPropagation();
    setOver(false);
    const id = e.dataTransfer.getData(AGENT_DRAG_TYPE);
    if (id && id !== lead?.agent.id) onPin(id, index);
  };
  const tile = (row: SidebarRow, index?: number) => (
    <div key={row.agent.id} className="jg-pinned__slot" draggable={index !== undefined}
      onDragStart={index === undefined ? undefined : (e) => { e.dataTransfer.setData(AGENT_DRAG_TYPE, row.agent.id); e.dataTransfer.effectAllowed = "move"; }}
      onDrop={index === undefined ? undefined : dropAt(index)}
      onContextMenu={index === undefined ? undefined : (e) => { e.preventDefault(); setMenu({ id: row.agent.id, x: e.clientX, y: e.clientY }); }}>
      <SupervisorTile row={row} selected={selectedId === row.agent.id} unread={unread(row)} onSelect={() => onSelect(row.agent.id)} />
    </div>
  );
  return (
    <div className={`jg-pinned${over ? " is-drop-target" : ""}${pinned.length ? " has-pins" : ""}`} aria-label="Pinned"
      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={dropAt()}>
      <div className="jg-pinned__grid">
        {lead && tile(lead)}
        {pinned.map((row, i) => tile(row, i))}
      </div>
      {children}
      <Menu open={Boolean(menu)} anchor={menu ? { x: menu.x, y: menu.y } : null} items={TILE_MENU} ariaLabel="Pinned agent actions"
        onClose={() => setMenu(null)} onSelect={() => { if (menu) onUnpin(menu.id); setMenu(null); }} />
    </div>
  );
}
