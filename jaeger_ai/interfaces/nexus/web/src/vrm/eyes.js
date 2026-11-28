// The eyes of the display robots. Every shape comes from one 64-point outline, so hearts, stars, lids and pills morph
// rather than swap, and every value runs through a damped spring, so any change can interrupt any other and still settle.
// Adapted from local-avatar-demo/public/js/eyes.js; see the README's source record. No DOM here, so `node test.mjs` can check it.
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const ease = v => { v = clamp(v); return v * v * (3 - 2 * v); };
const pulse = (t, start, attack, hold, release) => ease((t - start) / attack) * ease((start + attack + hold + release - t) / release);

// Each has anticipation, a hold you can read, and a recovery. duration is in seconds.
export const REACTIONS = { blink: 0.9, wink: 1.8, sideeye: 2.8, sparkle: 2.5, heart: 3, roll: 2.4, peek: 3.2, doze: 4, groove: 3, wake: 1.8 };

const BASE = { width: 81, height: 105, curve: 0, tilt: 0, asym: 0, spread: 178, x: 0, y: 0, heart: 0, star: 0, ring: 0, chevron: 0, blush: 0, tear: 0, brows: 0, browSlope: 0, browLift: 0, blinkL: 0, blinkR: 0, red: 190, green: 255, blue: 225, sparkles: 0, question: 0, dots: 0, notes: 0, sleep: 0 };
export const MOODS = {
  neutral: {},
  joy: { height: 10, width: 86, curve: 38, y: 8, sparkles: 0.12 },
  excited: { height: 103, width: 94, star: 0.95, red: 255, green: 223, blue: 156, sparkles: 1 },
  love: { heart: 1, width: 98, height: 111, red: 255, green: 163, blue: 193, blush: 0.7, sparkles: 0.35 },
  sad: { height: 43, width: 77, tilt: 0.16, curve: -12, y: 25, red: 157, green: 209, blue: 255, tear: 0.85, brows: 0.65, browSlope: 0.3 },
  angry: { height: 45, width: 92, tilt: -0.25, red: 255, green: 154, blue: 120, brows: 1, browSlope: -0.35, browLift: -8 },
  surprised: { width: 78, height: 111, ring: 0.6, spread: 183, y: -8, brows: 0.35, browLift: 20 },
  scared: { width: 83, height: 115, ring: 0.76, spread: 185, red: 198, green: 221, blue: 255, brows: 0.8, browSlope: 0.25, browLift: 13 },
  thinking: { height: 69, width: 70, asym: 0.37, x: 32, y: -24, dots: 1, brows: 0.3, browLift: 14 },
  confused: { height: 62, width: 78, asym: -0.6, tilt: 0.07, question: 1, brows: 0.65, browSlope: 0.15, browLift: 17 },
  shy: { height: 30, width: 74, curve: 13, y: 25, x: -12, blush: 1, red: 225, green: 232, blue: 245 },
  smug: { height: 30, width: 84, asym: 0.55, curve: 11, tilt: -0.06, x: -20, brows: 0.5, browLift: 5 },
  sleepy: { height: 9, width: 88, curve: -3, y: 28, sleep: 1, red: 180, green: 203, blue: 228 },
  laughing: { height: 7, width: 87, chevron: 1, y: 5, red: 244, green: 237, blue: 184 },
  singing: { height: 22, width: 83, curve: 28, notes: 1, red: 183, green: 240, blue: 255 },
  listening: { height: 109, width: 67, spread: 165, brows: 0.22, browLift: 11 },
};

