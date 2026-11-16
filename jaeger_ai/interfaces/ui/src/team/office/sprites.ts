/* Original pixel art for the Team office, drawn in code (no image assets).
 * One world pixel = one art pixel; the canvas is scaled up with smoothing off.
 * Environment colours come from Jaeger theme tokens (office.css), so the
 * office follows light/dark; people get stable colours from their avatar seed. */
import { seedHue } from "../AgentAvatar";
import type { Mood } from "./officeState";

export const CELL_W = 76, CELL_H = 66, MARGIN = 8, WALL_H = 38, BREAK_H = 54;

export const PALETTE_KEYS = ["wall", "wall-trim", "floor-a", "floor-b", "desk-top", "desk-front", "desk-edge", "chair", "monitor",
  "screen-off", "screen-on", "screen-code", "screen-warn", "screen-err", "glow", "glow-warn", "glow-err", "outline", "sky-day",
  "sky-night", "frame", "plant", "plant-dark", "pot", "mug", "steam", "warn", "err", "dim", "paper", "accent", "rug", "shadow"] as const;
export type PaletteKey = typeof PALETTE_KEYS[number];
export type Palette = Record<PaletteKey, string>;

export interface DeskGeom { x0: number; y0: number; cx: number }
export const deskGeom = (i: number, cols: number): DeskGeom => {
  const x0 = MARGIN + (i % cols) * CELL_W, y0 = WALL_H + Math.floor(i / cols) * CELL_H;
  return { x0, y0, cx: x0 + 38 };
};
export const worldSize = (n: number, cols: number) => ({ w: MARGIN * 2 + cols * CELL_W, h: WALL_H + Math.max(1, Math.ceil(n / cols)) * CELL_H + BREAK_H });
/** Feet position when seated, standing beside a desk (hand-off visit), and in the aisle under it. */
export const seatPoint = (d: DeskGeom) => ({ x: d.cx, y: d.y0 + 40 });
export const visitPoint = (d: DeskGeom) => ({ x: d.x0 + 70, y: d.y0 + 50 });
export const aisleY = (d: DeskGeom) => d.y0 + 60;
export const coffeePoint = (w: number, h: number, slot: number) => ({ x: w - MARGIN - 44 - (slot % 3) * 10, y: h - 10 - (slot % 2) * 4 });

const SKIN = ["#f1c7a5", "#e0ac84", "#c68a5e", "#9a6440", "#6e4529", "#f6d6bd"];
const HAIR = ["#2a1d16", "#4a2f1d", "#7a4b26", "#c9a15a", "#1d1d24", "#8c8c94", "#a3442c", "#3b2a4a"];

export interface Look { skin: string; hair: string; shirt: string; shirtDark: string; pants: string; hairStyle: number }
export function lookFor(seed: string): Look {
  const [a, b] = seedHue(seed);
  let h = 0; for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return {
    skin: SKIN[h % SKIN.length], hair: HAIR[(h >> 3) % HAIR.length], hairStyle: (h >> 7) % 3,
    shirt: `hsl(${a} 58% 52%)`, shirtDark: `hsl(${a} 52% 38%)`, pants: `hsl(${b} 22% 26%)`,
  };
}

type Ctx = CanvasRenderingContext2D;
const r = (c: Ctx, fill: string, x: number, y: number, w: number, h: number) => { c.fillStyle = fill; c.fillRect(Math.round(x), Math.round(y), w, h); };

