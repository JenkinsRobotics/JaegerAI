// Copied from JaegerAvatar app/web/kin/styles.js (commit e041f0c), now Omni's own file.
// Character styles: how a character looks on any display body. The animation is the shared face stream from
// eyes.js (moods, reactions, blinks, gaze, lip sync); a style only changes how that stream is drawn, so a
// character keeps every expression on every screen. Everything is drawn in the 1024x640 face space and
// fitted to the screen, square (JP01) or wide (Momo/Mochi).
import { drawFace, path } from './eyes.js';
import { FACES, FACE_CHOICES, mouthShape, waveLine } from './jp01.js';

const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, Number.isFinite(v) ? v : a)), mix = (a, b, u) => a + (b - a) * u;

// eye: pill (Mochi) | anime | visor. mouth: none | smile | cat | grille | wave. tint: the character's own colour.
export const STYLES = {
  mochi: { label: 'Mochi', eye: 'pill', mouth: 'none' },
  jp01: { label: 'JP01', eye: 'pill', mouth: 'smile', tint: [130, 185, 255], tintMix: .5 },
  vita: { label: 'Vita', eye: 'anime', mouth: 'cat', tint: [95, 232, 222], tintMix: .6, accent: [255, 112, 178] },
};
// Locked looks ship in the character's pack (looks/screen.json) as data for this renderer version. A host
// that can't draw the version a pack asks for shows its own face instead of an approximation.
export const RENDERER = 'screen-face/1';
export const fromPack = (s, label) => ({ label, eye: s.eye, mouth: s.mouth, tint: s.tint, tintMix: s.tint_mix, accent: s.accent });

// The character's colour at rest; a strong mood colour (love pink, angry orange) still shows through.
const REST = [190, 255, 225];
export function tint(p, style) {
  const own = style.tint, moodPull = clamp(Math.hypot(p.red - REST[0], p.green - REST[1], p.blue - REST[2]) / 120);
  const u = own ? (style.tintMix ?? .5) * (1 - .7 * moodPull) : 0;
  return [p.red, p.green, p.blue].map((c, i) => Math.round(clamp(mix(c, own?.[i] ?? c, u), 0, 255)));
}
const rgb = (c, a = 1) => `rgba(${c.map(Math.round).join(',')},${a})`;
const shaped = p => Math.max(clamp(p.heart), clamp(p.star));   // a heart or star eye hides pupils and highlights

const EYES = {
  pill: () => null,                                            // drawFace's own Mochi eye
  anime: style => (ctx, p, side, color, contour) => {
    const ys = contour.map(q => q[1]), open = Math.max(...ys) - Math.min(...ys), a = 1 - clamp(shaped(p) / .6);
    ctx.save(); ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 17; path(ctx, contour); ctx.fill(); ctx.shadowBlur = 0;
    if (open > 18 && a > 0) {                                  // pupil and two highlights, cut by the lids
      ctx.clip(); ctx.globalAlpha = a;
      const k = 1 - .55 * clamp(p.ring);                          // surprise shrinks the pupils
      ctx.fillStyle = 'rgba(12,16,44,.88)'; ctx.beginPath(); ctx.ellipse(0, p.height * .14, p.width * .52 * k, p.height * .62 * k, 0, 0, 7); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.ellipse(-p.width * .3, -p.height * .3, p.width * .24, p.height * .2, -.4, 0, 7); ctx.fill();
      ctx.beginPath(); ctx.arc(p.width * .3, p.height * .32, p.width * .1, 0, 7); ctx.fill();
    }
    ctx.restore();
    if (open > 6) {                                            // a heavy upper lash with a flick at the outer corner
      const top = [...contour.slice(contour.length / 2), contour[0]], end = side > 0 ? top[top.length - 1] : top[0];
      ctx.save(); ctx.strokeStyle = rgb(style.accent ?? [255, 255, 255], .95); ctx.lineWidth = 14; ctx.lineCap = ctx.lineJoin = 'round';
      path(ctx, top); ctx.stroke(); ctx.beginPath(); ctx.moveTo(...end); ctx.lineTo(end[0] + side * 26, end[1] - 22); ctx.stroke(); ctx.restore();
    }
  },
  visor: () => (ctx, p, side, color, contour) => {
    ctx.save(); ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 12; path(ctx, contour); ctx.fill(); ctx.shadowBlur = 0;
    const s = Math.min(p.width, p.height) * .62 * (1 - clamp(shaped(p) / .6)) * (1 - .6 * clamp(p.ring));   // surprise: pinpoint pupils
    if (s > 4) { ctx.clip(); ctx.fillStyle = '#080808'; ctx.fillRect(clamp((p.x || 0) / 54, -1, 1) * p.width * .3 - s / 2, -s / 2, s, s); }   // square pupils look where the eyes look
    ctx.restore();
  },
};