// What the eyes want to be right now. v: { emotion, moodAge, reaction: { name, age }, and the rig's output channels }.
export function faceTarget(v, t) {
  const name = MOODS[v.emotion] ? v.emotion : 'neutral', p = { ...BASE, ...MOODS[name] };
  const age = v.moodAge ?? 3, pop = Math.sin(age * 14) * Math.exp(-age * 7) * 0.07;   // a new feeling lands with a little overshoot, on the screen
  p.width *= 1 + pop; p.height *= 1 - pop * 0.5;
  // The shell stays put, so the rig's body language plays out on the display: a nod dips the eyes, a tilt tilts them.
  p.x += (v.gazeX || 0) * 54 + (v.yaw || 0) * 44;
  p.y += -(v.gazeY || 0) * 28 - (v.pitch || 0) * 34 - (v.lift || 0) * 14 + (v.crouch || 0) * 18;
  p.tilt += (v.roll || 0) * 0.35;
  p.blinkL = clamp(v.blinkL ?? 0); p.blinkR = clamp(v.blinkR ?? 0);
  if (name === 'love') { const b = t % 2.4, thump = pulse(b, 0.1, 0.1, 0.02, 0.22) + 0.6 * pulse(b, 0.43, 0.09, 0.01, 0.18); p.width *= 1 + 0.055 * thump; p.height *= 1 + 0.055 * thump; }
  if (name === 'scared') p.x += Math.sin(t * 29) * 1.6;
  if (name === 'laughing') { p.y += Math.sin(t * 9) * 3; p.curve = 5; }
  if (name === 'singing') { p.y += Math.sin(t * 3) * 3; p.asym = Math.sin(t * 3) * 0.2; }
  const speech = clamp(v.jaw || 0); p.width *= 1 + speech * 0.045; p.height *= 1 + speech * 0.08;

  const r = v.reaction, duration = r && REACTIONS[r.name];
  if (duration) {
    const a = r.age, e = pulse(a, 0, 0.18, Math.max(0, duration - 0.55), 0.37);
    if (r.name === 'blink') { const b = Math.max(pulse(a, 0.06, 0.07, 0.035, 0.14), pulse(a, 0.4, 0.07, 0.025, 0.16)); p.blinkL = Math.max(p.blinkL, b); p.blinkR = Math.max(p.blinkR, b); }
    if (r.name === 'wink') { p.height += (95 - p.height) * e * 0.9; p.blinkR = Math.max(p.blinkR, pulse(a, 0.24, 0.12, 0.7, 0.28)); p.curve += e * 12; p.x -= e * 9; }
    if (r.name === 'sideeye') { p.x += e * 82; p.height *= 1 - 0.65 * e; p.asym += e * 0.25; }
    if (r.name === 'sparkle') { p.star += (1 - p.star) * e; p.width += e * 12; p.height += (105 - p.height) * e; p.sparkles = Math.max(p.sparkles, e); p.red += e * (255 - p.red); p.blue += e * (150 - p.blue); }
    if (r.name === 'heart') { p.heart += (1 - p.heart) * e; p.width += e * 12; p.height += (110 - p.height) * e; p.blush = Math.max(p.blush, e); p.red += e * (255 - p.red); p.green += e * (163 - p.green); p.blue += e * (193 - p.blue); }
    if (r.name === 'roll') { const th = ease((a - 0.25) / 1.6) * Math.PI * 2; p.x += Math.sin(th) * 70 * e; p.y += (Math.cos(th) - 1) * 30 * e; p.height *= 1 - 0.35 * e; }
    if (r.name === 'peek') { p.blinkL = Math.max(p.blinkL, pulse(a, 0.05, 0.14, 0.55, 0.75)); p.blinkR = Math.max(p.blinkR, pulse(a, 0.05, 0.14, 1.35, 0.65)); p.x += e * 24; }
    if (r.name === 'doze') { p.height *= 1 - 0.93 * e; p.y += e * 16; p.sleep = Math.max(p.sleep, e); p.curve -= e * 5; }
    if (r.name === 'groove') { const w = Math.sin(a * 5) * e; p.y += w * 11; p.asym += w * 0.45; p.curve += e * 12; p.notes = Math.max(p.notes, e); }
    if (r.name === 'wake') { const b = pulse(a, 0.04, 0.08, 0.13, 0.13), open = pulse(a, 0.37, 0.1, 0.5, 0.6); p.blinkL = Math.max(p.blinkL, b); p.blinkR = Math.max(p.blinkR, b); p.height += (123 - p.height) * open; p.width += (91 - p.width) * open; p.ring += 0.3 * open; }
  }
  const energy = clamp(v.energy2 ?? 1, 0.5, 1.5);
  p.x *= energy; p.y *= energy; p.curve *= 0.75 + energy * 0.25; p.tilt *= 0.8 + energy * 0.2;
  p.x = clamp(p.x, -150, 150); p.y = clamp(p.y, -60, 60);   // a shape never leaves the display
  return p;
}

