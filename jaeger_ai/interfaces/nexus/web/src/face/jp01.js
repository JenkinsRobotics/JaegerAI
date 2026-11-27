// Copied from JaegerAvatar app/web/kin/jp01.js (commit e041f0c), now Omni's own file.
// JP01's own display behaviour, taken from its Teensy head firmware (EyesAnimation.h wakeup(), NeoPixelHandler.h):
// the wake-up sequence for the eyes and the two 24-LED side rings.
export const WAKE = 2.0;          // firmware: "2 seconds total / 5 steps"
export const RING_LEDS = 24;      // NUM_LEDS_LTNeoPixel / NUM_LEDS_RTNeoPixel
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));

// Which firmware step (0..4) a wake that started `age` seconds ago is on, and how far through it.
export function wakeStep(age) {
  const s = clamp(age / WAKE, 0, .99999) * 5;
  return { step: Math.floor(s), progress: s % 1 };
}

// The five wakeup() steps applied to the current face: blank, a 2-pixel line growing in width, the full line,
// the line opening in height, then the eyes fully open. Width and height are the face's own (so any mood wakes).
export function wakeFace(face, age) {
  if (age == null || age >= WAKE) return face;
  const { step, progress } = wakeStep(age), line = Math.max(4, face.height * .1), p = { ...face, blinkL: 0, blinkR: 0, heart: 0, star: 0, ring: 0, chevron: 0 };
  for (const k of ['blush', 'tear', 'sparkles', 'dots', 'question', 'sleep', 'notes', 'brows']) p[k] = 0;
  if (step === 0) { p.width = 0; p.height = 0; }
  else if (step === 1) { p.width = face.width * progress; p.height = line; }
  else if (step === 2) { p.height = line; }
  else if (step === 3) { p.height = line + (face.height - line) * progress; }
  p.curve = step < 3 ? 0 : face.curve;
  return p;
}

// Ring state for one frame: brightness 0..1 for each LED. During the wake the ring fills one LED at a time
// (the firmware's colorWipe) as the eye line grows; awake, it breathes slowly and swells with speech.
export function ringLevels(age, t, jaw = 0) {
  if (age != null && age < WAKE) {
    const lit = clamp((age - WAKE / 5) / (WAKE / 5)) * RING_LEDS;// fills while the eye line grows (step 1), full by the line, as on the real head
    return Array.from({ length: RING_LEDS }, (_, i) => clamp(lit - i));
  }
  const level = clamp(.72 + .14 * Math.sin(t * 1.3) + .3 * clamp(jaw));
  return Array(RING_LEDS).fill(level);
}

// 24 small LEDs on a circle in the y-z plane, facing +x (side 1) or -x (side -1). Returns the LED meshes.
export function addRing(THREE, parent, [x, y, z], side, radius, size) {
  const leds = [], geometry = new THREE.BoxGeometry(size * .35, size, size);
  for (let i = 0; i < RING_LEDS; i++) {
    const a = Math.PI / 2 - side * i / RING_LEDS * Math.PI * 2;// clockwise from the top, seen from that side
    const led = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0, toneMapped: false }));
    led.position.set(x, y + Math.sin(a) * radius, z + Math.cos(a) * radius); led.rotation.x = -a;
    parent.add(led); leds.push(led);
  }
  return leds;
}

// ---- Faces JP01 can wear. Each takes the shared eye performance `p` (gaze p.x/p.y, blinks, p.width/p.height
// relative to the resting 81x105 eye, p.curve, and the wake steps) so every face looks, blinks, talks and wakes.
const REST = { w: 81, h: 105 };
const lerp = (a, b, u) => a + (b - a) * u;