export function drawRoom(c: Ctx, p: Palette, w: number, h: number, night: boolean, frame: number, rows: number) {
  // Floor: two-tone tiles, with a rug under each row of desks.
  for (let y = WALL_H; y < h; y += 8) for (let x = 0; x < w; x += 8) r(c, ((x + y) / 8) % 2 ? p["floor-a"] : p["floor-b"], x, y, 8, 8);
  for (let row = 0; row < rows; row++) r(c, p.rug, MARGIN - 2, WALL_H + row * CELL_H + 46, w - 2 * MARGIN + 4, 10);
  // Back wall with windows, a clock and a status board.
  r(c, p.wall, 0, 0, w, WALL_H); r(c, p["wall-trim"], 0, WALL_H - 4, w, 4); r(c, p.outline, 0, WALL_H, w, 1);
  const panes = Math.max(2, Math.floor((w - 70) / 56));
  for (let i = 0; i < panes; i++) {
    const x = 14 + i * 56;
    r(c, p.frame, x, 7, 34, 22); r(c, night ? p["sky-night"] : p["sky-day"], x + 2, 9, 30, 18); r(c, p.frame, x + 16, 9, 2, 18); r(c, p.frame, x + 2, 17, 30, 1);
    if (night) { r(c, p.paper, x + 6, 12, 1, 1); r(c, p.paper, x + 25, 20, 1, 1); r(c, p.paper, x + 22, 11, 2, 2); }
    else { r(c, p.paper, x + 5, 12, 6, 2); r(c, p.paper, x + 22, 21, 7, 2); }
  }
  const cx = w - 30; // clock
  r(c, p.outline, cx - 6, 8, 13, 13); r(c, p.paper, cx - 5, 9, 11, 11); r(c, p.outline, cx, 10, 1, 5); r(c, p.outline, cx, 14, 4, 1);
  r(c, p.accent, cx - 1, 14, 2, 2);
  // Break area along the bottom: counter, coffee machine, water cooler, sofa, plant.
  const by = h - BREAK_H;
  r(c, p["wall-trim"], 0, by, w, 2);
  r(c, p["desk-front"], w - MARGIN - 70, by + 10, 70, 14); r(c, p["desk-top"], w - MARGIN - 70, by + 8, 70, 3);
  const mx = w - MARGIN - 28; r(c, p.monitor, mx, by - 4, 14, 14); r(c, p.outline, mx + 3, by + 3, 8, 4); r(c, p.err, mx + 10, by - 1, 2, 2);
  if (frame % 8 < 4) { r(c, p.steam, mx + 5, by - 8, 1, 2); r(c, p.steam, mx + 8, by - 10, 1, 2); }
  r(c, p.mug, mx - 8, by + 4, 4, 4);
  const wx = w - MARGIN - 62; r(c, p["sky-day"], wx, by - 6, 8, 8); r(c, p.monitor, wx - 1, by + 2, 10, 12);
  r(c, p.chair, MARGIN + 4, by + 16, 40, 12); r(c, p.chair, MARGIN + 4, by + 10, 40, 6); r(c, p.outline, MARGIN + 4, by + 28, 40, 1);
  plant(c, p, MARGIN + 52, by + 8); plant(c, p, w - MARGIN - 8, 22);
}

function plant(c: Ctx, p: Palette, x: number, y: number) {
  r(c, p.plant, x - 3, y - 8, 7, 7); r(c, p["plant-dark"], x - 5, y - 4, 4, 4); r(c, p["plant-dark"], x + 2, y - 5, 4, 4);
  r(c, p.pot, x - 3, y, 7, 7); r(c, p.outline, x - 3, y + 7, 7, 1);
}

function screenFor(p: Palette, mood: Mood) {
  return mood === "error" ? p["screen-err"] : mood === "approval" ? p["screen-warn"] : mood === "offline" ? p["screen-off"]
    : mood === "idle" || mood === "handoff" ? p["screen-off"] : p["screen-on"];
}

/** A desk with its monitor; `seated` draws the worker in the chair (typing when working). */
export function drawDesk(c: Ctx, p: Palette, d: DeskGeom, mood: Mood, look: Look | null, seated: boolean, frame: number, lead: boolean, motion: boolean) {
  const { x0, y0, cx } = d;
  const screen = screenFor(p, mood);
  const lit = mood === "working" || mood === "queued" || mood === "approval" || mood === "error";
  if (lit) { c.globalAlpha = 0.5; r(c, mood === "error" ? p["glow-err"] : mood === "approval" ? p["glow-warn"] : p.glow, x0 + 8, y0 + 12, 36, 26); c.globalAlpha = 1; }
  // Chair back.
  r(c, p.chair, cx - 8, y0 + 16, 16, 18); r(c, p.outline, cx - 8, y0 + 16, 16, 1);
  if (seated && look) seatedPerson(c, p, cx, y0 + 10, look, mood, frame, motion);
  // Desk.
  r(c, p["desk-top"], x0 + 10, y0 + 31, 56, 5); r(c, p["desk-edge"], x0 + 10, y0 + 36, 56, 1); r(c, p["desk-front"], x0 + 12, y0 + 37, 52, 11);
  r(c, p["desk-edge"], x0 + 36, y0 + 39, 4, 1); r(c, p.outline, x0 + 12, y0 + 48, 52, 1);
  // Monitor (faces the room at an angle so its screen shows state).
  r(c, p.monitor, x0 + 13, y0 + 18, 17, 13); r(c, screen, x0 + 14, y0 + 19, 15, 10); r(c, p.monitor, x0 + 20, y0 + 31, 3, 1);
  if (mood === "working" || mood === "queued") {
    const scroll = motion && mood === "working" ? frame % 4 : 0;
    for (let i = 0; i < 4; i++) { const len = 3 + ((i + scroll) * 5) % 9; r(c, p["screen-code"], x0 + 16 + (i % 2) * 2, y0 + 20 + i * 2, Math.min(len, 11), 1); }
  } else if (mood === "approval") { r(c, p.outline, x0 + 21, y0 + 20, 1, 5); r(c, p.outline, x0 + 21, y0 + 26, 1, 1); }
  else if (mood === "error") { for (let i = 0; i < 5; i++) { r(c, p.paper, x0 + 19 + i, y0 + 21 + i, 1, 1); r(c, p.paper, x0 + 23 - i, y0 + 21 + i, 1, 1); } }
  // Keyboard, papers, mug.
  r(c, p.monitor, cx - 6, y0 + 32, 12, 2);
  r(c, p.paper, x0 + 50, y0 + 30, 7, 2); r(c, p.paper, x0 + 51, y0 + 29, 6, 1);
  if (mood === "idle") { r(c, p.mug, x0 + 46, y0 + 27, 4, 4); r(c, p.mug, x0 + 50, y0 + 28, 1, 2); if (!motion || frame % 6 < 3) { r(c, p.steam, x0 + 47, y0 + 24, 1, 2); r(c, p.steam, x0 + 48, y0 + 22, 1, 2); } }
  if (lead) { r(c, p.warn, x0 + 58, y0 + 27, 4, 4); r(c, p.outline, x0 + 59, y0 + 31, 2, 1); }
}

