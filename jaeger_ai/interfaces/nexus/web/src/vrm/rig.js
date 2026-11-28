import { MOVES, moveNow } from './motion.js';
import { REACTIONS } from './eyes.js';
// The face rig: one small vector of numbers drives every renderer (OLED, visor, anime, 3D, later a robot).
// Layers: emotion pose + idle life + gestures + audio-driven speech, each channel settled by its own spring.
const grp = {
  mouth: [700, 0.95], lids: [380, 0.75], brow: [300, 0.55], gaze: [1400, 0.9],
  shape: [220, 0.75], head: [70, 0.55], body: [170, 0.42], tone: [30, 1],
};
//           name: [rest, group]
const CH = {
  lipAA:[0,'mouth'],lipEE:[0,'mouth'],lipIH:[0,'mouth'],lipOH:[0,'mouth'],lipOU:[0,'mouth'],
  lidL: [1, 'lids'], lidR: [1, 'lids'], low: [0, 'lids'], arc: [0, 'lids'], squeeze: [0, 'lids'], heart: [0, 'lids'], pupil: [1, 'lids'],
  browL: [0, 'brow'], browR: [0, 'brow'], tilt: [0, 'brow'],
  gazeX: [0, 'gaze'], gazeY: [0, 'gaze'],
  jaw: [0, 'mouth'], wide: [0, 'mouth'], round: [0, 'mouth'], teeth: [0, 'mouth'],
  smile: [0.1, 'shape'], mouthX: [0, 'shape'],
  yaw: [0, 'head'], pitch: [0, 'head'], roll: [0, 'head'], lean: [0, 'head'],
  crouch: [0, 'body'], lift: [0, 'body'], wave: [0, 'body'], hand: [0, 'body'], shrug: [0, 'body'], type: [0, 'body'],
  blush: [0, 'tone'], glow: [1, 'tone'], sparkle: [0, 'tone'], tear: [0, 'tone'], sweat: [0, 'tone'], vein: [0, 'tone'], droop: [0, 'tone'],
  tintR: [0.35, 'tone'], tintG: [0.8, 'tone'], tintB: [1, 'tone'],
};
export const CHANNELS = Object.keys(CH);
export const GROUP = Object.fromEntries(CHANNELS.map(k => [k, CH[k][1]])), REST = Object.fromEntries(CHANNELS.map(k => [k, CH[k][0]]));

