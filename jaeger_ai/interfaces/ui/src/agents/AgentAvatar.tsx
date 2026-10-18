import type { CSSProperties, ReactNode } from "react";
import { StarIcon } from "../icons";
import { avatarColor, avatarFace, avatarShape, type AvatarShape } from "./avatarColor";

/** Agent avatar: one of a few hand-drawn silhouettes (by a hash of the id) in the agent's color, with a
 * two-eye face that looks its own way; or the agent's image, clipped round. Silhouettes are Jaeger originals. */
const SHAPES: Record<AvatarShape, ReactNode> = {
  circle: <circle cx="18" cy="18" r="18" />,
  blob: <path d="M18.6 1.2c6.1.2 11.3 3 13.9 7.9 2.4 4.6 2.7 10.4.5 15.2-2.4 5.3-7.6 9.9-14.6 10.4-7.3.5-13.3-3.2-15.9-8.6C.2 21.3.3 15 3.2 10 6 5 11.6 1 18.6 1.2z" />,
  hexagon: <polygon points="18,2.2 31.7,10.1 31.7,25.9 18,33.8 4.3,25.9 4.3,10.1" strokeWidth="4.4" strokeLinejoin="round" stroke="currentColor" />,
  cloud: <><circle cx="11.5" cy="21" r="10" /><circle cx="24.5" cy="21" r="10" /><circle cx="18" cy="13.5" r="11.5" /><rect x="11.5" y="18" width="13" height="13" /></>,
  pill: <rect x="0.5" y="4.5" width="35" height="27" rx="13.5" />,
  squircle: <rect x="3.3" y="4" width="29.4" height="28" rx="5.6" />,
};

/** The lead squircle's tilt drifts slowly (observed in the reference: about -25° at one point,
 * about -8° half an hour later). One sweep takes LEAD_DRIFT_SECONDS; the phase comes from the wall
 * clock so a remount or reload never snaps it back. */
export const LEAD_DRIFT_SECONDS = 1200;
export function leadDriftPhase(now = Date.now()): number {
  return Math.round((now / 1000) % (LEAD_DRIFT_SECONDS * 2));
}

export function AgentAvatar({ id, name, src, size = 36 }: { id: string; name: string; src?: string; size?: number }) {
  const shape = avatarShape(id);
  const face = avatarFace(id, shape);
  const style = {
    width: size, height: size, "--jg-avatar-color": avatarColor(id),
    "--jg-avatar-spin": `${face.spin}deg`, "--jg-eye-x": `${(face.dx * size) / 100}px`,
    "--jg-eye-y": `${(face.dy * size) / 100}px`, "--jg-eye-tilt": `${face.tilt}deg`,
    "--jg-glance-x": `${(face.glance.dx * size) / 100}px`, "--jg-glance-y": `${(face.glance.dy * size) / 100}px`,
    "--jg-glance-delay": `-${face.glance.delay}s`, "--jg-blink": `${face.blink}s`,
    ...(shape === "squircle" ? { "--jg-drift-delay": `-${leadDriftPhase()}s` } : {}),
  } as CSSProperties;
  return (
    <span className={`jg-avatar jg-avatar--${src ? "image" : shape}`} style={style} aria-hidden="true" title={name} data-shape={src ? undefined : shape}>
      {src ? <img src={src} alt="" /> : (
        <span className="jg-avatar__body">
          <svg className="jg-avatar__shape" viewBox="0 0 36 36" fill="currentColor" aria-hidden="true">{SHAPES[shape]}</svg>
          <span className={`jg-avatar__face jg-avatar__face--${face.eyes}`}><i /><i /></span>
        </span>
      )}
    </span>
  );
}

/** A pinned tile's art: the agent's avatar, larger. The corner shows the unread dot, else (for the
 * supervisor) its star badge. */
export function SupervisorArt({ id, name, unread = false, lead = false, size = 54 }: { id: string; name: string; unread?: boolean; lead?: boolean; size?: number }) {
  return (
    <span className="jg-supervisor-art" style={{ width: size, height: size }} aria-hidden="true">
      <AgentAvatar id={id} name={name} size={size} />
      {unread ? <span className="jg-supervisor-art__dot" /> : lead && <span className="jg-supervisor-art__badge"><StarIcon width={9} height={9} /></span>}
    </span>
  );
}
