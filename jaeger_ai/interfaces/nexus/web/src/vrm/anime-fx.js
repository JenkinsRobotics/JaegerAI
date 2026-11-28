// What an anime cuts to around a feeling: drawn marks that track the head, and a backdrop that changes with the mood.
// Everything here is plain 2D canvas, redrawn only when a new pose shows.
const INK = 'rgba(28,18,48,.95)';
const seeded = i => { const x = Math.sin(i * 127.1) * 43758.5453; return x - Math.floor(x); };

function heartPath(g, x, y, s) {
  g.beginPath(); g.moveTo(x, y + s * 0.9);
  g.bezierCurveTo(x - s * 1.5, y - s * 0.1, x - s * 0.7, y - s * 1.1, x, y - s * 0.35);
  g.bezierCurveTo(x + s * 0.7, y - s * 1.1, x + s * 1.5, y - s * 0.1, x, y + s * 0.9); g.closePath();
}
function star(g, x, y, s) {
  g.beginPath();
  for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4 - Math.PI / 2, r = i % 2 ? s * 0.18 : s; g[i ? 'lineTo' : 'moveTo'](x + Math.cos(a) * r, y + Math.sin(a) * r); }
  g.closePath(); g.fill();
}
function rays(g, cx, cy, n, r0, r1, spread, color, rot = 0, jitter = 0, step = 0) {
  g.fillStyle = color; g.beginPath();
  for (let i = 0; i < n; i++) {
    const a = rot + i / n * Math.PI * 2 + (seeded(i + step * 13) - 0.5) * jitter, rr = r0 * (1 + (seeded(i * 3 + step) - 0.5) * jitter);
    g.moveTo(cx + Math.cos(a - spread) * r1, cy + Math.sin(a - spread) * r1);
    g.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
    g.lineTo(cx + Math.cos(a + spread) * r1, cy + Math.sin(a + spread) * r1);
  }
  g.fill();
}

const MOODS = {
  surprised(g, w, h, cx, cy, A, t, step) { g.fillStyle = `rgba(255,255,255,${0.1 * A})`; g.fillRect(0, 0, w, h); rays(g, cx, cy, 64, Math.min(w, h) * 0.4, Math.hypot(w, h), 0.012, `rgba(255,255,255,${0.75 * A})`, 0, 0.5, step); },
  scared(g, w, h, cx, cy, A, t, step) { g.fillStyle = `rgba(20,8,50,${0.5 * A})`; g.fillRect(0, 0, w, h); rays(g, cx, cy, 48, Math.min(w, h) * 0.46, Math.hypot(w, h), 0.01, `rgba(190,170,255,${0.4 * A})`, 0, 0.6, step); },
  angry(g, w, h, cx, cy, A, t, step) { g.fillStyle = `rgba(120,10,20,${0.5 * A})`; g.fillRect(0, 0, w, h); rays(g, cx, cy, 40, Math.min(w, h) * 0.38, Math.hypot(w, h), 0.03, `rgba(255,70,40,${0.45 * A})`, 0, 0.45, step); },
  sad(g, w, h, cx, cy, A, t) {
    g.fillStyle = `rgba(10,20,60,${0.55 * A})`; g.fillRect(0, 0, w, h);
    g.strokeStyle = `rgba(150,180,255,${0.28 * A})`; g.lineWidth = Math.max(1, h / 700); g.beginPath();
    for (let i = 0; i < 46; i++) { const x = seeded(i) * w, y = ((seeded(i + 50) + t * (0.25 + seeded(i + 9) * 0.25)) % 1) * h * 1.2 - h * 0.1; g.moveTo(x, y); g.lineTo(x, y + h * 0.09); }
    g.stroke();
  },
  love(g, w, h, cx, cy, A, t) {
    g.fillStyle = `rgba(255,110,170,${0.28 * A})`; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 18; i++) { const s = h * (0.012 + seeded(i) * 0.03), y = h * 1.1 - ((seeded(i + 7) + t * (0.05 + seeded(i + 3) * 0.05)) % 1) * h * 1.2; g.fillStyle = `rgba(255,${150 + (i % 3) * 30},200,${0.5 * A})`; heartPath(g, seeded(i + 21) * w + Math.sin(t + i) * h * 0.012, y, s); g.fill(); }
  },
  joy(g, w, h, cx, cy, A, t) {
    g.fillStyle = `rgba(255,130,90,${0.24 * A})`; g.fillRect(0, 0, w, h);
    rays(g, cx, cy, 14, Math.min(w, h) * 0.05, Math.hypot(w, h), 0.09, `rgba(255,190,90,${0.3 * A})`, t * 0.12);
    g.fillStyle = `rgba(255,250,210,${0.8 * A})`;
    for (let i = 0; i < 16; i++) star(g, seeded(i + 40) * w, seeded(i + 60) * h, h * 0.016 * (0.6 + 0.6 * Math.abs(Math.sin(t * 2.2 + i))));
  },
  thinking(g, w, h, cx, cy, A) { g.fillStyle = `rgba(14,12,40,${0.32 * A})`; g.fillRect(0, 0, w, h); },
  sleepy(g, w, h, cx, cy, A) { g.fillStyle = `rgba(8,12,44,${0.48 * A})`; g.fillRect(0, 0, w, h); },
  singing(g, w, h, cx, cy, A, t) {
    g.fillStyle = `rgba(90,40,170,${0.3 * A})`; g.fillRect(0, 0, w, h);
    for (const [x0, sp, col] of [[0.2, 0.7, '120,220,255'], [0.8, -0.9, '255,130,220'], [0.5, 1.2, '190,160,255']]) {
      const a = Math.PI / 2 + Math.sin(t * sp) * 0.55, sx = x0 * w, L = Math.hypot(w, h);
      g.fillStyle = `rgba(${col},${0.2 * A})`; g.beginPath(); g.moveTo(sx, -10); g.lineTo(sx + Math.cos(a - 0.1) * L, Math.sin(a - 0.1) * L); g.lineTo(sx + Math.cos(a + 0.1) * L, Math.sin(a + 0.1) * L); g.fill();
    }
  },
};
MOODS.excited = MOODS.joy; MOODS.laughing = MOODS.joy; MOODS.shy = MOODS.love;