// `a` = arousal: scales how hard speech emphasis kicks the body. `s` = transition speed. `c` = tint.
export const EMOTIONS = {
  neutral: { a: 0.8 },
  joy: { a: 1.1, smile: 0.8, lidL: 1.05, lidR: 1.05, low: 0.35, browL: 0.25, browR: 0.25, tilt: 0.12, pitch: 0.12, blush: 0.35, sparkle: 0.3, c: [0.4, 0.9, 1] },
  excited: { a: 1.5, s: 1.5, smile: 1, lidL: 1.2, lidR: 1.2, browL: 0.55, browR: 0.55, tilt: 0.1, pupil: 1.25, sparkle: 1, crouch: -0.1, lift: 0.2, pitch: 0.18, blush: 0.5, c: [0.45, 1, 0.85] },
  love: { a: 0.9, s: 0.8, heart: 1, smile: 0.7, blush: 1, tilt: 0.3, roll: 0.14, sparkle: 0.5, browL: 0.2, browR: 0.2, c: [1, 0.42, 0.68] },
  sad: { a: 0.35, s: 0.6, smile: -0.65, lidL: 0.72, lidR: 0.72, tilt: 0.85, browL: -0.1, browR: -0.1, pitch: -0.32, gazeY: -0.3, droop: 1, tear: 0.55, lift: -0.2, glow: 0.7, crouch: 0.08, c: [0.3, 0.5, 1] },
  angry: { a: 1.3, s: 1.4, smile: -0.6, lidL: 0.85, lidR: 0.85, low: 0.28, tilt: -1, browL: -0.5, browR: -0.5, pitch: -0.2, pupil: 0.72, vein: 1, crouch: 0.08, c: [1, 0.22, 0.16] },
  surprised: { a: 1.4, s: 2.2, lidL: 1.35, lidR: 1.35, browL: 1, browR: 1, pupil: 0.68, jaw: 0.34, round: 0.75, crouch: -0.15, lift: 0.25, pitch: 0.12, c: [0.65, 0.9, 1] },
  scared: { a: 1.2, s: 1.8, lidL: 1.25, lidR: 1.25, browL: 0.6, browR: 0.6, tilt: 0.85, pupil: 0.6, smile: -0.4, sweat: 1, crouch: 0.12, pitch: -0.1, lean: -0.5, c: [0.75, 0.75, 1] },
  thinking: { a: 0.5, s: 0.8, gazeX: 0.45, gazeY: 0.55, lidL: 0.88, lidR: 0.92, browL: 0.5, browR: -0.1, mouthX: 0.4, smile: -0.04, roll: 0.09, c: [1, 0.72, 0.28] },
  confused: { a: 0.7, browL: 0.7, browR: -0.35, tilt: 0.2, roll: 0.18, mouthX: -0.35, smile: -0.2, sweat: 0.5, gazeX: -0.15, c: [0.75, 0.6, 1] },
  shy: { a: 0.45, s: 0.8, gazeY: -0.5, gazeX: 0.35, blush: 1, smile: 0.32, lidL: 0.84, lidR: 0.84, roll: 0.11, pitch: -0.2, tilt: 0.35, c: [1, 0.55, 0.7] },
  smug: { a: 0.7, lidL: 0.68, lidR: 0.7, low: 0.2, smile: 0.5, mouthX: 0.55, browL: 0.38, browR: -0.05, roll: -0.07, pitch: 0.16, c: [0.55, 1, 0.55] },
  sleepy: { a: 0.25, s: 0.4, lidL: 0.34, lidR: 0.38, browL: -0.2, browR: -0.2, pitch: -0.25, roll: 0.1, droop: 0.5, glow: 0.55, c: [0.35, 0.45, 0.8] },
  laughing: { a: 1.6, s: 1.8, arc: 1, smile: 1, jaw: 0.25, browL: 0.5, browR: 0.5, tilt: 0.3, pitch: 0.28, blush: 0.75, c: [0.5, 1, 0.8] },
  singing: { a: 1.2, s: 1.1, smile: 0.5, lidL: 0.95, lidR: 0.95, browL: 0.3, browR: 0.3, tilt: 0.28, blush: 0.3, sparkle: 0.5, c: [0.75, 0.55, 1] },
  listening: { a: 0.6, s: 1.2, lidL: 1.06, lidR: 1.06, browL: 0.16, browR: 0.16, smile: 0.16, lean: 0.6, c: [0.4, 0.85, 1] },
};