// A 64x64 LED panel, like JP01's real matrix: draw into the grid, then show it as lit dots with a soft glow.
export const GRID = 64;
export function panel() {
  const data = new Uint8ClampedArray(GRID * GRID * 4);
  const set = (x, y, [r, g, b], a = 1) => {
    x = Math.round(x); y = Math.round(y); if (x < 0 || y < 0 || x >= GRID || y >= GRID || a <= 0) return;
    const i = (y * GRID + x) * 4; data[i] = lerp(data[i], r, a); data[i + 1] = lerp(data[i + 1], g, a); data[i + 2] = lerp(data[i + 2], b, a); data[i + 3] = 255;
  };
  // Filled rounded rectangle centred on (cx, cy), the firmware's fillRoundRect.
  const box = (cx, cy, w, h, r, c, a = 1) => {
    if (w < .5 || h < .5) return; r = Math.min(r, w / 2, h / 2);
    const x0 = cx - w / 2, y0 = cy - h / 2;
    for (let y = Math.floor(y0); y < y0 + h; y++) for (let x = Math.floor(x0); x < x0 + w; x++) {
      const dx = Math.max(x0 + r - (x + .5), 0, x + .5 - (x0 + w - r)), dy = Math.max(y0 + r - (y + .5), 0, y + .5 - (y0 + h - r));
      if (dx * dx + dy * dy <= r * r + .25) set(x, y, c, a);
    }
  };
  return { data, set, box, lit: (x, y) => data[(y * GRID + x) * 4 + 3] > 0 };
}
let scratch = null, dots = null;
function showPanel(ctx, P, glow = .22) {
  const W = ctx.canvas.width, H = ctx.canvas.height, make = (w, h) => { const c = ctx.canvas.ownerDocument?.createElement('canvas') || new OffscreenCanvas(w, h); c.width = w; c.height = h; return c; };
  scratch ??= make(GRID, GRID);
  if (!dots) { dots = make(16, 16); const d = dots.getContext('2d'); d.fillStyle = '#fff'; d.beginPath(); d.roundRect(2, 2, 12, 12, 4); d.fill(); }
  const s = scratch.getContext('2d'), img = s.createImageData(GRID, GRID); img.data.set(P.data); s.putImageData(img, 0, 0);
  ctx.clearRect(0, 0, W, H); ctx.save();
  ctx.imageSmoothingEnabled = false; ctx.drawImage(scratch, 0, 0, W, H);
  ctx.globalCompositeOperation = 'destination-in'; ctx.fillStyle = ctx.createPattern(dots, 'repeat'); ctx.fillRect(0, 0, W, H);// only the LED dots stay lit
  ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = glow; ctx.imageSmoothingEnabled = true; ctx.drawImage(scratch, 0, 0, W, H);// soft panel glow
  ctx.restore();
}
const gazeOf = p => ({ gx: clamp((p.x || 0) / 54, -1.6, 1.6), gy: clamp((p.y || 0) / 28, -1.6, 1.6) });

// Matrix eyes: the head firmware's own face (EyesAnimation.h), two blue 20x20 rounded squares 28 px apart.
export function matrixFace(p) {
  const P = panel(), { gx, gy } = gazeOf(p), blue = [70, 120, 255];
  for (const [side, cx] of [[-1, 18], [1, 46]]) {
    const blink = clamp(side < 0 ? p.blinkL : p.blinkR), h = 20 * (p.height / REST.h) * (1 + side * (p.asym || 0)) * (1 - blink);
    P.box(cx + gx * 6, 32 + gy * 4 + (p.curve || 0) * .05, 20 * p.width / REST.w, Math.max(blink > .9 ? 2 : 0, h), 4, blue);
  }
  return P;
}

// T-face: JP01's warm pixel face from the real build, two T eyes, a flat mouth and pink cheek pixels.
export function tFace(p, jaw = 0) {
  const P = panel(), { gx, gy } = gazeOf(p), on = p.width > 0, open = clamp(p.height / REST.h);
  if (!on) return P;
  const glow = .3 + .7 * open, skin = [248, 226, 186], warm = [236, 168, 112], ink = [40, 26, 18], pink = [226, 74, 190];
  for (let y = 0; y < GRID; y++) for (let x = 0; x < GRID; x++) {
    const blot = .5 + .5 * Math.sin(x * .31 + y * .17) * Math.cos(y * .23 - x * .07);// uneven backlight, as on the panel
    P.set(x, y, [0, 1, 2].map(i => lerp(skin[i], warm[i], blot * .55) * glow));
  }
  const ex = gx * 3, ey = gy * 2, bar = 18 * p.width / REST.w;
  for (const [side, cx] of [[-1, 17], [1, 47]]) {
    const blink = clamp(side < 0 ? p.blinkL : p.blinkR), stem = 12 * open * (1 - blink);
    P.box(cx + ex, 16 + ey, bar, 4, 0, ink);
    P.box(cx + ex, 18 + ey + stem / 2, 4, stem, 0, ink);
    P.box(side < 0 ? 5 : 59, 29, 3, 3, 0, pink, .9);
  }
  const smile = clamp((p.curve || 0) / 30, -1, 1), mw = 20 - jaw * 6, mh = 2 + clamp(jaw) * 6;
  P.box(32 + ex * .5, 44 + ey * .5, mw, mh, 1, ink);
  if (Math.abs(smile) > .25) for (const side of [-1, 1]) P.box(32 + ex * .5 + side * (mw / 2 + 1), 44 + ey * .5 - Math.sign(smile) * 2, 2, 2, 0, ink);
  return P;
}

