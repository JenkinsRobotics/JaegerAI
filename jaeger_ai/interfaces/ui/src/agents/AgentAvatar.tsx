import { StarIcon } from "../icons";
import { initials } from "./agentsLogic";

/** Avatar image when the agent has one, initials otherwise (D1: no per-agent hues). */
export function AgentAvatar({ name, src, lead, size = 32 }: { name: string; src?: string; lead?: boolean; size?: number }) {
  return (
    <span className={`jg-avatar${lead ? " jg-avatar--lead" : ""}`} style={{ width: size, height: size }} aria-hidden="true">
      {src ? <img src={src} alt="" /> : <span className="jg-avatar__initials">{lead ? "J" : initials(name)}</span>}
      {lead && <span className="jg-avatar__badge"><StarIcon width={9} height={9} /></span>}
    </span>
  );
}