// Additive clips: fn(u 0..1, t seconds, tgt). env() gives soft in/out.
const env = (u, a = 0.15, b = 0.25) => Math.min(1, u / a) * Math.min(1, (1 - u) / b);
export const GESTURES = {
  nod: [0.7, (u, t, o) => { o.pitch += -0.32 * Math.sin(t * 15) * env(u); }],
  shake: [0.8, (u, t, o) => { o.yaw += 0.42 * Math.sin(t * 13) * env(u); o.smile -= 0.1; }],
  tilt: [1.3, (u, t, o) => { o.roll += 0.3 * env(u); o.browL += 0.25 * env(u); }],
  wink: [0.6, (u, t, o) => { const e = env(u, 0.2, 0.35); o.lidR -= 1.15 * e; o.smile += 0.35 * e; o.mouthX += 0.4 * e; o.browL += 0.3 * e; o.roll -= 0.08 * e; }],
  wave: [2.2, (u, t, o) => { const e = env(u, 0.14, 0.2); o.wave += e; o.smile += 0.3 * e; o.roll += 0.06 * e; o.browL += 0.15 * e; o.browR += 0.15 * e; }],
  shrug: [1, (u, t, o) => { const e = env(u); o.shrug += e; o.browL += 0.6 * e; o.browR += 0.6 * e; o.tilt += 0.4 * e; o.lift += 0.3 * e; o.roll += 0.1 * e; o.smile -= 0.3 * e; }],
  bounce: [0.9, (u, t, o) => { o.lift += 0.5 * Math.abs(Math.sin(t * 10)) * env(u); o.crouch += 0.1 * Math.cos(t * 20) * env(u); }],
  gasp: [0.85, (u, t, o) => {
    if (t < 0.12) { o.crouch += 0.2; o.lidL -= 0.3; o.lidR -= 0.3; }   // anticipation
    else { const e = env(u, 0.15, 0.4); o.lidL += 0.35 * e; o.lidR += 0.35 * e; o.browL += 0.8 * e; o.browR += 0.8 * e; o.crouch -= 0.2 * e; o.lift += 0.3 * e; o.lean -= 0.5 * e; }
  }],
  sigh: [1.3, (u, t, o) => { const e = env(u, 0.3, 0.4); o.lidL -= 0.35 * e; o.lidR -= 0.35 * e; o.pitch -= (u < 0.3 ? -0.15 : 0.25) * e; o.tilt += 0.5 * e; o.crouch += (u < 0.3 ? -0.08 : 0.12) * e; o.lift -= 0.1 * e; }],
  think: [0.8, (u, t, o) => { const e = env(u); o.gazeY += 0.4 * e; o.gazeX -= 0.4 * e; o.browL += 0.4 * e; o.mouthX -= 0.4 * e; o.smile -= 0.1 * e; }],
};

const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
export const SNAP = (x, steps) => steps.reduce((best, s) => (Math.abs(s - x) < Math.abs(best - x) ? s : best), steps[0]);
const blinkCurve = t => t < 0.07 ? t / 0.07 : t < 0.09 ? 1 : t < 0.23 ? 1 - (t - 0.09) / 0.14 : 0;

export class Rig {
  constructor() {
    this.x = {}; this.v = {}; this.tgt = {}; this.out = {};
    for (const k of CHANNELS) { this.x[k] = CH[k][0]; this.v[k] = 0; this.out[k] = CH[k][0]; }
    this.t = 0;
    this.emotion = 'neutral'; this.intensity = 1; this.speed = 1;
    this.voice = null; this.gestures = []; this.fx = [];
    this.fix = { x: 0, y: 0 }; this.micro = { x: 0, y: 0 }; this.nextFix = 1; this.nextMicro = 0.5;
    this.blinkAt = -1; this.nextBlink = 2; this.attn = { x: 0, y: 0, at: -99 };
    this.mode = 'idle'; this.relaxAt = Infinity; this.typingUntil = 0; this.hearingUntil = 0;
    this.sway = null; this.fxTimer = 0; this.sinceEmph = 9;
    this.energy = 1; this.emotionAt = -9; this.reaction = null; this.act = null; this.next = null; this.attentive = false; this.puppet = null;
    this.bones = { chestYaw: [0, 0], chestPitch: [0, 0], chestRoll: [0, 0], shL: [0, 0], shR: [0, 0], hipX: [0, 0] };
  }