// Ring eyes: the JX screen face, white circle eyes and a small mouth on black, drawn smooth at full size.
export function ringFace(ctx, p, jaw = 0) {
  const W = ctx.canvas.width, H = ctx.canvas.height, s = W / 1024, { gx, gy } = gazeOf(p);
  ctx.clearRect(0, 0, W, H); if (p.width <= 0) return;
  ctx.save(); ctx.scale(s, H / 1024); ctx.strokeStyle = ctx.fillStyle = '#f4f7ff'; ctx.lineCap = 'round';
  ctx.shadowColor = 'rgba(200,220,255,.7)'; ctx.shadowBlur = 18;
  for (const [side, cx] of [[-1, 300], [1, 724]]) {
    const blink = clamp(side < 0 ? p.blinkL : p.blinkR), rx = 118 * p.width / REST.w, ry = Math.max(4, 118 * (p.height / REST.h) * (1 - blink));
    ctx.lineWidth = 40; ctx.beginPath(); ctx.ellipse(cx + gx * 40, 420 + gy * 26, rx, ry, 0, 0, Math.PI * 2); ctx.stroke();
  }
  const smile = clamp((p.curve || 0) / 30, -1, 1), mw = 60 - jaw * 20, mh = 10 + clamp(jaw) * 60, mx = 512 + gx * 18, my = 720 + gy * 10;
  ctx.lineWidth = 26; ctx.beginPath();
  if (mh > 14) ctx.ellipse(mx, my, mw, mh / 2, 0, 0, Math.PI * 2), ctx.fill();
  else { ctx.moveTo(mx - mw, my); ctx.quadraticCurveTo(mx, my + smile * 40, mx + mw, my); ctx.stroke(); }
  ctx.restore();
}

// name -> how to paint it and its side-ring colour (null ring = follow the eye colour).
export const FACES = {
  matrix: { paint: (ctx, p) => showPanel(ctx, matrixFace(p), .75), ring: [40, 90, 255] },
  tface: { paint: (ctx, p, jaw) => showPanel(ctx, tFace(p, jaw)), ring: [40, 230, 90] },
  ring: { paint: ringFace, ring: [60, 150, 255] },
};

// ---- Neon emotes: purge-mask style faces drawn as glowing neon tubes at full screen resolution. The emote
// follows the mood, swaps with a short flicker, and still blinks, looks around, talks and wakes.
export const EMOTES = {
  smile: { color: [60, 190, 255] },  // ^ ^ with a wide grin
  heart: { color: [255, 50, 170] },  // <3 <3 with lips
  wow: { color: [255, 215, 30] },    // o_o
  uwu: { color: [255, 40, 60] },     // U w U with blush marks
  dx: { color: [180, 90, 255] },     // X X and a shout
};
export const MOOD_EMOTE = { love: 'heart', surprised: 'wow', confused: 'wow', thinking: 'wow', listening: 'wow',
  shy: 'uwu', laughing: 'uwu', smug: 'uwu', excited: 'uwu', singing: 'uwu', angry: 'dx', scared: 'dx', sad: 'dx' };
export const emoteFor = (mood, reaction) => reaction === 'heart' ? 'heart' : reaction === 'sparkle' ? 'uwu' : MOOD_EMOTE[mood] || 'smile';

const curve = (x0, x1, y, dip, n = 24) => Array.from({ length: n + 1 }, (_, i) => { const u = i / n; return [lerp(x0, x1, u), y + dip * 4 * u * (1 - u)]; });
const oval = (cx, cy, rx, ry, n = 40) => Array.from({ length: n + 1 }, (_, i) => { const a = i / n * Math.PI * 2; return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]; });
const heartPts = (cx, cy, s, h, n = 48) => Array.from({ length: n + 1 }, (_, i) => { const a = i / n * Math.PI * 2; return [cx + s * Math.sin(a) ** 3, cy - h * s * (13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a)) / 16]; });