export class FaceAnimator {
  constructor() { this.values = { ...BASE }; this.velocity = Object.fromEntries(Object.keys(BASE).map(k => [k, 0])); }
  update(v, dt, t) {
    const target = faceTarget(v, t);
    for (const key of Object.keys(BASE)) {
      const lid = key.startsWith('blink'), speed = lid ? 47 : key === 'x' || key === 'y' ? 24 : 19, damping = lid ? 1 : 0.83;
      for (let left = clamp(dt, 0, 0.1); left > 0; left -= 1 / 120) {    // small steps, so a stalled tab can't blow the spring up
        const h = Math.min(left, 1 / 120);
        this.velocity[key] += (speed * speed * (target[key] - this.values[key]) - 2 * damping * speed * this.velocity[key]) * h;
        this.values[key] += this.velocity[key] * h;
      }
    }
    return this.values;
  }
}

// The shared outline. side is -1 or +1.
export function eyeContour(p, side, steps = 64) {
  const points = [], blink = clamp(side < 0 ? p.blinkL : p.blinkR), width = p.width * (1 + blink * 0.08), height = Math.max(3, p.height * (1 + side * p.asym) * (1 - blink));
  const heart = clamp(p.heart) * (1 - blink), star = clamp(p.star) * (1 - blink), angle = side * p.tilt, c = Math.cos(angle), s = Math.sin(angle);
  for (let i = 0; i < steps; i++) {
    const a = i / steps * Math.PI * 2, cx = Math.cos(a), sy = Math.sin(a);
    const ex = Math.sign(cx) * Math.abs(cx) ** 0.58, ey = Math.sign(sy) * Math.abs(sy) ** 0.58;   // rounded pill
    const ht = a + Math.PI / 2, hx = Math.sin(ht) ** 3, hy = -(13 * Math.cos(ht) - 5 * Math.cos(2 * ht) - 2 * Math.cos(3 * ht) - Math.cos(4 * ht)) / 17;   // heart
    const sec = Math.floor(i / (steps / 8)), f = (i % (steps / 8)) / (steps / 8), a0 = sec * Math.PI / 4, a1 = (sec + 1) * Math.PI / 4, r0 = sec % 2 ? 0.29 : 1, r1 = sec % 2 ? 1 : 0.29;   // four-point star
    const sx = Math.cos(a0) * r0 * (1 - f) + Math.cos(a1) * r1 * f, sy2 = Math.sin(a0) * r0 * (1 - f) + Math.sin(a1) * r1 * f;
    let x = ex * (1 - heart) + hx * heart, y = ey * (1 - heart) + hy * heart;
    x = x * (1 - star) + sx * star; y = y * (1 - star) + sy2 * star;
    x *= width; y *= height;
    y += (x * x / (width * width) - 1) * (p.curve + blink * 12) * (1 - heart) * (1 - star);
    y += clamp(p.chevron) * (1 - Math.abs(x / width)) * -48 * (1 - blink);
    points.push([x * c - y * s, x * s + y * c]);
  }
  return points;
}

function trace(ctx, points) { ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath(); }

