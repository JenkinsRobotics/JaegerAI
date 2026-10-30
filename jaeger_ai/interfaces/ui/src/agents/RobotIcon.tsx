/**
 * RobotIcon (unified UI, 2026-10-30, original): a small single-colour robot per specialist.
 * The head variant comes from a hash of the agent id (stable across devices), the colour from
 * avatarColor (the same agent colours the sidebar uses). A status ring shows working / approval.
 * Per-device choice between robots and the classic silhouettes: useRobotIcons().
 */
import { useEffect, useState, type ReactElement } from "react";
import { avatarColor } from "./avatarColor";

export const ROBOT_ICONS_KEY = "jaeger.ui.robot-icons";
const EVENT = "jaeger:robot-icons";
export const ROBOT_VARIANTS = ["dome", "box", "antenna", "visor"] as const;
export type RobotVariant = (typeof ROBOT_VARIANTS)[number];

export function robotVariant(id: string): RobotVariant {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return ROBOT_VARIANTS[h % ROBOT_VARIANTS.length];
}

export function useRobotIcons(): [boolean, (on: boolean) => void] {
  const read = () => { try { return localStorage.getItem(ROBOT_ICONS_KEY) !== "0"; } catch { return true; } };
  const [on, setOn] = useState(read);
  useEffect(() => { const sync = () => setOn(read()); addEventListener(EVENT, sync); return () => removeEventListener(EVENT, sync); }, []);
  return [on, (next) => { try { localStorage.setItem(ROBOT_ICONS_KEY, next ? "1" : "0"); } catch { /* */ } dispatchEvent(new Event(EVENT)); }];
}

const HEADS: Record<RobotVariant, ReactElement> = {
  dome: <path d="M5 13a7 7 0 0 1 14 0v4a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z" />,
  box: <rect x="4.5" y="7" width="15" height="12" rx="2.5" />,
  antenna: <><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 8V4.5" strokeWidth="1.6" stroke="currentColor" /><circle cx="12" cy="4" r="1.4" /></>,
  visor: <><rect x="4" y="7.5" width="16" height="11.5" rx="5.75" /></>,
};

export function RobotIcon({ id, name, size = 28, status }: { id: string; name: string; size?: number; status?: string }) {
  const variant = robotVariant(id);
  const ring = status === "working" ? "working" : status === "waiting_approval" ? "approval" : status === "error" || status === "blocked" ? "error" : undefined;
  return (
    <span className="jg-robot" data-variant={variant} data-ring={ring} title={name} role="img" aria-label={name}
      style={{ width: size, height: size, color: avatarColor(id) }}>
      <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
        <g fill="currentColor">{HEADS[variant]}</g>
        <g className="jg-robot__face">
          {variant === "visor" ? <rect x="7" y="11" width="10" height="3" rx="1.5" /> : <><circle cx="9.3" cy="13.2" r="1.35" /><circle cx="14.7" cy="13.2" r="1.35" /></>}
        </g>
      </svg>
    </span>
  );
}
