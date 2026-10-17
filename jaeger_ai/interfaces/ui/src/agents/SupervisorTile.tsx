import type { SidebarRow } from "./agentsLogic";
import { AgentAvatar } from "./AgentAvatar";

export function SupervisorTile({ row, selected, onSelect }: { row: SidebarRow; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" className={`jg-supervisor${selected ? " is-selected" : ""}`} aria-current={selected ? "page" : undefined} onClick={onSelect}>
      <AgentAvatar name="Jaeger" src={row.agent.avatar_url} lead size={36} />
      <span className="jg-supervisor__label">Jaeger</span>
    </button>
  );
}