// The emote as neon tubes (`lines`) and lit panels (`fills`), in 64-unit screen coordinates.
export function emoteShapes(p, jaw = 0, name = 'smile', t = 0) {
  const lines = [], fills = [], out = { color: EMOTES[name]?.color || EMOTES.smile.color, lines, fills };
  if (p.width <= 0) return out;
  const { gx, gy } = gazeOf(p), open = clamp(p.height / REST.h), wide = clamp(p.width / REST.w), talk = clamp(jaw);
  if (open < .2) { for (const cx of [20, 44]) lines.push([[cx - 8 * wide, 27], [cx + 8 * wide, 27]]); return out; }// the wake line
  const ex = gx * 2.5, ey = gy * 2, sq = y => 32 + (y - 32) * open, my = sq(44) + ey * .5, mx = 32 + ex * .5;
  for (const [side, cx0] of [[-1, 20], [1, 44]]) {
    const blink = clamp(side < 0 ? p.blinkL : p.blinkR), cx = cx0 + ex, cy = sq(26) + ey, h = (1 - blink) * open;
    if (blink > .7) { lines.push([[cx - 6, cy], [cx + 6, cy]]); continue; }
    if (name === 'smile') lines.push(curve(cx - 7, cx + 7, cy + 2.5 * h, -6.5 * h));
    if (name === 'heart') fills.push(heartPts(cx, cy, 7.2 * (1 + .1 * Math.max(0, Math.sin(t * 7)) ** 8), h));
    if (name === 'wow') { lines.push(oval(cx, cy, 6, 6 * h)); fills.push(oval(cx + gx * 2, cy + gy * 2 * h, 1.8, 1.8 * h, 16)); }
    if (name === 'uwu') { lines.push([[cx - 6, cy - 5 * h], ...curve(cx - 6, cx + 6, cy + 1 * h, 4.5 * h, 16), [cx + 6, cy - 5 * h]]);
      for (let i = 0; i < 3; i++) lines.push([[cx - 4 + i * 3.4 + side * 1.5, cy + 9], [cx - 5.6 + i * 3.4 + side * 1.5, cy + 12]]); }
    if (name === 'dx') { lines.push([[cx - 6, cy - 6 * h], [cx + 6, cy + 6 * h]], [[cx + 6, cy - 6 * h], [cx - 6, cy + 6 * h]]); }
  }
  if (name === 'smile') { lines.push([[mx - 16, my - 4], ...curve(mx - 13, mx + 13, my - 2, 7 + talk * 3), [mx + 16, my - 4]]); if (talk > .2) lines.push(curve(mx - 8, mx + 8, my + 1, 2 + talk * 5)); }
  if (name === 'heart') { const o = talk * 3;
    fills.push([[mx - 7, my], [mx - 4, my - 2.4], [mx - 1.5, my - 2], [mx, my - 1.2], [mx + 1.5, my - 2], [mx + 4, my - 2.4], [mx + 7, my], ...curve(mx + 7, mx - 7, my, 3.5 + o, 12)]); }
  if (name === 'wow') lines.push(talk > .2 ? oval(mx, my, 2.5, 1 + talk * 3, 20) : [[mx - 4, my], [mx + 4, my]]);
  if (name === 'uwu') { const y = my + 2; lines.push([[mx - 7, y - 2], ...curve(mx - 7, mx, y - 1, 3 + talk * 2, 8), ...curve(mx, mx + 7, y - 1, 3 + talk * 2, 8), [mx + 7, y - 2]]); }
  if (name === 'dx') { const d = 8 + talk * 3; lines.push([[mx - 7, my - 4], [mx + 7, my - 4], [mx, my - 4 + d], [mx - 7, my - 4]], [[mx - 2, my - 2.5], [mx - 2, my + 1.5], [mx + 1.5, my - .5], [mx - 2, my - 2.5]]); }
  return out;
}

