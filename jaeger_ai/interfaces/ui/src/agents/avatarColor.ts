/* Deterministic avatar color per agent, drawn from existing Aether palette
 * tokens (no new literals). The same id always gets the same hue. */
export const AVATAR_PALETTE = [
  "var(--aether-color-error)",
  "var(--aether-color-accent)",
  "var(--aether-color-joint)",
  "var(--aether-color-ok)",
  "var(--aether-color-warn)",
  "var(--aether-color-hardware)",
  "var(--aether-color-part)",
] as const;

/** The supervisor keeps the red of its pinned tile (SupervisorArt) everywhere. */
const LEAD_AGENT_ID = "native:jaeger";

/** FNV-1a with a final avalanche mix, so similar ids spread across the palette. */
export function avatarColor(id: string): string {
  if (id === LEAD_AGENT_ID) return "var(--aether-color-error)";
  let h = 2166136261;
  for (let i = 0; i < id.length; i += 1) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  h ^= h >>> 16;
  h = Math.imul(h, 2246822507);
  h ^= h >>> 13;
  return AVATAR_PALETTE[(h >>> 0) % AVATAR_PALETTE.length];
}