const MOUTHS = {
  none: null,
  smile(ctx, p, v, jaw, t, color) {
    const { open, width, flat } = mouthShape(v, jaw), cx = 512 + (p.x || 0) * .5, cy = 505 + (p.y || 0) * .4;
    ctx.strokeStyle = ctx.fillStyle = color; ctx.lineWidth = 22;
    if (open < .08) { const dip = clamp(26 + (p.curve || 0) * .6, -20, 48); ctx.beginPath(); ctx.moveTo(cx - 75, cy); ctx.quadraticCurveTo(cx, cy + dip * 2, cx + 75, cy); ctx.stroke(); }
    else { ctx.beginPath(); ctx.ellipse(cx, cy + 12, 70 * width, 12 + 70 * open * (1 - .35 * flat), 0, 0, 7); ctx.globalAlpha = .22; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke(); }
  },
  cat(ctx, p, v, jaw, t, color, style) {                       // a small ω that opens into a rounded "D"
    const { open, width } = mouthShape(v, jaw), cx = 512 + (p.x || 0) * .5, cy = 500 + (p.y || 0) * .4, w = 62 * Math.max(.75, width);
    const dip = clamp(1 + (p.curve || 0) / 30, -.6, 2) * 26;
    ctx.strokeStyle = color; ctx.lineWidth = 13;
    if (open > .08) {
      ctx.beginPath(); ctx.moveTo(cx - w, cy); ctx.quadraticCurveTo(cx, cy + 10, cx + w, cy); ctx.quadraticCurveTo(cx + w * .8, cy + 30 + 110 * open, cx, cy + 34 + 115 * open);
      ctx.quadraticCurveTo(cx - w * .8, cy + 30 + 110 * open, cx - w, cy); ctx.fillStyle = rgb(style.accent ?? [255, 120, 170], .9); ctx.fill(); ctx.stroke();
    } else { ctx.beginPath(); ctx.moveTo(cx - w, cy); ctx.quadraticCurveTo(cx - w / 2, cy + dip, cx, cy); ctx.quadraticCurveTo(cx + w / 2, cy + dip, cx + w, cy); ctx.stroke(); }
  },
  grille(ctx, p, v, jaw, t, color) {                           // a rounded grille of teeth that opens with each syllable
    const { open, width } = mouthShape(v, jaw), cx = 512 + (p.x || 0) * .4, cy = 500 + (p.y || 0) * .3, w = 300 * clamp(width, .8, 1.25), h = 64 + 96 * open;
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(clamp(p.asym || 0, -1, 1) * .12 - clamp(-(p.curve || 0) / 40, -.5, .5) * .05);
    ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 14; ctx.beginPath(); ctx.roundRect(-w / 2, -h / 2, w, h, h / 2); ctx.fill(); ctx.shadowBlur = 0;
    ctx.strokeStyle = '#141414'; ctx.lineWidth = 7; ctx.beginPath();
    for (let i = 1; i < 6; i++) { const x = -w / 2 + w * i / 6; ctx.moveTo(x, -h / 2); ctx.lineTo(x, h / 2); }
    for (const y of open > .25 ? [-h / 6, h / 6] : [0]) { ctx.moveTo(-w / 2, y); ctx.lineTo(w / 2, y); }
    ctx.stroke(); ctx.restore();
  },
  wave(ctx, p, v, jaw, t, color) {
    ctx.strokeStyle = color; ctx.shadowColor = color; ctx.lineCap = ctx.lineJoin = 'round';
    for (const [lw, blur, alpha] of [[26, 30, .35], [13, 16, 1]]) {
      ctx.lineWidth = lw; ctx.shadowBlur = blur; ctx.globalAlpha = alpha; ctx.beginPath();
      waveLine(v, jaw, t).forEach(([x, y], i) => ctx[i ? 'lineTo' : 'moveTo'](512 + (p.x || 0) * .5 + x * 380, 505 + y * 95)); ctx.stroke();
    }
  },
};

// Square screens get a bigger, compact face lifted for the mouth; wide ones a slightly smaller face.
function fit(ctx, style, layout = {}) {
  const W = ctx.canvas.width, H = ctx.canvas.height;
  if (style.mouth === 'none' && !style.band) return layout;
  return H / W > .8 ? { scale: (layout.scale || 1.55) * .92, spread: layout.spread ?? .8, dy: -110 * H / 1024 } : { scale: .86, spread: 1, dy: -46 * H / 640 };
}
function inFace(ctx, L, draw) {
  const W = ctx.canvas.width, H = ctx.canvas.height;
  ctx.save(); ctx.translate(W / 2, H / 2 + (L.dy || 0)); ctx.scale(L.scale || 1, L.scale || 1); ctx.translate(-512, -320); draw(); ctx.restore();
}

export function styledFace(style) {
  const eye = EYES[style.eye]?.(style), mouth = MOUTHS[style.mouth];
  return {
    paint(ctx, p, jaw, { t = 0, v = {}, layout = {} } = {}) {
      const col = tint(p, style), L = fit(ctx, style, layout), q = { ...p, red: col[0], green: col[1], blue: col[2] };
      if (style.eye === 'visor') { q.height *= .8; q.width *= 1.08; }   // round eyes behind a visor
      drawFace(ctx, q, t, { ...L, eye });
      if (p.width <= 1) return col;                            // JP01's wake: dark until the eyes open
      inFace(ctx, L, () => {
        if (style.eye === 'visor') {                           // the visor band is hardware: it follows the eyes only a little
          const half = q.spread * (L.spread ?? 1) + q.width * 1.45, y = 288 + (p.y || 0) * .3;
          ctx.save(); ctx.strokeStyle = rgb(col, .55); ctx.lineWidth = 14; ctx.beginPath(); ctx.roundRect(512 - half, y - 128, half * 2, 256, 128); ctx.stroke();
          ctx.globalCompositeOperation = 'destination-over'; ctx.fillStyle = rgb(col, .1); ctx.fill(); ctx.restore();
        }
        if (mouth) { ctx.save(); mouth(ctx, q, v, jaw, t, rgb(col), style); ctx.restore(); }
      });
      return col;
    },
  };
}
for (const [id, style] of Object.entries(STYLES)) {
  FACES['style:' + id] = styledFace(style);
  FACE_CHOICES.push(['style:' + id, `${style.label} style`]);
}