// Neon tubes: a wide soft halo, the coloured tube, then a near-white core.
function neon(ctx, { color: [r, g, b], lines, fills }, level = 1) {
  const W = ctx.canvas.width, H = ctx.canvas.height, k = W / 64, col = `rgb(${r},${g},${b})`, core = `rgb(${lerp(r, 255, .7)},${lerp(g, 255, .7)},${lerp(b, 255, .7)})`;
  const path = pts => { ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x * k, y * k) : ctx.moveTo(x * k, y * k)); };
  ctx.clearRect(0, 0, W, H); ctx.save(); ctx.lineCap = ctx.lineJoin = 'round'; ctx.globalAlpha = level;
  for (const [width, blur, style, alpha] of [[2.6, 90, col, .45], [1.5, 34, col, 1], [.55, 10, core, 1]]) {
    ctx.globalAlpha = level * alpha; ctx.shadowColor = style; ctx.shadowBlur = blur * W / 1024; ctx.strokeStyle = ctx.fillStyle = style; ctx.lineWidth = width * k;
    for (const l of lines) { path(l); ctx.stroke(); }
    for (const f of fills) { path(f); ctx.closePath(); if (style === core) { ctx.globalAlpha = level * .45; ctx.fill(); ctx.globalAlpha = level; ctx.lineWidth = .4 * k; ctx.stroke(); ctx.lineWidth = width * k; } else { ctx.fill(); ctx.stroke(); } }
  }
  ctx.restore();
}

FACES.emote = {
  paint(ctx, p, jaw, { mood, reaction, t = 0 } = {}) {
    const name = emoteFor(mood, reaction), state = ctx.canvas.neon ??= { name, at: -1 };// per screen
    if (name !== state.name) { state.name = name; state.at = t; }
    const age = t - state.at, flicker = age < .16 ? [0, .15, 1, .3, 1][Math.floor(age / .033)] ?? 1 : 1;// a neon sign re-striking
    neon(ctx, emoteShapes(p, jaw, name, t), flicker);
    return EMOTES[name].color.map(c => c * flicker);
  },
  ring: EMOTES.smile.color,
};

// ---- Mochi with a mouth: the default Mochi eyes, lifted, over a mouth. The mouths lip sync from Vita's five vowel
// shapes (aa ee ih oh ou): Mochi's round smile that opens, lips, or a voice waveform.
import { drawFace, eyeContour } from './eyes.js';
export function mouthShape(v = {}, jaw = 0) {
  const s = k => clamp(v[k] || 0), aa = s('aa'), ee = s('ee'), ih = s('ih'), oh = s('oh'), ou = s('ou');
  const open = clamp(Math.max(aa, oh * .85, ih * .6, ee * .45, ou * .7, clamp(jaw) * .8));
  return { open, width: 1 + .45 * ee + .15 * aa + .1 * ih - .4 * ou - .3 * oh, flat: clamp(ee * .8 + ih * .4) };
}
export function mochiMouth(ctx, p, v, jaw, { scale = 1.45 } = {}) {
  const { open, width, flat } = mouthShape(v, jaw), col = `rgb(${Math.round(clamp(p.red, 0, 255))},${Math.round(clamp(p.green, 0, 255))},${Math.round(clamp(p.blue, 0, 255))})`;
  const W = ctx.canvas.width, k = W / 1024, cx = (512 + (p.x || 0) * scale * .5) * k, cy = (750 + (p.y || 0) * .4) * k;
  ctx.save(); ctx.strokeStyle = ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 17 * k; ctx.lineCap = 'round'; ctx.lineWidth = 24 * k;
  if (p.width <= 0) { ctx.restore(); return; }
  // One shape that flows: at rest it's a smile line (both edges on the curve, drawn thick); speech opens it into the round
  // mouth by moving the edges apart and the centre down, with no swap between two drawings.
  const e = clamp(open / .2), ease = e * e * (3 - 2 * e), dip = clamp(26 + (p.curve || 0) * .6, 6, 48) * k;
  const half = lerp(75 * k, 70 * width * k, ease), ry = (12 + 78 * open * (1 - .35 * flat)) * k, n = 32, edge = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n * 2 - 1, round = Math.sqrt(Math.max(0, 1 - u * u)), y = lerp(cy + dip * (1 - u * u), cy + ry * .35, ease);
    edge.push([cx + u * half, y, ease * ry * round]);
  }
  ctx.beginPath(); edge.forEach(([x, y, h], i) => i ? ctx.lineTo(x, y - h) : ctx.moveTo(x, y - h));
  for (let i = n; i >= 0; i--) ctx.lineTo(edge[i][0], edge[i][1] + edge[i][2]);
  ctx.closePath(); ctx.globalAlpha = .22 * ease; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke();
  ctx.restore();
}
const rgb = (p, k = 1) => `rgb(${[p.red, p.green, p.blue].map(c => Math.round(clamp(c, 0, 255) * k)).join(',')})`;
// Where a mouth sits: 750 of a 1024-high screen, by the screen's own height, so it is on a wide screen (Mochi's) as on JP01's square one.
const mouthAt = (ctx, p, scale) => { const k = ctx.canvas.width / 1024; return { k, cx: (512 + (p.x || 0) * scale * .5) * k, cy: 750 * ctx.canvas.height / 1024 + (p.y || 0) * .4 * k }; };

