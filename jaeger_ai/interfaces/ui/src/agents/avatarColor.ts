/* Deterministic avatar color per agent, from the Jaeger avatar tokens (tokens.jaeger.css;
 * no literals here). The same id always gets the same hue. */
export const AVATAR_PALETTE = [
  "var(--jg-avatar-red)",
  "var(--jg-avatar-green)",
  "var(--jg-avatar-purple)",
  "var(--jg-avatar-pink)",
  "var(--jg-avatar-teal)",
  "var(--jg-avatar-brown)",
  "var(--jg-avatar-blue)",
  "var(--jg-avatar-orange)",
] as const;

/** The supervisor keeps the red of its pinned tile (SupervisorArt) everywhere. */
const LEAD_AGENT_ID = "native:jaeger";

/** FNV-1a with a final avalanche mix, so similar ids spread across the palette. */
export function avatarColor(id: string): string {
  if (id === LEAD_AGENT_ID) return "var(--jg-avatar-red)";
  let h = 2166136261;
  for (let i = 0; i < id.length; i += 1) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  h ^= h >>> 16;
  h = Math.imul(h, 2246822507);
  h ^= h >>> 13;
  return AVATAR_PALETTE[(h >>> 0) % AVATAR_PALETTE.length];
}

/** Avatar silhouettes, drawn fresh for Jaeger (36-unit box). The supervisor alone is a squircle. */
export const AVATAR_SHAPES = ["circle", "blob", "hexagon", "cloud", "pill"] as const;
export type AvatarShape = (typeof AVATAR_SHAPES)[number] | "squircle";

/** FNV-1a over a salted key plus an avalanche mix: one independent draw per trait. */
function draw(id: string, salt: string): number {
  const key = `${salt}:${id}`;
  let h = 2166136261;
  for (let i = 0; i < key.length; i += 1) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  h ^= h >>> 15;
  h = Math.imul(h, 2246822519);
  h ^= h >>> 13;
  h = Math.imul(h, 3266489917);
  h ^= h >>> 16;
  return h >>> 0;
}
const pick = <T,>(id: string, salt: string, from: readonly T[]): T => from[draw(id, salt) % from.length];

/** Shape by a salted hash of the id (independent of the color). */
export function avatarShape(id: string): AvatarShape {
  if (id === LEAD_AGENT_ID) return "squircle";
  return pick(id, "shape", AVATAR_SHAPES);
}

/** A face: where the two eyes look (offsets in % of the avatar), how the pair tilts, the eye
 * form, and a small turn of the whole silhouette, so a roster reads as distinct characters. */
export interface AvatarFace { dx: number; dy: number; tilt: number; eyes: "tall" | "wide"; spin: number }

export function avatarFace(id: string, shape: AvatarShape = avatarShape(id)): AvatarFace {
  if (id === LEAD_AGENT_ID) return { dx: 4, dy: 6, tilt: 0, eyes: "tall", spin: -24 };
  return {
    dx: pick(id, "gaze-x", [-12, -6, 0, 0, 4, 10, 16]),
    dy: pick(id, "gaze-y", [-8, -6, -2, 2, 6]),
    tilt: pick(id, "tilt", [0, 0, 0, -24, 18]),
    eyes: pick(id, "eyes", ["tall", "tall", "tall", "tall", "tall", "wide"] as const),
    spin: shape === "circle" ? 0 : pick(id, "spin", [-14, -8, 0, 6, 12]),
  };
}
