/**
 * Crisp 16x24 pixel-art character, pet, bubble & furniture renderer.
 * Speech/permission/heart bubble matrices and offscreen sprite-caching pattern
 * adapted from pixel-agents-hq/pixel-agents (MIT).
 */
import { Direction, TILE_SIZE, type FurnitureKind, type OfficeAgentActivity } from "./types";

export interface CharacterPalette {
  skin: string;
  skinShade: string;
  hair: string;
  hairLight: string;
  shirt: string;
  shirtShade: string;
  pants: string;
  shoes: string;
  accent: string;
}

export const CHARACTER_PALETTES: readonly CharacterPalette[] = [
  // 0: Jaeger Primary (Cobalt jacket, warm cream skin, dark hair, cyan visor accent)
  { skin: "#f4c9a0", skinShade: "#d9a479", hair: "#1f2937", hairLight: "#374151", shirt: "#2563eb", shirtShade: "#1d4ed8", pants: "#1e293b", shoes: "#0f172a", accent: "#38bdf8" },
  // 1: Producer (Emerald blazer, warm tan, chestnut hair)
  { skin: "#e0ac7c", skinShade: "#bd8759", hair: "#4a2c1d", hairLight: "#6b3e28", shirt: "#059669", shirtShade: "#047857", pants: "#1f2937", shoes: "#111827", accent: "#34d399" },
  // 2: Editor (Violet hoodie, fair skin, auburn hair)
  { skin: "#f8d5b8", skinShade: "#dfb08e", hair: "#8b3a2b", hairLight: "#b4533c", shirt: "#7c3aed", shirtShade: "#6d28d9", pants: "#312e81", shoes: "#1e1b4b", accent: "#c084fc" },
  // 3: Researcher (Amber cardigan, deep brown skin, black hair)
  { skin: "#9a6342", skinShade: "#75462b", hair: "#171717", hairLight: "#333333", shirt: "#d97706", shirtShade: "#b45309", pants: "#292524", shoes: "#1c1917", accent: "#fbbf24" },
  // 4: Engineer / Subagent (Teal tech tee, medium skin, blonde hair)
  { skin: "#f1c295", skinShade: "#d09d6e", hair: "#d4a437", hairLight: "#eac463", shirt: "#0d9488", shirtShade: "#0f766e", pants: "#1e293b", shoes: "#0f172a", accent: "#2dd4bf" },
  // 5: Writer (Rose sweater, warm ivory, dark indigo hair)
  { skin: "#f6d0b1", skinShade: "#d7a885", hair: "#27273f", hairLight: "#3f3f66", shirt: "#e11d48", shirtShade: "#be123c", pants: "#334155", shoes: "#1e293b", accent: "#fb7185" },
  // 6: Director (Slate turtleneck, olive skin, silver-streaked hair)
  { skin: "#d9a77a", skinShade: "#b68356", hair: "#475569", hairLight: "#94a3b8", shirt: "#334155", shirtShade: "#1e293b", pants: "#0f172a", shoes: "#020617", accent: "#60a5fa" },
  // 7: Ops / Hardware (Orange vest, tan skin, dark brown hair)
  { skin: "#c98f61", skinShade: "#a56e43", hair: "#2b1d14", hairLight: "#473123", shirt: "#ea580c", shirtShade: "#c2410c", pants: "#1f2937", shoes: "#111827", accent: "#fb923c" },
];

// Pixel-art speech bubbles (11x11) adapted from pixel-agents bubble-*.json (MIT)
const BUBBLE_OUTLINE = "#1e293b";
const BUBBLE_FILL = "#f8fafc";