  setEmotion(name, intensity = 1) {
    if (!EMOTIONS[name]) return;
    const changed = name !== this.emotion;
    this.emotion = name; this.intensity = intensity; this.speed = EMOTIONS[name].s ?? 1;
    this.relaxAt = Infinity;
    if (!changed) return;
    this.emotionAt = this.t;
    this.blink();                                  // humans blink on a change of mind
    this.kick('crouch', 1.4 * (EMOTIONS[name].a ?? 1));   // a small dip of the spine before the pose lands
    if (name === 'surprised') this.emit('!', 1, { size: 1.5 });
    if (name === 'confused') this.emit('?', 1, { size: 1.4 });
    if (name === 'angry') this.emit('#', 2, { size: 1.1 });
  }
  relaxIn(sec) { this.relaxAt = this.t + (this.emotion === 'surprised' || this.emotion === 'scared' ? Math.min(sec, 1.2) : sec); }
  kick(k, vel) { this.v[k] += vel; }
  gesture(name, dur) { const g = GESTURES[name]; if (g) this.gestures.push({ fn: g[1], t: 0, dur: dur ?? g[0] }); }
  blink() { if (this.t - this.blinkAt > 0.25) { this.blinkAt = this.t; this.nextBlink = rand(2.2, 5.5); } }
  look(x, y) { this.attn = { x: clamp(x, -1, 1), y: clamp(y, -1, 1), at: this.t }; }
  typing() {
    this.typingUntil = this.t + 1.6;
    if (this.mode === 'idle') this.kick('pitch', -0.25);
    if (this.t - this.blinkAt > 1.5 && Math.random() < 0.15) this.blink();
  }
  // A full-body move is not snapped off: a new one eases the running one out over a quarter of a second (as Stop does,
  // so its feet land where they should), then starts. Asked again for the move she is already making, she carries on.
  // An eye reaction can be cut off by the next one: the eyes' springs carry it over.
  // ponytail: one move waits, the latest asked for; a longer line if a scene needs three in a row.
  move(name) {
    if (!MOVES[name]) return;
    if (!this.act) return void (this.act = { name, age: 0 });
    if (this.act.name === name && this.act.stop === undefined) return;
    this.next = name;
    if (this.act.stop === undefined) this.act.stop = 0;
  }
  react(name) { if (REACTIONS[name]) this.reaction = { name, age: 0 }; }
  stopMove() { this.next = null; if (this.act && this.act.stop === undefined) this.act.stop = 0; }
  listen() { this.hearingUntil = this.t + 0.4; }   // someone is talking to her: eye contact and the attentive face, no hands on a keyboard
  // Called by the performer on each voiced onset: small velocity impulses, so overshoot comes from the springs.
  emphasis(s) {
    const a = (EMOTIONS[this.emotion].a ?? 1) * s;
    this.kick('browL', 3.2 * a); this.kick('browR', 3.2 * a);
    this.kick('pitch', -1.3 * a); this.kick('crouch', 2.1 * a); this.kick('lift', 1.2 * a);
    this.kick('roll', rand(-0.5, 0.5) * a);
    this.kick('hand', 3 * a);
    this.sinceEmph = 0;
    if (this.emotion === 'laughing') {
      this.kick('pitch', 2.6 * s); this.kick('roll', rand(-1.6, 1.6) * s); this.kick('crouch', 2 * s);
      if (this.t - (this.lastHa ?? -9) > 0.5) { this.emit('ha', 1, { size: 0.9 }); this.lastHa = this.t; }
    }
    if (this.emotion === 'singing') this.emit(Math.random() < 0.5 ? '♪' : '♫', 1);
  }
  beat(i) {
    if (i % 2 === 0) { this.kick('crouch', 1.3); this.kick('lift', 0.9); }
  }
  emit(glyph, n = 1, { size = 1 } = {}) {
    for (let i = 0; i < n; i++) {
      const side = Math.random() < 0.5 ? -1 : 1;
      this.fx.push({ glyph, x: side * rand(0.55, 0.85), y: rand(-0.75, -0.15), vx: side * rand(0.02, 0.1), vy: -rand(0.18, 0.34), age: 0, life: rand(1.1, 1.8), size: size * rand(0.85, 1.15), rot: rand(-0.3, 0.3) });
    }
  }

