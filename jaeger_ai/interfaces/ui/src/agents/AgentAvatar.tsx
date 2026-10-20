import type { CSSProperties, ReactNode } from "react";
import { StarIcon } from "../icons";
import { avatarColor, avatarFace, avatarShape, type AvatarShape } from "./avatarColor";
import type { AvatarState } from "./avatarMotion";

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
/** States that draw an activity mark over the avatar (dots, an orbiting dot, a gathering ring). */
const OVERLAY: Partial<Record<AvatarState, string>> = { thinking: "dots", waiting: "orbit", spawning: "gather" };

export const LEAD_DRIFT_SECONDS = 1200;
export function leadDriftPhase(now = Date.now()): number {
  return Math.round((now / 1000) % (LEAD_DRIFT_SECONDS * 2));
}

export function AgentAvatar({ id, name, src, size = 36, state, primary = false, preset }: { preset?: string | null; primary?: boolean; id: string; name: string; src?: string; size?: number; state?: AvatarState }) {
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
    <span className={`jg-avatar jg-avatar--${src ? "image" : shape}`} style={style} title={name} data-shape={src ? undefined : shape} data-state={state && state !== "idle" ? state : undefined} data-running={state === "thinking" || state === "streaming" || state === "working" ? "true" : undefined}>
      {preset ? <svg className="jg-avatar__robot" viewBox="0 0 36 36" aria-hidden="true"><path d={preset === "robot-shield" ? "M5 5h26v16c0 7-13 13-13 13S5 28 5 21Z" : preset === "robot-square" ? "M4 6h28v25H4Z" : "M8 7h20a5 5 0 0 1 5 5v14a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5V12a5 5 0 0 1 5-5Z"} fill="currentColor" /><path d="M18 2v5M1 16v7m34-7v7" stroke="currentColor" strokeWidth="2" /><rect x="9" y="13" width="18" height="12" rx="4" fill="white" /><circle cx="14" cy="19" r="2" fill="currentColor" /><circle cx="22" cy="19" r="2" fill="currentColor" /></svg> : src ? <img src={src} alt="" /> : (
        <span className="jg-avatar__body">
          <svg className="jg-avatar__shape" viewBox="0 0 36 36" fill="currentColor" aria-hidden="true">{SHAPES[shape]}</svg>
          <span className={`jg-avatar__face jg-avatar__face--${face.eyes}`}><i /><i /></span>
        </span>
      )}
      {primary && <span className="jg-primary-badge" role="img" aria-label="Primary bot" data-primary-agent-id={id}><StarIcon width={8} height={8} /></span>}
      {state && OVERLAY[state] && <span className={`jg-avatar__fx jg-avatar__fx--${OVERLAY[state]}`}><i /><i /><i /></span>}
    </span>
  );
}

/** Pinned art retains the primary marker independently of the unread dot. */
export function SupervisorArt({ id, name, unread = false, primary = false, size = 54, state, preset }: { id: string; name: string; unread?: boolean; primary?: boolean; preset?: string | null; size?: number; state?: AvatarState }) {
  return (
    <span className={`jg-supervisor-art${primary ? " is-primary" : ""}`} style={{ width: size, height: size }}>
      <AgentAvatar id={id} name={name} size={size} state={state} primary={primary} preset={preset} />
      {unread && <span className="jg-supervisor-art__dot" />}
    </span>
  );
}
