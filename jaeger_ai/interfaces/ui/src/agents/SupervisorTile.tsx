import type { SidebarRow } from "./agentsLogic";
import { label } from "./agentsLogic";
import { SupervisorArt } from "./AgentAvatar";
import { useAvatarState } from "./avatarMotion";

/** Pinned supervisor card: square tile, its tilted avatar (+ unread dot), name underneath. */
export function SupervisorTile({ row, selected, unread = false, onSelect }: { row: SidebarRow; selected: boolean; unread?: boolean; onSelect: () => void }) {
  const name = label(row.agent);
  const state = useAvatarState(row.summary?.status, unread);
  return (
    <div className="jg-supervisor-wrap">
      <button type="button" className={`jg-supervisor${selected ? " is-selected" : ""}`} aria-current={selected ? "page" : undefined} onClick={onSelect} title={row.agent.primary ? `${name} · Primary bot` : name}>
        <SupervisorArt id={row.agent.id} name={name} unread={unread} preset={row.agent.icon_preset} primary={row.agent.primary === true} state={state} />
        <span className="jg-supervisor__label">{name}</span>
      </button>
    </div>
  );
}