// Lips: a cupid's-bow upper lip and a fuller lower lip, tinted toward pink, parting with each vowel.
export function mochiLips(ctx, p, v, jaw, { scale = 1.45 } = {}) {
  if (p.width <= 0) return;
  const { open, width, flat } = mouthShape(v, jaw), { k, cx, cy } = mouthAt(ctx, p, scale);
  const w = 240 * width * k, gap = 110 * open * (1 - .35 * flat) * k, lift = clamp((p.curve || 0) / 30, -1, 1) * 14 * k;
  const pink = { red: lerp(p.red, 255, .55), green: lerp(p.green, 120, .55), blue: lerp(p.blue, 175, .55) }, col = rgb(pink);
  const L = cx - w / 2, R = cx + w / 2, top = cy - gap * .4, bottom = cy + gap * .6;
  ctx.save(); ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 20 * k;
  ctx.beginPath(); ctx.moveTo(L, cy - lift);                                    // upper lip
  ctx.bezierCurveTo(L + w * .2, top - 30 * k, cx - w * .12, top - 34 * k, cx, top - 20 * k);
  ctx.bezierCurveTo(cx + w * .12, top - 34 * k, R - w * .2, top - 30 * k, R, cy - lift);
  ctx.quadraticCurveTo(cx, cy - gap * .8 + 12 * k, L, cy - lift); ctx.fill();// quadratic: the lip edge reaches half way to this point
  ctx.beginPath(); ctx.moveTo(L, cy - lift);                                    // lower lip
  ctx.quadraticCurveTo(cx, cy + gap * 1.2 - 8 * k, R, cy - lift);
  ctx.bezierCurveTo(R - w * .15, bottom + 52 * k, L + w * .15, bottom + 52 * k, L, cy - lift); ctx.fill();
  ctx.shadowBlur = 0; ctx.fillStyle = rgb(pink, 1.25); ctx.globalAlpha = .35;    // a highlight on the lower lip
  ctx.beginPath(); ctx.ellipse(cx, bottom + 24 * k, w * .16, 7 * k, 0, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

// Waveform: a glowing voice line across the mouth that ripples with speech; vowels change its pitch.
export function waveLine(v = {}, jaw = 0, t = 0, n = 72) {
  const { open, width } = mouthShape(v, jaw), freq = 2.2 + 2.4 * clamp(v.ee || 0) + 1.2 * clamp(v.ih || 0) - .9 * clamp((v.oh || 0) + (v.ou || 0)), amp = .03 + open;
  return Array.from({ length: n + 1 }, (_, i) => {
    const u = i / n, env = Math.sin(Math.PI * u) ** 1.5;
    const wave = Math.sin(u * Math.PI * 2 * freq + t * 9) * .6 + Math.sin(u * Math.PI * 2 * freq * 2.3 - t * 13) * .3 + Math.sin(u * Math.PI * 2 * 7.1 + t * 21) * .1 * open;
    return [(u - .5) * Math.max(.7, width), env * wave * amp];
  });
}
export function mochiWave(ctx, p, v, jaw, { scale = 1.45, t = 0 } = {}) {
  if (p.width <= 0) return;
  const { k, cx, cy } = mouthAt(ctx, p, scale), col = rgb(p), W = 380 * k, A = 95 * k;
  ctx.save(); ctx.strokeStyle = col; ctx.shadowColor = col; ctx.lineCap = ctx.lineJoin = 'round';
  for (const [lw, blur, alpha] of [[28, 34, .35], [14, 18, 1]]) {
    ctx.lineWidth = lw * k; ctx.shadowBlur = blur * k; ctx.globalAlpha = alpha; ctx.beginPath();
    waveLine(v, jaw, t).forEach(([x, y], i) => i ? ctx.lineTo(cx + x * W, cy + y * A) : ctx.moveTo(cx + x * W, cy + y * A)); ctx.stroke();
  }
  ctx.restore();
}

// Mochi's eyes, lifted to make room, over one of the mouths.
const LIFT = { scale: .92, dy: -110 };   // of a 1024 screen
const withMochiEyes = mouth => ({
  paint(ctx, p, jaw, { t = 0, v = {}, layout = {} } = {}) {
    const scale = (layout.scale || 1.55) * LIFT.scale;
    drawFace(ctx, p, t, { ...layout, scale, dy: LIFT.dy * ctx.canvas.height / 1024 }); mouth(ctx, p, v, jaw, { scale, t });
  },
});
FACES.mochi_mouth = withMochiEyes(mochiMouth);
FACES.mochi_lips = withMochiEyes(mochiLips);
FACES.mochi_wave = withMochiEyes(mochiWave);

// ---- The look made for the real panel. `native` draws a face straight onto the 64 x 64 LEDs: whole bright pixels and
// no glow, where the twin's big screen shrunk to 64 is a dim blur. The geometry is the twin's own (same layout numbers,
// divided by 16), so the robot and its twin show one face. A face without `native` is streamed as the shrunk stand-in.
const K = GRID / 1024, cover = new Float32Array(GRID * GRID);
// Fill a shape given as points in panel pixels. Four sample rows a pixel: an edge LED dims by how much of it is covered.
function fill(P, pts, color, alpha = 1) {
  let y0 = Infinity, y1 = -Infinity;
  for (const [, y] of pts) { y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  y0 = Math.max(0, Math.floor(y0)); y1 = Math.min(GRID, Math.ceil(y1));
  for (let row = y0 * 4; row < y1 * 4; row++) {
    const y = (row + .5) / 4, xs = [];
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) { const [ax, ay] = pts[i], [bx, by] = pts[j]; if ((ay > y) !== (by > y)) xs.push(ax + (y - ay) / (by - ay) * (bx - ax)); }
    xs.sort((a, b) => a - b);
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const a = Math.max(0, xs[k]), b = Math.min(GRID, xs[k + 1]);
      for (let x = Math.floor(a); x < b; x++) cover[(row >> 2) * GRID + x] += (Math.min(b, x + 1) - Math.max(a, x)) / 4;
    }
  }
  for (let y = y0; y < y1; y++) for (let x = 0; x < GRID; x++) { const i = y * GRID + x; if (cover[i]) { P.set(x, y, color, Math.min(1, cover[i]) * alpha); cover[i] = 0; } }
}
// A near-level line as a band `w` pixels tall.
const band = (P, pts, w, color, alpha) => fill(P, [...pts.map(([x, y]) => [x, y - w / 2]), ...pts.map(([x, y]) => [x, y + w / 2]).reverse()], color, alpha);
const GLYPHS = { question: ['111', '001', '011', '000', '010'], sleep: ['111', '001', '010', '100', '111'], notes: ['011', '011', '010', '110', '110'] };   // ? z and a note, 3 x 5 LEDs
// Mochi's eyes and marks (eyes.js drawFace) on the panel.
function mochiEyes64(P, p, t, { scale = 1.55, spread = 1 } = {}) {
  const s = scale * LIFT.scale * K, X = x => GRID / 2 + (x - 512) * s, Y = y => (512 + LIFT.dy) * K + (y - 320) * s;
  const color = [p.red, p.green, p.blue].map(c => clamp(c, 0, 255));
  for (const side of [-1, 1]) {
    const cx = X(512 + side * p.spread * spread + p.x), cy = Y(288 + p.y), blink = clamp(side < 0 ? p.blinkL : p.blinkR);
    const contour = eyeContour(p, side).map(([x, y]) => [cx + x * s, cy + y * s]);
    if (Math.max(3, p.height * (1 - blink)) * 2 * s < 1.6) for (const d of [-.4, .4]) fill(P, contour.map(([x, y]) => [x, y + d]), color);   // a closed eye is still a line of whole LEDs
    else fill(P, contour, color);
    if (p.ring > .01) { const r = clamp(p.ring, 0, .84); fill(P, contour.map(([x, y]) => [cx + (x - cx) * r, cy + (y - cy) * r]), [0, 0, 0]); }
    if (p.brows > .01) {
      const lift = -143 - p.browLift, slope = side * p.browSlope * 55;
      band(P, Array.from({ length: 9 }, (_, i) => { const u = i / 8, y = (1 - u) ** 2 * (lift - slope) + 2 * u * (1 - u) * (lift - 9) + u * u * (lift + slope); return [cx + (u * 116 - 58) * s, cy + y * s]; }), Math.max(1.5, 8 * s), color, clamp(p.brows));
    }
    for (let i = 0; i < 3 && p.blush > .01; i++) P.box(Math.round(X(512 + side * 302 * spread)) + i * 2 + .5, Math.round(Y(410)) + .5, 1, 3, 0, [255, 168, 186], clamp(p.blush) * .65);   // one LED wide, every other column: 19 units apart is under two LEDs
    if (p.tear > .02) { const phase = (t * .48 + (side > 0 ? .4 : 0)) % 1; P.box(X(512 + side * 245 * spread + p.x), Y(340 + phase * 147), 1.5, 2.5, .7, [157, 207, 255], clamp(p.tear) * Math.sin(phase * Math.PI)); }
  }
  for (let i = 0; i < 5 && p.sparkles > .02; i++) {
    const phase = (t * .4 + i * .19) % 1, a = Math.sin(phase * Math.PI) * clamp(p.sparkles) * .85, x = X([190, 800, 500, 237, 772][i]), y = Y([154, 165, 110, 442, 426][i] - phase * 15);
    P.set(x, y, color, a); for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) P.set(x + dx, y + dy, color, a * .5);
  }
  for (let i = 0; i < 3 && p.dots > .02; i++) P.box(X(476 + i * 36), Y(465), 2, 2, 0, color, clamp(p.dots) * (.25 + .75 * (.5 + .5 * Math.sin(t * 3 - i * .8))));
  for (const [field, x, y] of [['question', 765, 138], ['sleep', 768, 167], ['notes', 205, 150]]) if (p[field] > .02)   // ponytail: one z, where the twin has a second, smaller one
    GLYPHS[field].forEach((row, j) => [...row].forEach((on, i) => { if (on === '1') P.set(X(x) + i, Y(y - Math.sin(t * 1.7) * 5) - 5 + j, color, clamp(p[field]) * .7); }));
}
// The voice line: the twin's waveform, resting on whole rows. Each column of LEDs is lit from the line's height on its
// left edge to its height on the right edge, one LED past each end: two LEDs thick when flat, unbroken when steep.
function wave64(P, p, v, jaw, t, scale) {
  const cx = (512 + (p.x || 0) * scale * .5) * K, cy = Math.round((750 + (p.y || 0) * .4) * K), color = [p.red, p.green, p.blue].map(c => clamp(c, 0, 255));
  const pts = waveLine(v, jaw, t).map(([x, y]) => [cx + x * 380 * K, cy + y * 95 * K]);
  let i = 0;
  const at = x => { while (i < pts.length - 2 && pts[i + 1][0] < x) i++; const [ax, ay] = pts[i], [bx, by] = pts[i + 1]; return ay + (by - ay) * clamp((x - ax) / (bx - ax || 1)); };
  for (let x = Math.ceil(pts[0][0]); x + 1 <= pts.at(-1)[0]; x++) {
    const a = at(x), b = at(x + 1), top = Math.min(a, b) - 1, bottom = Math.max(a, b) + 1;
    for (let y = Math.floor(top); y < bottom; y++) P.set(x, y, color, Math.min(bottom, y + 1) - Math.max(top, y));
  }
}
FACES.mochi_wave.native = (p, jaw, { t = 0, v = {}, layout = {} } = {}) => {
  const P = panel();
  if (p.width > 0) { mochiEyes64(P, p, t, layout); wave64(P, p, v, jaw, t, (layout.scale || 1.55) * LIFT.scale); }
  return P;
};
FACES.matrix.native = p => matrixFace(p);
FACES.tface.native = (p, jaw) => tFace(p, jaw);
// The faces a JP01 can switch between live, in picker order ('' = Mochi eyes, the default).
export const FACE_CHOICES = [['', 'Mochi eyes'], ['mochi_mouth', 'Mochi eyes + mouth'], ['mochi_lips', 'Mochi eyes + lips'], ['mochi_wave', 'Mochi eyes + waveform'], ['matrix', 'Matrix'], ['tface', 'T-face'], ['ring', 'Ring eyes'], ['emote', 'Neon emotes']];