export function drawPixelBubble(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  kind: "permission" | "waiting" | "heart" | "coffee" | "thinking",
  frameTick: number,
): void {
  const bx = Math.round(x - 6);
  const by = Math.round(y - 12);
  // Rounded bubble box
  ctx.fillStyle = BUBBLE_OUTLINE;
  ctx.fillRect(bx + 1, by, 10, 1);
  ctx.fillRect(bx, by + 1, 12, 7);
  ctx.fillRect(bx + 1, by + 8, 10, 1);
  ctx.fillRect(bx + 5, by + 9, 2, 2);

  ctx.fillStyle = BUBBLE_FILL;
  ctx.fillRect(bx + 1, by + 1, 10, 7);
  ctx.fillRect(bx + 5, by + 8, 2, 1);

  if (kind === "permission") {
    const pulse = Math.floor(frameTick / 15) % 2 === 0 ? "#f59e0b" : "#d97706";
    ctx.fillStyle = pulse;
    ctx.fillRect(bx + 5, by + 2, 2, 3);
    ctx.fillRect(bx + 5, by + 6, 2, 1);
  } else if (kind === "waiting") {
    ctx.fillStyle = "#10b981";
    ctx.fillRect(bx + 3, by + 4, 1, 2);
    ctx.fillRect(bx + 4, by + 5, 1, 2);
    ctx.fillRect(bx + 5, by + 4, 1, 2);
    ctx.fillRect(bx + 6, by + 3, 1, 2);
    ctx.fillRect(bx + 7, by + 2, 1, 2);
  } else if (kind === "heart") {
    ctx.fillStyle = "#ef4444";
    ctx.fillRect(bx + 3, by + 3, 2, 2);
    ctx.fillRect(bx + 7, by + 3, 2, 2);
    ctx.fillRect(bx + 4, by + 4, 4, 2);
    ctx.fillRect(bx + 5, by + 6, 2, 1);
  } else if (kind === "coffee") {
    ctx.fillStyle = "#78350f";
    ctx.fillRect(bx + 4, by + 4, 4, 3);
    ctx.fillStyle = "#94a3b8";
    const s = Math.floor(frameTick / 18) % 2;
    ctx.fillRect(bx + 5 + s, by + 2, 1, 1);
    ctx.fillRect(bx + 7 - s, by + 2, 1, 1);
  } else {
    // Animated thinking dots
    const active = Math.floor(frameTick / 14) % 3;
    for (let i = 0; i < 3; i++) {
      ctx.fillStyle = i === active ? "#3b82f6" : "#94a3b8";
      ctx.fillRect(bx + 3 + i * 2.5, by + 4, 1.5, 1.5);
    }
  }
}

