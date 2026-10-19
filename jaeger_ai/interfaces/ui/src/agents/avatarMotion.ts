import { useEffect, useRef, useState } from "react";
import type { AgentStatus } from "../api/types";
import type { ChatTurn } from "../chat/host";

/** Avatar life states, modelled on the reference app's lifecycle states (spec:
 * jaeger-shots/specs/avatar-motion.md). The motion itself is our own CSS (agents.css). */
export type AvatarState =
  | "idle" | "thinking" | "streaming" | "working" | "waiting" | "blocked"
  | "finished" | "failed" | "notifying" | "spawning";

/** One-shot states and how long they play before settling back to the steady state. */
export const ONE_SHOT_MS: Partial<Record<AvatarState, number>> = { finished: 1800, failed: 3000, notifying: 1800 };

/** Steady state for a gateway agent status. */
export function steadyState(status?: AgentStatus): AvatarState {
  switch (status) {
    case "working": return "working";
    case "waiting_approval": return "waiting";
    case "blocked": return "blocked";
    default: return "idle";
  }
}

/** The transient state a status change plays, if any: working→idle finishes, anything→error fails,
 * becoming unread while not busy notifies. */
export function transitionState(prev: { status?: AgentStatus; unread: boolean }, next: { status?: AgentStatus; unread: boolean }): AvatarState | undefined {
  if (next.status === "error" && prev.status !== "error") return "failed";
  if (prev.status === "working" && (next.status === "idle" || next.status === undefined)) return "finished";
  if (next.unread && !prev.unread && steadyState(next.status) === "idle") return "notifying";
  return undefined;
}

/** Live state for a sidebar row or tile: the steady state, with one-shots layered on top for a while. */
export function useAvatarState(status: AgentStatus | undefined, unread: boolean): AvatarState {
  const prev = useRef({ status, unread });
  const [shot, setShot] = useState<AvatarState | undefined>();
  useEffect(() => {
    const t = transitionState(prev.current, { status, unread });
    prev.current = { status, unread };
    if (!t) return;
    setShot(t);
    const timer = setTimeout(() => setShot(undefined), ONE_SHOT_MS[t] ?? 0);
    return () => clearTimeout(timer);
  }, [status, unread]);
  return shot ?? steadyState(status);
}

/** The in-chat progress avatar: thinking while reasoning, streaming while text arrives, working while
 * a tool runs or another agent has the turn, waiting when it needs the user. */
export function turnAvatarState(turn: Pick<ChatTurn, "parts">): AvatarState {
  const parts = turn.parts;
  if (parts.some((p) => p.kind === "confirmation" || (p.kind === "toolInvocation" && p.state === "waitingForConfirmation"))) return "waiting";
  const last = parts[parts.length - 1];
  if (!last) return "thinking";
  if (last.kind === "thinking") return last.durationMs === undefined ? "thinking" : "working";
  if (last.kind === "markdownContent") return "streaming";
  return "working";
}
