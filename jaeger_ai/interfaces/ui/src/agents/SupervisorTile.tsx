import type { SidebarRow } from "./agentsLogic";
import { label } from "./agentsLogic";
import { SupervisorArt } from "./AgentAvatar";

/** Pinned supervisor card: square tile, art + star badge, name underneath. */
export function SupervisorTile({ row, selected, onSelect }: { row: SidebarRow; selected: boolean; onSelect: () => void }) {
  const name = label(row.agent);
  return (
    <div className="jg-supervisor-wrap">
      <button type="button" className={`jg-supervisor${selected ? " is-selected" : ""}`} aria-current={selected ? "page" : undefined} onClick={onSelect} title={name}>
        <SupervisorArt />
        <span className="jg-supervisor__label">{name}</span>
      </button>
    </div>
  );
}