  tick(dt) {
    dt = Math.min(dt, 1 / 20);
    this.t += dt; this.sinceEmph += dt;
    const t = this.t, tg = this.tgt, pose = EMOTIONS[this.emotion], I = this.intensity * this.energy, v = this.voice;
    if (t > this.relaxAt) { this.setEmotion('neutral'); }

    const hearing = t < this.hearingUntil && this.mode !== 'speaking';
    const listening = hearing || (this.mode === 'idle' && t < this.typingUntil);
    this.attentive = listening;
    const base = listening && this.emotion === 'neutral' ? EMOTIONS.listening : pose;
    for (const k of CHANNELS) { const r = CH[k][0]; tg[k] = r + ((base[k] ?? r) - r) * I; }
    if (base.c) { [tg.tintR, tg.tintG, tg.tintB] = base.c; }

    // gaze: fixations with micro-saccades; attention follows the person's pointer
    if ((this.nextFix -= dt) <= 0) {
      const m = this.mode;
      const hasAttn = t - this.attn.at < 6;
      let fx = hasAttn ? this.attn.x : 0, fy = hasAttn ? this.attn.y : 0;
      if (m === 'thinking') { fx = rand(-0.5, 0.5); fy = rand(0.0, 0.5); this.nextFix = rand(0.45, 1.1); }
      else if (m === 'speaking') { if (Math.random() < 0.28) { fx += rand(-0.35, 0.35); fy += rand(-0.1, 0.25); } this.nextFix = rand(0.9, 2.4); }
      else { if (!listening && Math.random() < 0.4) { fx = rand(-0.55, 0.55); fy = rand(-0.3, 0.3); } this.nextFix = rand(1.2, 3.5); }
      if (Math.hypot(fx - this.fix.x, fy - this.fix.y) > 0.35 && Math.random() < 0.35) this.blink();
      this.fix = { x: fx, y: fy };
    }
    if ((this.nextMicro -= dt) <= 0) { this.micro = { x: rand(-0.035, 0.035), y: rand(-0.03, 0.03) }; this.nextMicro = rand(0.3, 0.9); }
    if (t - this.attn.at < 1.2) this.fix = { x: this.attn.x, y: this.attn.y };
    tg.gazeX += this.fix.x + this.micro.x;
    tg.gazeY += this.fix.y + this.micro.y;

    // eyes lead, head follows; slow perlin-ish drift keeps her from freezing
    tg.yaw += tg.gazeX * 0.42 + 0.05 * Math.sin(t * 0.37) + 0.03 * Math.sin(t * 0.91 + 1);
    tg.pitch += tg.gazeY * 0.28 + 0.03 * Math.sin(t * 0.53 + 2);
    tg.roll += 0.025 * Math.sin(t * 0.43 + 4);
    tg.crouch += 0.012 * Math.sin(t * 1.7); tg.lift += 0.03 * Math.sin(t * 1.7 - 0.5);

    if (listening && !hearing) tg.type = 1;

    // speech layer
    if (v) {
      // a held-open pose (surprise) must not fight the words coming out of it
      tg.jaw = tg.jaw * 0.25 + v.open * 1.3; tg.wide += v.wide; tg.round = tg.round * 0.25 + v.round; tg.teeth = v.teeth;
      tg.smile *= 1 - 0.5 * v.round;
      const lift = v.pitch * v.energy;
      tg.browL += lift * 0.22 + (v.brow || 0) * 0.24; tg.browR += lift * 0.22 + (v.brow || 0) * 0.24;
      tg.pitch += lift * 0.07 - (v.nod || 0) * 0.10; tg.lift += v.energy * 0.03 + (v.nod || 0) * 0.04; tg.glow += v.energy * 0.22;
      if (this.emotion === 'laughing') {
        tg.squeeze = clamp((v.energy - 0.6) * 2.5, 0, 1) * 0.9;
        tg.tear = 0.3;
      }
      if (this.emotion === 'singing' && this.sinceEmph > 0.34 && v.energy > 0.45) {  // held note: eyes close, brows lift
        tg.lidL *= 0.55; tg.lidR *= 0.55; tg.tilt += 0.35; tg.browL += 0.2; tg.browR += 0.2;
      }
    }
    if (this.sway) {
      const b = (t - this.sway.t0) / this.sway.beat * Math.PI / 2;
      tg.yaw += 0.17 * Math.sin(b); tg.roll += 0.17 * Math.sin(b + 0.5);
    }
    if (this.mode === 'thinking') { tg.crouch += 0.012 * Math.sin(t * 5); tg.glow += 0.18 * Math.sin(t * 5); }

    this.gestures = this.gestures.filter(g => {
      g.t += dt; const u = g.t / g.dur;
      if (u >= 1) return false;
      g.fn(u, g.t, tg); return true;
    });
    if (this.reaction && (this.reaction.age += dt) > REACTIONS[this.reaction.name]) this.reaction = null;
    if (this.act) {
      if (this.act.stop === undefined) this.act.age += dt; else this.act.stop += dt / 0.25;
      const m = this.act.stop >= 1 ? null : moveNow(this.act);
      if (!m) { this.act = this.next ? { name: this.next, age: 0 } : null; this.next = null; }
      else { tg.smile += (m.pose.smile - 0.1) * m.weight * 0.6; tg.blush += (m.pose.heart ?? 0) * 0.6; }
    }
    // A plugin, such as webcam tracking, can drive the face. Her voice keeps the mouth while she talks.
    if (this.puppet) {
      const P = this.puppet;
      tg.yaw = P.yaw; tg.pitch = P.pitch; tg.roll = P.roll; tg.gazeX = P.gazeX; tg.gazeY = P.gazeY;
      tg.lidL = Math.min(tg.lidL, 1.05 - P.blinkL); tg.lidR = Math.min(tg.lidR, 1.05 - P.blinkR);
      tg.browL += P.brow; tg.browR += P.brow; tg.smile = Math.max(tg.smile, P.smile);
      if (!v) { tg.jaw = P.jaw; tg.wide = P.wide; tg.round = P.round; }
    }

    for(const key of ['aa','ee','ih','oh','ou'])tg['lip'+key.toUpperCase()]=v?.vowels?.[key]||0;
    this.out.kinMouth=v?.vowels?1:0;

    // settle: two substeps keep the stiff mouth/gaze springs stable at low framerates
    const h = dt / 2;
    for (let n = 0; n < 2; n++) for (const k of CHANNELS) {
      const g = CH[k][1];
      let K = grp[g][0];
      if (g !== 'mouth' && g !== 'gaze' && g !== 'tone') K *= this.speed;
      else if (g === 'tone') K *= Math.min(this.speed, 1.5);
      const C = 2 * grp[g][1] * Math.sqrt(K);
      this.v[k] += (K * (tg[k] - this.x[k]) - C * this.v[k]) * h;
      this.x[k] += this.v[k] * h;
    }

    // output: springs + the things that must stay crisp (blink curve, lid-follows-gaze)
    if ((this.nextBlink -= dt) <= 0) { this.blinkAt = t; this.nextBlink = rand(2.2, 5.5) * (Math.random() < 0.2 ? 0.12 : 1); }
    const b = blinkCurve(t - this.blinkAt);
    const o = this.out, x = this.x;
    for (const k of CHANNELS) o[k] = x[k];
    const couple = x.gazeY * 0.1;
    o.lidL = Math.max(0, (x.lidL + couple) * (1 - b));
    o.lidR = Math.max(0, (x.lidR + couple) * (1 - b));
    o.jaw = clamp(x.jaw, 0, 1); o.wide = clamp(x.wide, 0, 1); o.round = clamp(x.round, 0, 1);
    o.teeth = clamp(x.teeth, 0, 1); o.blink = b;
    const shut = v?.shut || 0, tuck = v?.tuck || 0;   // lip closures land on time, past the springs, like a blink
    if (shut || tuck) {
      const k = 1 - shut;
      o.jaw = o.jaw * k * (1 - tuck) + tuck * 0.06; o.wide *= k; o.round *= k * (1 - tuck); o.teeth = Math.max(o.teeth * k, tuck);
      for (const key of ['lipAA', 'lipEE', 'lipIH', 'lipOH', 'lipOU']) o[key] *= k * (1 - tuck);
    }
    o.blinkL = b; o.blinkR = blinkCurve(t - this.blinkAt - 0.02);   // no two eyes close on quite the same frame
    o.blush = clamp(x.blush, 0, 1); o.arc = clamp(x.arc, 0, 1); o.squeeze = clamp(x.squeeze, 0, 1);
    o.heart = clamp(x.heart, 0, 1); o.low = clamp(x.low, 0, 1); o.sparkle = clamp(x.sparkle, 0, 1);
    o.energy = v ? v.energy : 0;
    o.vx = this.v.yaw + this.v.roll; o.vy = this.v.lift - this.v.crouch;

    // Skeleton: the channels say where the head and face want to be; the body follows through its joints, later and less.
    // Nothing is scaled. A nod turns the head on its neck, a laugh shakes the shoulders, a breath lifts the ribs.
    const follow = (bone, want, K, zeta = 0.75) => {
      const b_ = this.bones[bone];
      b_[1] += (K * (want - b_[0]) - 2 * zeta * Math.sqrt(K) * b_[1]) * dt; b_[0] += b_[1] * dt;
      return b_[0];
    };
    const voiced = v ? v.energy : 0;
    o.breath = Math.sin(t * 1.5 + Math.sin(t * 0.37) * 0.8) * (1 - voiced * 0.6);
    o.chestYaw = follow('chestYaw', x.yaw * 0.42, 34);
    o.chestPitch = follow('chestPitch', x.pitch * 0.26 - x.crouch * 0.75 + x.lean * 0.14, 40, 0.7);
    o.chestRoll = follow('chestRoll', x.roll * 0.4 + 0.012 * Math.sin(t * 0.41), 30);
    const laughShake = this.emotion === 'laughing' ? voiced * 0.5 * Math.sin(t * 19) : 0;
    const raise = x.lift * 0.5 - x.crouch * 0.5 + x.shrug + o.breath * 0.05 + laughShake + voiced * 0.05;
    o.shL = follow('shL', raise + x.roll * 0.35 + x.hand * 0.04, 90, 0.6);
    o.shR = follow('shR', raise - x.roll * 0.35 + x.hand * 0.1, 90, 0.6);
    o.hipX = follow('hipX', 0.5 * Math.sin(t * 0.29) + x.yaw * 0.3, 8);
    o.crouch = x.crouch;

    this.fxTimer -= dt;
    if (this.fxTimer <= 0) {
      this.fxTimer = 0.7;
      if (this.emotion === 'love') this.emit('♥');
      if (this.emotion === 'sleepy') this.emit('z');
      if (this.mode === 'thinking') this.emit('…', 1, { size: 1.2 });
      if (this.act?.name === 'celebrate') this.emit('✦', 2);
      if (this.act?.name === 'heart') this.emit('♥');
    }
    for (const f of this.fx) { f.age += dt; f.x += f.vx * dt; f.y += f.vy * dt; }
    this.fx = this.fx.filter(f => f.age < f.life);
    return o;
  }
}

// Particles are the one thing each renderer shares verbatim.
export function drawFx(ctx, rig, cx, cy, scale, color, font = '600 1px system-ui, sans-serif') {
  ctx.save();
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const f of rig.fx) {
    const u = f.age / f.life, s = scale * 0.2 * f.size * Math.min(1, u * 6);
    ctx.save();
    ctx.translate(cx + f.x * scale, cy + f.y * scale);
    ctx.rotate(f.rot);
    ctx.scale(s, s);
    ctx.font = font;
    ctx.globalAlpha = Math.min(1, (1 - u) * 2.5);
    ctx.fillStyle = color;
    ctx.fillText(f.glyph, 0, 0);
    ctx.restore();
  }
  ctx.restore();
}