export function drawPixelCharacter(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  paletteIdx: number,
  dir: Direction,
  pose: "stand" | "walk" | "type" | "read",
  frame: number,
  blinking: boolean,
  selected: boolean,
  isPrimary: boolean,
): void {
  const pal = CHARACTER_PALETTES[paletteIdx % CHARACTER_PALETTES.length];
  const x = Math.round(cx - 8);
  const bob = pose === "walk" ? (frame % 2 === 1 ? -1 : 0) : 0;
  const seatOffset = pose === "type" || pose === "read" ? 2 : 0;
  const y = Math.round(cy - 20 + bob + seatOffset);

  // Soft ground shadow
  ctx.fillStyle = "rgba(15, 23, 42, 0.28)";
  ctx.fillRect(x + 3, Math.round(cy - 2), 10, 3);

  // Selection ring under feet
  if (selected) {
    ctx.strokeStyle = pal.accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 1.5, Math.round(cy - 3.5), 13, 5);
  }

  // Legs / Shoes
  const legStep = pose === "walk" ? (frame === 1 ? 1 : frame === 3 ? -1 : 0) : 0;
  ctx.fillStyle = pal.pants;
  if (pose === "type" || pose === "read") {
    ctx.fillRect(x + 4, y + 14, 8, 3);
    ctx.fillStyle = pal.shoes;
    ctx.fillRect(x + 4, y + 17, 3, 2);
    ctx.fillRect(x + 9, y + 17, 3, 2);
  } else {
    ctx.fillRect(x + 4, y + 14, 3, 4 + (legStep > 0 ? 1 : 0));
    ctx.fillRect(x + 9, y + 14, 3, 4 + (legStep < 0 ? 1 : 0));
    ctx.fillStyle = pal.shoes;
    ctx.fillRect(x + 4, y + 18 + (legStep > 0 ? 1 : 0), 3, 2);
    ctx.fillRect(x + 9, y + 18 + (legStep < 0 ? 1 : 0), 3, 2);
  }

  // Torso / Jacket
  ctx.fillStyle = pal.shirt;
  ctx.fillRect(x + 4, y + 8, 8, 6);
  ctx.fillStyle = pal.shirtShade;
  ctx.fillRect(x + 4, y + 12, 8, 2);
  if (isPrimary) {
    // Jaeger signature collar/chest badge glow
    ctx.fillStyle = pal.accent;
    ctx.fillRect(x + 7, y + 9, 2, 2);
  }

  // Arms (animated for typing / reading / walking)
  ctx.fillStyle = pal.shirt;
  if (pose === "type") {
    const tShift = frame % 2 === 0 ? 0 : -1;
    ctx.fillRect(x + 2, y + 9 + tShift, 2, 3);
    ctx.fillRect(x + 12, y + 9 - tShift, 2, 3);
    ctx.fillStyle = pal.skin;
    ctx.fillRect(x + 2, y + 11 + tShift, 2, 1);
    ctx.fillRect(x + 12, y + 11 - tShift, 2, 1);
  } else if (pose === "read") {
    ctx.fillRect(x + 2, y + 9, 2, 3);
    ctx.fillRect(x + 12, y + 9, 2, 3);
    // Glowing tablet/book held in hands
    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(x + 5, y + 10, 6, 4);
    ctx.fillStyle = pal.accent;
    ctx.fillRect(x + 6, y + 11, 4, 2);
  } else {
    ctx.fillRect(x + 2, y + 9 - legStep, 2, 4);
    ctx.fillRect(x + 12, y + 9 + legStep, 2, 4);
    ctx.fillStyle = pal.skin;
    ctx.fillRect(x + 2, y + 13 - legStep, 2, 1);
    ctx.fillRect(x + 12, y + 13 + legStep, 2, 1);
  }

  // Head
  ctx.fillStyle = pal.skin;
  ctx.fillRect(x + 4, y + 2, 8, 6);
  ctx.fillStyle = pal.skinShade;
  ctx.fillRect(x + 4, y + 7, 8, 1);

  // Hair cap & directional face
  ctx.fillStyle = pal.hair;
  ctx.fillRect(x + 3, y + 1, 10, 3);
  ctx.fillStyle = pal.hairLight;
  ctx.fillRect(x + 5, y + 1, 5, 1);

  if (dir === Direction.UP) {
    // Back of head covered by hair
    ctx.fillStyle = pal.hair;
    ctx.fillRect(x + 4, y + 3, 8, 4);
  } else {
    // Side hair framing
    ctx.fillStyle = pal.hair;
    ctx.fillRect(x + 3, y + 3, 1, 3);
    ctx.fillRect(x + 12, y + 3, 1, 3);
    // Eyes (blink naturally)
    if (!blinking) {
      ctx.fillStyle = "#0f172a";
      if (dir === Direction.LEFT) {
        ctx.fillRect(x + 5, y + 5, 1, 1);
        ctx.fillRect(x + 8, y + 5, 1, 1);
      } else if (dir === Direction.RIGHT) {
        ctx.fillRect(x + 7, y + 5, 1, 1);
        ctx.fillRect(x + 10, y + 5, 1, 1);
      } else {
        ctx.fillRect(x + 5, y + 5, 1, 1);
        ctx.fillRect(x + 10, y + 5, 1, 1);
      }
    }
  }
}

export function drawOfficePet(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  dir: Direction,
  frame: number,
  sleeping: boolean,
): void {
  const x = Math.round(cx - 5);
  const y = Math.round(cy - 8);
  ctx.fillStyle = "rgba(15, 23, 42, 0.22)";
  ctx.fillRect(x + 1, Math.round(cy - 1), 8, 2);

  // Ginger office cat ("Pixel")
  ctx.fillStyle = "#f97316";
  if (sleeping) {
    ctx.fillRect(x + 1, y + 4, 8, 4);
    ctx.fillStyle = "#fed7aa";
    ctx.fillRect(x + 3, y + 5, 4, 2);
    return;
  }
  ctx.fillRect(x + 2, y + 3, 6, 4);
  // Ears
  const headX = dir === Direction.LEFT ? x + 1 : x + 5;
  ctx.fillRect(headX, y + 1, 4, 3);
  ctx.fillStyle = "#ea580c";
  ctx.fillRect(headX, y, 1, 1);
  ctx.fillRect(headX + 3, y, 1, 1);
  // Tail wag
  const wag = frame % 2 === 0 ? 0 : -1;
  const tailX = dir === Direction.LEFT ? x + 8 : x + 1;
  ctx.fillRect(tailX, y + 2 + wag, 1, 3);
  // Paws
  ctx.fillStyle = "#fed7aa";
  ctx.fillRect(x + 2 + (frame % 2), y + 7, 2, 1);
  ctx.fillRect(x + 6 - (frame % 2), y + 7, 2, 1);
}