export class Mood {
  constructor(before) {
    this.c = document.createElement('canvas'); this.c.className = 'bgl';
    this.c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none';
    before.parentNode.insertBefore(this.c, before);
    this.g = this.c.getContext('2d'); this.w = {}; this.at = 0; this.step = 0;
  }
  // Half resolution: these are soft backdrops, and it keeps the fill cost out of the frame budget.
  draw(emotion, t, W, H, cx, cy) {
    const c = this.c, g = this.g, w = W >> 1, h = H >> 1, dt = Math.min(0.2, t - this.at); this.at = t; this.step++;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    g.clearRect(0, 0, w, h);
    for (const k of Object.keys(MOODS)) {
      this.w[k] = (this.w[k] ?? 0) + ((k === emotion ? 1 : 0) - (this.w[k] ?? 0)) * (1 - Math.exp(-dt * (k === emotion ? 14 : 6)));
      if (this.w[k] > 0.01) MOODS[k](g, w, h, cx / 2, cy / 2, this.w[k], t, this.step);
    }
  }
}

// Manga marks, anchored to the head so they turn and bob with it. eyes and head are overlay pixels, r is the head radius in pixels.
export function drawMarks(g, o, t, { head, eyes, r, side, facing }) {
  // An iris mesh's centre sits above the part you can see, so the marks aim a little lower.
  eyes = eyes.map(e => [e[0], e[1] + r * 0.1]);
  const cheekY = r * 0.24, front = Math.max(0, Math.min(1, (facing - 0.25) * 4));
  g.save(); g.lineCap = 'round'; g.lineJoin = 'round';
  if (o.blush > 0.3 && front) {          // hatched blush lines
    g.strokeStyle = `rgba(226,60,90,${(o.blush - 0.3) * 1.3 * front})`; g.lineWidth = Math.max(1, r * 0.022); g.beginPath();
    for (const e of eyes) for (let i = 0; i < 4; i++) { const x = e[0] + (i - 1.5) * r * 0.075, y = e[1] + cheekY; g.moveTo(x + r * 0.045, y - r * 0.05); g.lineTo(x - r * 0.045, y + r * 0.05); }
    g.stroke();
  }
  if (o.droop > 0.25) {                  // gloom lines down the forehead
    g.strokeStyle = `rgba(70,50,150,${Math.min(0.75, o.droop * 0.75)})`; g.lineWidth = Math.max(1, r * 0.024); g.beginPath();
    for (let i = 0; i < 11; i++) { const x = head[0] + (i - 5) * r * 0.11, y0 = head[1] - r * (0.62 - Math.abs(i - 5) * 0.03); g.moveTo(x, y0); g.lineTo(x, y0 + r * (0.2 + seeded(i) * 0.26)); }
    g.stroke();
  }
  if (o.tear > 0.12 && front) {          // tears: a stream down each cheek and a drop falling off it
    const a = Math.min(1, o.tear * 1.6) * front;
    for (const e of eyes) {
      g.strokeStyle = `rgba(150,215,255,${0.85 * a})`; g.lineWidth = r * 0.055; g.beginPath(); g.moveTo(e[0], e[1] + r * 0.1); g.lineTo(e[0] + side * r * 0.02, e[1] + r * (0.25 + o.tear * 0.5)); g.stroke();
      const u = (t * 0.9 + e[0] * 0.013) % 1;
      g.fillStyle = `rgba(190,232,255,${a})`; g.beginPath(); g.ellipse(e[0], e[1] + r * (0.3 + u * 0.9), r * 0.032, r * 0.055, 0, 0, 7); g.fill();
    }
  }
  if (o.sweat > 0.2) {                   // the big sweat drop on the temple
    const a = Math.min(1, o.sweat * 1.5), s = r * 0.17, x = head[0] + r * 0.92 * (side || 1), y = head[1] - r * 0.3 + ((t * 0.28) % 1) * r * 0.28;
    g.globalAlpha = a; g.fillStyle = '#a9dcff'; g.strokeStyle = INK; g.lineWidth = Math.max(1, r * 0.025);
    g.beginPath(); g.moveTo(x, y - s * 1.35); g.bezierCurveTo(x + s * 0.15, y - s * 0.7, x + s, y - s * 0.1, x + s * 0.8, y + s * 0.45); g.bezierCurveTo(x + s * 0.5, y + s * 1.1, x - s * 0.5, y + s * 1.1, x - s * 0.8, y + s * 0.45); g.bezierCurveTo(x - s, y - s * 0.1, x - s * 0.15, y - s * 0.7, x, y - s * 1.35); g.fill(); g.stroke();
    g.fillStyle = '#fff'; g.beginPath(); g.ellipse(x - s * 0.3, y + s * 0.3, s * 0.16, s * 0.28, 0.4, 0, 7); g.fill(); g.globalAlpha = 1;
  }
  if (o.vein > 0.3) {                    // the cross-popping anger mark, pulsing
    const s = r * 0.17 * (1 + 0.16 * Math.sin(t * 13)), x = head[0] - r * 0.74 * (side || 1), y = head[1] - r * 0.7;
    g.globalAlpha = Math.min(1, o.vein); g.strokeStyle = '#e8203a'; g.lineWidth = r * 0.055;
    for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + 0.3; const c = Math.cos(a), n = Math.sin(a); g.beginPath(); g.moveTo(x + c * s * 0.3 - n * s * 0.75, y + n * s * 0.3 + c * s * 0.75); g.quadraticCurveTo(x + c * s * 0.32, y + n * s * 0.32, x + c * s * 0.3 + n * s * 0.75, y + n * s * 0.3 - c * s * 0.75); g.stroke(); }
    g.globalAlpha = 1;
  }
  if (o.heart > 0.5 && front) for (const e of eyes) {
    g.fillStyle = `rgba(255,70,130,${(o.heart - 0.5) * 2 * front})`; g.strokeStyle = 'rgba(255,255,255,.9)'; g.lineWidth = Math.max(1, r * 0.018);
    heartPath(g, e[0], e[1], r * 0.2 * (1 + 0.12 * Math.sin(t * 7))); g.fill(); g.stroke();
  }
  if (o.sparkle > 0.3 && front) {
    g.fillStyle = `rgba(255,255,255,${Math.min(1, o.sparkle * 1.2) * front})`;
    for (const e of eyes) star(g, e[0] - r * 0.05, e[1] - r * 0.08, r * 0.075 * (0.8 + 0.3 * Math.sin(t * 8 + e[0])));
    g.fillStyle = `rgba(255,245,190,${Math.min(1, o.sparkle) * 0.95})`;
    for (let i = 0; i < 4; i++) { const a = i * 1.57 + 0.6 + t * 0.4; star(g, head[0] + Math.cos(a) * r * 1.35, head[1] + Math.sin(a) * r * 1.2, r * 0.11 * (0.5 + 0.6 * Math.abs(Math.sin(t * 3 + i)))); }
  }
  g.restore();
}
