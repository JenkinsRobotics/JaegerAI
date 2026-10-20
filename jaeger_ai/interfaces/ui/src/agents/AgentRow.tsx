import { label, runnerLabel, type SidebarRow } from "./agentsLogic";
import { AgentAvatar } from "./AgentAvatar";
import { useAvatarState } from "./avatarMotion";

export function AgentRow({ row, selected, unread, onSelect }: { row: SidebarRow; selected: boolean; unread: boolean; onSelect: () => void }) {
  const name = label(row.agent);
  const state = useAvatarState(row.summary?.status, unread);
  const runner = runnerLabel(row.summary?.task?.runner ?? row.agent.runner);
  return (
    <button type="button" className={`jg-agent-row${selected ? " is-selected" : ""}${unread ? " is-unread" : ""}`} aria-current={selected ? "page" : undefined} onClick={onSelect} title={runner ? `${name} · runs on ${runner}` : name}>
      <AgentAvatar id={row.agent.id} name={name} src={row.agent.avatar_url} state={state} primary={row.agent.primary === true} />
      <span className="jg-agent-row__text">
        <span className="jg-agent-row__name">{name}</span>
        <span className="jg-agent-row__preview">{row.summary?.last_preview || (runner ? `Runs on ${runner}` : "No activity yet")}</span>
      </span>
      <span className={`jg-unread-dot${unread ? "" : " is-hidden"}`} aria-label={unread ? "Unread" : undefined} />
    </button>
  );
}