function head(c: Ctx, p: Palette, x: number, y: number, look: Look) {
  r(c, look.skin, x - 4, y, 8, 8);
  r(c, look.hair, x - 4, y - 1, 8, 3);
  if (look.hairStyle === 0) { r(c, look.hair, x - 5, y, 1, 4); r(c, look.hair, x + 4, y, 1, 4); }
  else if (look.hairStyle === 1) r(c, look.hair, x - 4, y + 2, 2, 2);
  else { r(c, look.hair, x - 5, y + 1, 1, 6); r(c, look.hair, x + 4, y + 1, 1, 6); }
  r(c, p.outline, x - 2, y + 4, 1, 1); r(c, p.outline, x + 1, y + 4, 1, 1);
}

function seatedPerson(c: Ctx, p: Palette, x: number, y: number, look: Look, mood: Mood, frame: number, motion: boolean) {
  head(c, p, x, y, look);
  r(c, look.shirt, x - 6, y + 8, 12, 13); r(c, look.shirtDark, x - 6, y + 19, 12, 2);
  const typing = mood === "working" && motion;
  const lUp = typing && frame % 2 === 0 ? 1 : 0, rUp = typing && frame % 2 === 1 ? 1 : 0;
  r(c, look.shirtDark, x - 8, y + 10, 2, 10 - lUp); r(c, look.skin, x - 7, y + 20 - lUp, 3, 2);
  if (mood === "approval") {
    // Raised hand and a "!" sign.
    const bob = motion && frame % 4 < 2 ? 1 : 0;
    r(c, look.shirtDark, x + 6, y - 4 - bob, 2, 14); r(c, look.skin, x + 6, y - 7 - bob, 3, 3);
    attention(c, p, x + 12, y - 16 - bob, p.warn);
  } else {
    r(c, look.shirtDark, x + 6, y + 10, 2, 10 - rUp); r(c, look.skin, x + 4, y + 20 - rUp, 3, 2);
  }
  if (mood === "error") cross(c, p, x - 3, y - 12);
}

export function attention(c: Ctx, p: Palette, x: number, y: number, fill: string) {
  r(c, p.outline, x - 1, y - 1, 9, 11); r(c, fill, x, y, 7, 9); r(c, p.outline, x + 3, y + 1, 1, 5); r(c, p.outline, x + 3, y + 7, 1, 1);
}
function cross(c: Ctx, p: Palette, x: number, y: number) {
  r(c, p.outline, x - 1, y - 1, 9, 9); r(c, p.err, x, y, 7, 7);
  for (let i = 0; i < 5; i++) { r(c, p.paper, x + 1 + i, y + 1 + i, 1, 1); r(c, p.paper, x + 5 - i, y + 1 + i, 1, 1); }
}

/** A standing or walking worker, feet at (x, y). */
export function drawWalker(c: Ctx, p: Palette, x: number, y: number, look: Look, frame: number, moving: boolean, carrying: "mug" | "paper" | null) {
  x = Math.round(x); y = Math.round(y);
  c.globalAlpha = 0.35; r(c, p.shadow, x - 5, y - 1, 10, 2); c.globalAlpha = 1;
  const step = moving ? frame % 2 : 0;
  r(c, look.pants, x - 3, y - 6, 2, 6 - step); r(c, look.pants, x + 1, y - 6, 2, 6 - (1 - step) * (moving ? 1 : 0));
  r(c, p.outline, x - 3, y - (step ? 1 : 0) - 1, 2, 1); r(c, p.outline, x + 1, y - (moving && !step ? 1 : 0) - 1, 2, 1);
  r(c, look.shirt, x - 5, y - 15, 10, 9); r(c, look.shirtDark, x - 5, y - 7, 10, 1);
  r(c, look.shirtDark, x - 7, y - 14 + (moving && step ? 1 : 0), 2, 7); r(c, look.shirtDark, x + 5, y - 14 + (moving && !step ? 1 : 0), 2, 7);
  if (carrying === "mug") { r(c, p.mug, x + 6, y - 9, 3, 3); }
  if (carrying === "paper") { r(c, p.paper, x + 5, y - 11, 5, 6); r(c, p.outline, x + 6, y - 9, 3, 1); }
  head(c, p, x, y - 23, look);
}

export function dimRect(c: Ctx, p: Palette, x: number, y: number, w: number, h: number) { c.globalAlpha = 0.55; r(c, p.dim, x, y, w, h); c.globalAlpha = 1; }
