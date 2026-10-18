/* The specialist list: a drop target that unpins a dragged tile, and a right-click "Pin to top" on
 * each row (the keyboard/VoiceOver path to the same thing). */
import { Menu, type MenuItem } from "@aether/ui";
import { useState, type DragEvent, type MouseEvent, type ReactNode } from "react";

const ROW_MENU: MenuItem[] = [{ id: "pin", label: "Pin to top" }];

export function SpecialistList({ dragType, onPin, onUnpin, children }: {
  dragType: string; onPin: (agentId: string) => void; onUnpin: (agentId: string) => void; children: ReactNode;
}) {
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const carries = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes(dragType);
  const onContextMenu = (e: MouseEvent<HTMLElement>) => {
    const item = (e.target as HTMLElement).closest<HTMLElement>("[data-agent-id]");
    if (!item?.dataset.agentId) return;
    e.preventDefault();
    setMenu({ id: item.dataset.agentId, x: e.clientX, y: e.clientY });
  };
  return (
    <nav className="jg-agent-list" aria-label="Specialists" onContextMenu={onContextMenu}
      onDragOver={(e) => { if (carries(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
      onDrop={(e) => { if (!carries(e)) return; e.preventDefault(); const id = e.dataTransfer.getData(dragType); if (id) onUnpin(id); }}>
      {children}
      <Menu open={Boolean(menu)} anchor={menu ? { x: menu.x, y: menu.y } : null} items={ROW_MENU} ariaLabel="Agent actions"
        onClose={() => setMenu(null)} onSelect={() => { if (menu) onPin(menu.id); setMenu(null); }} />
    </nav>
  );
}