export function drawFurnitureItem(
  ctx: CanvasRenderingContext2D,
  kind: FurnitureKind,
  col: number,
  row: number,
  wTiles: number,
  hTiles: number,
  frameTick: number,
  deskActive: OfficeAgentActivity | null,
  estopActive: boolean,
): void {
  const x = col * TILE_SIZE;
  const y = row * TILE_SIZE;
  const w = wTiles * TILE_SIZE;
  const h = hTiles * TILE_SIZE;

  switch (kind) {
    case "window": {
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(x + 1, y + 2, w - 2, h - 3);
      // Sky gradient bands
      ctx.fillStyle = "#38bdf8";
      ctx.fillRect(x + 2, y + 3, w - 4, 5);
      ctx.fillStyle = "#7dd3fc";
      ctx.fillRect(x + 2, y + 8, w - 4, 4);
      // Mullions
      ctx.fillStyle = "#334155";
      ctx.fillRect(x + Math.floor(w / 2), y + 2, 1, h - 3);
      ctx.fillRect(x + 2, y + 7, w - 4, 1);
      break;
    }
    case "whiteboard": {
      ctx.fillStyle = "#475569";
      ctx.fillRect(x + 2, y + 2, w - 4, h - 3);
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(x + 3, y + 3, w - 6, h - 5);
      // Colored roadmap bars
      ctx.fillStyle = "#3b82f6";
      ctx.fillRect(x + 6, y + 5, 14, 2);
      ctx.fillStyle = "#10b981";
      ctx.fillRect(x + 6, y + 8, 22, 2);
      ctx.fillStyle = "#f59e0b";
      ctx.fillRect(x + 24, y + 5, 12, 2);
      ctx.fillStyle = "#8b5cf6";
      ctx.fillRect(x + 32, y + 8, 16, 2);
      break;
    }
    case "desk_dual":
    case "desk_single":
    case "desk_edit": {
      // Desk shadow & wood/slate surface
      ctx.fillStyle = "rgba(15, 23, 42, 0.25)";
      ctx.fillRect(x + 1, y + h - 2, w - 2, 3);
      ctx.fillStyle = kind === "desk_edit" ? "#334155" : "#92400e";
      ctx.fillRect(x + 1, y + 2, w - 2, h - 3);
      ctx.fillStyle = kind === "desk_edit" ? "#475569" : "#b45309";
      ctx.fillRect(x + 2, y + 3, w - 4, h - 6);

      // Monitor(s)
      const isLit = !estopActive && (deskActive === "typing" || deskActive === "reading" || deskActive === "thinking");
      const screenColor = estopActive
        ? "#7f1d1d"
        : deskActive === "typing"
          ? "#0ea5e9"
          : deskActive === "reading"
            ? "#10b981"
            : deskActive === "thinking"
              ? "#f59e0b"
              : "#1e293b";

      const monitors = kind === "desk_single" ? [x + 9] : [x + 4, x + 17];
      for (const mx of monitors) {
        ctx.fillStyle = "#0f172a";
        ctx.fillRect(mx, y + 1, 11, 7);
        ctx.fillStyle = screenColor;
        ctx.fillRect(mx + 1, y + 2, 9, 5);
        if (isLit) {
          // Animated code / timeline bars on active screens
          const scroll = Math.floor(frameTick / 12) % 3;
          ctx.fillStyle = "#e0f2fe";
          ctx.fillRect(mx + 2, y + 3 + (scroll % 2), 5, 1);
          ctx.fillRect(mx + 2, y + 5, 7 - scroll, 1);
        }
        // Monitor stand
        ctx.fillStyle = "#334155";
        ctx.fillRect(mx + 4, y + 8, 3, 1);
      }
      // Keyboard
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(x + 9, y + 10, 10, 2);
      // Tiny coffee mug
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(x + w - 6, y + 9, 3, 3);
      break;
    }
    case "chair": {
      ctx.fillStyle = "#334155";
      ctx.fillRect(x + 4, y + 5, 8, 7);
      ctx.fillStyle = "#475569";
      ctx.fillRect(x + 5, y + 6, 6, 5);
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(x + 5, y + 12, 6, 2);
      break;
    }
    case "server_rack": {
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(x + 2, y + 1, w - 4, h - 2);
      ctx.fillStyle = "#1e293b";
      for (let slot = 0; slot < 5; slot++) {
        const sy = y + 3 + slot * 5;
        ctx.fillRect(x + 3, sy, w - 6, 3);
        const blink = (Math.floor(frameTick / 10) + slot) % 3 === 0;
        ctx.fillStyle = estopActive ? "#ef4444" : blink ? "#22c55e" : "#38bdf8";
        ctx.fillRect(x + 4, sy + 1, 2, 1);
        ctx.fillStyle = "#1e293b";
      }
      break;
    }
    case "bookshelf": {
      ctx.fillStyle = "#78350f";
      ctx.fillRect(x + 2, y + 1, w - 4, h - 2);
      const bookColors = ["#ef4444", "#3b82f6", "#f59e0b", "#10b981", "#a855f7"];
      for (let shelf = 0; shelf < 4; shelf++) {
        const sy = y + 3 + shelf * 6;
        ctx.fillStyle = "#451a03";
        ctx.fillRect(x + 3, sy, w - 6, 4);
        for (let b = 0; b < 4; b++) {
          ctx.fillStyle = bookColors[(shelf + b) % bookColors.length];
          ctx.fillRect(x + 4 + b * 2, sy, 2, 4);
        }
      }
      break;
    }
    case "plant": {
      ctx.fillStyle = "#b45309";
      ctx.fillRect(x + 5, y + 10, 6, 5);
      ctx.fillStyle = "#15803d";
      ctx.fillRect(x + 3, y + 4, 10, 6);
      ctx.fillStyle = "#22c55e";
      ctx.fillRect(x + 5, y + 2, 6, 6);
      ctx.fillRect(x + 2, y + 6, 4, 3);
      ctx.fillRect(x + 10, y + 6, 4, 3);
      break;
    }
    case "coffee_bar": {
      ctx.fillStyle = "#78350f";
      ctx.fillRect(x + 1, y + 3, w - 2, h - 4);
      ctx.fillStyle = "#d97706";
      ctx.fillRect(x + 2, y + 4, w - 4, h - 7);
      // Espresso machine
      ctx.fillStyle = "#334155";
      ctx.fillRect(x + 4, y + 1, 8, 7);
      ctx.fillStyle = "#ef4444";
      ctx.fillRect(x + 6, y + 2, 2, 1);
      // Steam animation
      const st = Math.floor(frameTick / 16) % 2;
      ctx.fillStyle = "rgba(248, 250, 252, 0.7)";
      ctx.fillRect(x + 17 + st, y + 1, 1, 2);
      ctx.fillRect(x + 20 - st, y + 2, 1, 2);
      // Mugs
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(x + 16, y + 5, 3, 3);
      ctx.fillRect(x + 21, y + 5, 3, 3);
      break;
    }
    case "sofa": {
      ctx.fillStyle = "#3730a3";
      ctx.fillRect(x + 1, y + 3, w - 2, h - 4);
      ctx.fillStyle = "#4f46e5";
      ctx.fillRect(x + 3, y + 5, w - 6, h - 7);
      ctx.fillStyle = "#6366f1";
      ctx.fillRect(x + 4, y + 6, Math.floor((w - 10) / 2), 4);
      ctx.fillRect(x + 6 + Math.floor((w - 10) / 2), y + 6, Math.floor((w - 10) / 2), 4);
      break;
    }
    case "table_round": {
      ctx.fillStyle = "#78350f";
      ctx.fillRect(x + 3, y + 4, 10, 8);
      ctx.fillStyle = "#b45309";
      ctx.fillRect(x + 4, y + 5, 8, 6);
      break;
    }
    case "lamp": {
      ctx.fillStyle = "#475569";
      ctx.fillRect(x + 7, y + 6, 2, 8);
      ctx.fillStyle = "#fde047";
      ctx.fillRect(x + 4, y + 2, 8, 5);
      ctx.fillStyle = "rgba(253, 224, 71, 0.14)";
      ctx.fillRect(x + 1, y + 1, 14, 14);
      break;
    }
  }
}
