/* Pinned agents (Jenkins Robotics, 2026-10-18, original): specialists dragged up beside the supervisor's
 * tile. A per-device UI preference in localStorage; the supervisor is always first and never listed. */
import type { SidebarRow } from "./agentsLogic";

export const PINS_KEY = "jaeger.ui.pinned-agents";
export const MAX_PINS = 8;
/** Drag payload type for an agent row or tile. */
export const AGENT_DRAG_TYPE = "application/x-jaeger-agent";

export function loadPins(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PINS_KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string").slice(0, MAX_PINS) : [];
  } catch {
    return [];
  }
}

export function savePins(pins: string[]) {
  try { localStorage.setItem(PINS_KEY, JSON.stringify(pins)); } catch { /* storage unavailable */ }
}

/** Pin `id` at `index` (end by default); pinning an already pinned agent moves it. */
export function pin(pins: string[], id: string, index = pins.length): string[] {
  const rest = pins.filter((p) => p !== id);
  const at = Math.max(0, Math.min(index, rest.length));
  return [...rest.slice(0, at), id, ...rest.slice(at)].slice(0, MAX_PINS);
}

export const unpin = (pins: string[], id: string) => pins.filter((p) => p !== id);

/** Specialists split into pinned tiles (pin order; unknown ids skipped) and the remaining list. */
export function splitPinned(specialists: SidebarRow[], pins: string[]): { pinned: SidebarRow[]; rest: SidebarRow[] } {
  const byId = new Map(specialists.map((r) => [r.agent.id, r]));
  const pinned = pins.map((id) => byId.get(id)).filter((r): r is SidebarRow => Boolean(r));
  const pinnedIds = new Set(pinned.map((r) => r.agent.id));
  return { pinned, rest: specialists.filter((r) => !pinnedIds.has(r.agent.id)) };
}