// Paints onto a clear 1024x512 layer, already scaled by the caller. scale is what that scaling is, since shadows ignore transforms.
export function drawFace(ctx, p, t, scale = 1, color = `rgb(${clamp(p.red, 0, 255) | 0},${clamp(p.green, 0, 255) | 0},${clamp(p.blue, 0, 255) | 0})`) {
  for (const side of [-1, 1]) {
    ctx.save(); ctx.translate(512 + side * p.spread + p.x, 256 + p.y);
    const outline = eyeContour(p, side);
    ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 17 * scale; trace(ctx, outline); ctx.fill(); ctx.shadowBlur = 0;
    if (p.ring > 0.01) { ctx.globalCompositeOperation = 'destination-out'; ctx.save(); ctx.scale(clamp(p.ring, 0, 0.84), clamp(p.ring, 0, 0.84)); trace(ctx, outline); ctx.fill(); ctx.restore(); ctx.globalCompositeOperation = 'source-over'; }
    if (p.brows > 0.01) { ctx.globalAlpha = clamp(p.brows); ctx.strokeStyle = color; ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(-58, -143 - p.browLift - side * p.browSlope * 55); ctx.quadraticCurveTo(0, -152 - p.browLift, 58, -143 - p.browLift + side * p.browSlope * 55); ctx.stroke(); }
    ctx.restore();
  }
  // Secondary marks stay on the display, so the silhouette never changes.
  ctx.save(); ctx.strokeStyle = '#ffa8ba'; ctx.lineWidth = 7; ctx.lineCap = 'round'; ctx.globalAlpha = clamp(p.blush) * 0.65;
  for (const side of [-1, 1]) for (let i = 0; i < 3; i++) { const x = 512 + side * 302 + i * 19; ctx.beginPath(); ctx.moveTo(x, 365); ctx.lineTo(x - 9, 391); ctx.stroke(); }
  ctx.restore();
  if (p.tear > 0.02) { ctx.save(); ctx.fillStyle = '#9dcfff'; for (const side of [-1, 1]) { const ph = (t * 0.48 + (side > 0 ? 0.4 : 0)) % 1; ctx.globalAlpha = clamp(p.tear) * Math.sin(ph * Math.PI); ctx.beginPath(); ctx.ellipse(512 + side * 245 + p.x, 308 + ph * 147, 8, 13, 0, 0, Math.PI * 2); ctx.fill(); } ctx.restore(); }
  if (p.sparkles > 0.02) { ctx.save(); ctx.fillStyle = color; for (let i = 0; i < 5; i++) { const ph = (t * 0.4 + i * 0.19) % 1, al = Math.sin(ph * Math.PI) * clamp(p.sparkles); ctx.globalAlpha = al * 0.85; const x = [190, 800, 500, 237, 772][i], y = [122, 133, 78, 410, 394][i] - ph * 15, r = 6 + al * 7; ctx.beginPath(); ctx.moveTo(x, y - r); ctx.quadraticCurveTo(x + 2, y - 2, x + r, y); ctx.quadraticCurveTo(x + 2, y + 2, x, y + r); ctx.quadraticCurveTo(x - 2, y + 2, x - r, y); ctx.quadraticCurveTo(x - 2, y - 2, x, y - r); ctx.fill(); } ctx.restore(); }
  if (p.dots > 0.02) { ctx.save(); ctx.fillStyle = color; for (let i = 0; i < 3; i++) { ctx.globalAlpha = clamp(p.dots) * (0.25 + 0.75 * (0.5 + 0.5 * Math.sin(t * 3 - i * 0.8))); ctx.beginPath(); ctx.arc(760 + i * 36, 96, 7, 0, Math.PI * 2); ctx.fill(); } ctx.restore(); }
  for (const [field, glyph, x, y] of [['question', '?', 765, 106], ['sleep', 'z', 768, 135], ['notes', '♪', 205, 118]]) if (p[field] > 0.02) {
    ctx.save(); ctx.fillStyle = color; ctx.globalAlpha = clamp(p[field]) * 0.7; ctx.font = '46px Georgia'; ctx.fillText(glyph, x, y - Math.sin(t * 1.7) * 5);
    if (field === 'sleep') { ctx.font = '28px Georgia'; ctx.globalAlpha *= 0.7; ctx.fillText('z', 803, 87 - Math.sin(t * 1.7) * 5); }
    ctx.restore();
  }
}
