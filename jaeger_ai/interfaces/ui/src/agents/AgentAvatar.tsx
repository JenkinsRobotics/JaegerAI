import type { CSSProperties } from "react";
import { StarIcon } from "../icons";
import { avatarColor } from "./avatarColor";

/** Round agent avatar: a token-colored disc with a small face (two eyes), or
 * the agent's image when it has one. */
export function AgentAvatar({ id, name, src, size = 36 }: { id: string; name: string; src?: string; size?: number }) {
  const style = { width: size, height: size, "--jg-avatar-color": avatarColor(id) } as CSSProperties;
  return (
    <span className="jg-avatar" style={style} aria-hidden="true" title={name}>
      {src ? <img src={src} alt="" /> : <span className="jg-avatar__face"><i /><i /></span>}
    </span>
  );
}

/** The supervisor's art: three dots on a tile, plus the star badge. */
export function SupervisorArt({ size = 64 }: { size?: number }) {
  return (
    <span className="jg-supervisor-art" style={{ width: size, height: size }} aria-hidden="true">
      <span className="jg-supervisor-art__dots"><i /><i /><i /></span>
      <span className="jg-supervisor-art__badge"><StarIcon width={10} height={10} /></span>
    </span>
  );
}
