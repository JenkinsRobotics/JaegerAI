// Audio side of the performance. Pure JS (no DOM, no WebAudio) so it also runs in the node test.
//   analyze(): any audio -> mouth/prosody track. Works on any TTS, so the voice stays swappable.
//   synth*():  source-filter voice for what TTS can't do: laughing, gasps, singing, babble fallback.
export const SR = 22050;
const TAU = Math.PI * 2;
const sat = x => Math.max(0, Math.min(1, x));

function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -TAU / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const c = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = c;
      }
    }
  }
}

// Power-weighted centroid of the spectrum in a band: steadier than peak picking on harmonics.
function centroid(pow, df, lo, hi) {
  let s = 0, w = 0;
  for (let i = Math.ceil(lo / df); i <= hi / df; i++) { const p = pow[i] ** 2; s += p; w += p * i * df; }
  return s > 0 ? w / s : (lo + hi) / 2;
}

// F2 from an LPC envelope: the first resonance above F1. A spectral centroid reads neural voices'
// breathy highs as a raised tongue, which turned every "oo" into a smile.
function secondFormant(x, at, sr, f1) {
  const n = 256, order = 10, y = new Float64Array(n), r = new Float64Array(order + 1), a = new Float64Array(order + 1);
  for (let i = 0; i < n; i++) {                      // decimate by 2, pre-emphasis, window
    const s = ((x[at + i * 2] || 0) + (x[at + i * 2 + 1] || 0)) / 2, p = ((x[at + i * 2 - 2] || 0) + (x[at + i * 2 - 1] || 0)) / 2;
    y[i] = (s - 0.9 * p) * (0.5 - 0.5 * Math.cos(TAU * i / n));
  }
  for (let k = 0; k <= order; k++) for (let i = k; i < n; i++) r[k] += y[i] * y[i - k];
  if (r[0] < 1e-9) return 0;
  a[0] = 1;
  let e = r[0] * 1.001;
  for (let i = 1; i <= order; i++) {                 // Levinson-Durbin
    let k = r[i];
    for (let j = 1; j < i; j++) k += a[j] * r[i - j];
    k = -k / e;
    const t = a.slice();
    for (let j = 1; j < i; j++) t[j] = a[j] + k * a[i - j];
    t[i] = k; a.set(t); e *= 1 - k * k;
  }
  const M = 128, env = new Float64Array(M), from = Math.max(700, f1 * 1.25);
  for (let m = 0; m < M; m++) {
    let re = 0, im = 0;
    for (let k = 0; k <= order; k++) { re += a[k] * Math.cos(k * Math.PI * m / M); im -= a[k] * Math.sin(k * Math.PI * m / M); }
    env[m] = 1 / (re * re + im * im);
    const hz = (m - 1) * sr / 4 / M;
    if (m > 1 && hz > from && env[m - 1] > env[m] && env[m - 1] > env[m - 2]) return hz;
  }
  return 0;
}

function pitchOf(x, at, N, sr) {
  const minLag = Math.floor(sr / 650), maxLag = Math.min(Math.floor(sr / 75), N / 2);
  let e0 = 1e-9, best = 0, bestLag = 0;
  for (let i = 0; i < N - maxLag; i += 2) e0 += x[at + i] * x[at + i];
  for (let lag = minLag; lag < maxLag; lag++) {
    let c = 0;
    for (let i = 0; i < N - maxLag; i += 2) c += x[at + i] * x[at + i + lag];
    if (c > best) { best = c; bestLag = lag; }
  }
  return best / e0 > 0.45 ? sr / bestLag : 0;
}

export function analyze(x, sr = SR) {
  const N = 512, hop = Math.round(sr * 0.01), count = Math.max(1, Math.floor((x.length - N) / hop));
  const df = sr / N, win = Float64Array.from({ length: N }, (_, i) => 0.5 - 0.5 * Math.cos(TAU * i / N));
  const re = new Float64Array(N), im = new Float64Array(N), pow = new Float64Array(N / 2);
  const rms = new Float32Array(count), f1 = new Float32Array(count), f2 = new Float32Array(count);
  const hiR = new Float32Array(count), f0 = new Float32Array(count);
  for (let f = 0; f < count; f++) {
    const at = f * hop;
    let e = 0;
    for (let i = 0; i < N; i++) { const s = x[at + i] || 0; e += s * s; re[i] = s * win[i]; im[i] = 0; }
    rms[f] = Math.sqrt(e / N);
    fft(re, im);
    let lowE = 1e-9, hiE = 0;
    for (let i = 0; i < N / 2; i++) {
      pow[i] = re[i] * re[i] + im[i] * im[i];
      const hz = i * df;
      if (hz > 80 && hz < 3000) lowE += pow[i];
      else if (hz > 3800) hiE += pow[i];
    }
    hiR[f] = hiE / (hiE + lowE);
    f1[f] = centroid(pow, df, 220, 1000);
    f2[f] = secondFormant(x, at, sr, f1[f]);
    f0[f] = pitchOf(x, at, N, sr);
  }
  const ref = [...rms].sort((a, b) => a - b)[Math.floor(count * 0.93)] || 1e-6;
  const voiced = [...f0].filter(Boolean).sort((a, b) => a - b);
  const medF0 = voiced[voiced.length >> 1] || 200;
  const tr = { hop: 0.01, dur: x.length / sr, emph: [], pauses: [] };
  for (const k of ['open', 'wide', 'round', 'teeth', 'energy', 'pitch']) tr[k] = new Float32Array(count);
  let quiet = 0, lastEmph = -1;
  for (let f = 0; f < count; f++) {
    const e = sat(rms[f] / ref), gate = sat((e - 0.05) / 0.15);
    const fric = sat((hiR[f] - 0.22) / 0.4) * gate;
    const voicedness = gate * (1 - fric);
    const height = sat((f1[f] - 300) / 480);                     // F1: jaw height
    const front = sat((f2[f] - 2200) / 400);                     // F2: tongue front (ee) vs back (oo)
    const back = f2[f] ? sat((2250 - f2[f]) / 350) * sat((720 - f1[f]) / 260) : 0;  // American "oo" is fronted, up to about 2000 Hz
    tr.energy[f] = e;
    tr.open[f] = Math.pow(e, 0.65) * (0.22 + 0.78 * height) * voicedness + fric * 0.08;
    tr.wide[f] = front * (1 - 0.85 * height) * voicedness;
    tr.round[f] = back * voicedness;
    tr.teeth[f] = fric;
    tr.pitch[f] = f0[f] ? Math.max(-1, Math.min(1, Math.log2(f0[f] / medF0) * 1.8)) : (f ? tr.pitch[f - 1] * 0.9 : 0);
    const t = f * tr.hop;
    if (e < 0.08) { if (++quiet === 16) tr.pauses.push(t); } else quiet = 0;
    const rise = e - (tr.energy[f - 5] || 0);
    if (rise > 0.24 && t - lastEmph > 0.16) { tr.emph.push({ t, s: sat(rise * 1.3) }); lastEmph = t; }
  }
  return tr;
}

// Lip closures the voice engine timed from its phonemes ([start, end, 'p' | 'f'] in seconds): m/b/p press the lips
// shut, f/v tuck the lower lip under the teeth. Audio alone can't tell these from n/t/s, so they come from the engine.
export function markLips(tr, marks) {
  tr.shut = new Float32Array(tr.open.length); tr.tuck = new Float32Array(tr.open.length);
  for (const [a, b, kind] of marks || []) {
    const s = a - 0.015, e = Math.max(b, a + 0.05), ramp = 0.03, ch = kind === 'p' ? tr.shut : tr.tuck;   // lips move a little ahead of the sound
    for (let f = Math.max(0, Math.floor((s - ramp) / tr.hop)); f <= Math.min(ch.length - 1, (e + ramp) / tr.hop); f++) {
      const t = f * tr.hop, u = t < s ? (t - s + ramp) / ramp : t > e ? (e + ramp - t) / ramp : 1;
      ch[f] = Math.max(ch[f], 0.5 - 0.5 * Math.cos(Math.PI * sat(u)));
    }
  }
  return tr;
}

// Fuse Omni V2's 40 Hz neural IPA viseme/prosody track (jaw, aa/ee/ih/oh/ou, mbp, fv, th, brow, nod)
// directly onto the 100 Hz playback track so all rigs (VRM, anime, 3D, LED, JP01) get exact phoneme lip-sync
// without a separate /lip-sync round trip.
export function applyVisemes(tr, visemes) {
  if (!tr || !Array.isArray(visemes) || !visemes.length) return tr;
  const n = tr.open.length;
  const vowels = { aa: new Float32Array(n), ee: new Float32Array(n), ih: new Float32Array(n), oh: new Float32Array(n), ou: new Float32Array(n) };
  const brow = new Float32Array(n), nod = new Float32Array(n);
  tr.shut ??= new Float32Array(n);
  tr.tuck ??= new Float32Array(n);
  let vi = 0;
  for (let f = 0; f < n; f++) {
    const t = f * tr.hop;
    while (vi + 1 < visemes.length && (visemes[vi + 1].t ?? (vi + 1) * 0.025) <= t) vi++;
    const a = visemes[vi], b = visemes[Math.min(visemes.length - 1, vi + 1)];
    const ta = a.t ?? vi * 0.025, tb = b.t ?? (vi + 1) * 0.025;
    const u = tb > ta ? sat((t - ta) / (tb - ta)) : 0;
    const lerp = k => (a[k] || 0) + ((b[k] || 0) - (a[k] || 0)) * u;
    const jaw = sat(lerp('jaw'));
    const aa = sat(lerp('aa')), ee = sat(lerp('ee')), ih = sat(lerp('ih')), oh = sat(lerp('oh')), ou = sat(lerp('ou'));
    const mbp = sat(lerp('mbp')), fv = sat(lerp('fv')), th = sat(lerp('th'));
    vowels.aa[f] = aa; vowels.ee[f] = ee; vowels.ih[f] = ih; vowels.oh[f] = oh; vowels.ou[f] = ou;
    brow[f] = sat(lerp('brow')); nod[f] = sat(lerp('nod'));
    tr.open[f] = tr.open[f] * 0.35 + jaw * 0.65;
    tr.wide[f] = Math.max(tr.wide[f] * 0.35, sat(ee + ih * 0.75));
    tr.round[f] = Math.max(tr.round[f] * 0.35, sat(oh + ou));
    tr.teeth[f] = Math.max(tr.teeth[f], sat(fv + th * 0.8));
    tr.shut[f] = Math.max(tr.shut[f], mbp);
    tr.tuck[f] = Math.max(tr.tuck[f], fv);
  }
  tr.vowels = vowels;
  tr.brow = brow;
  tr.nod = nod;
  return tr;
}

export function sampleTrack(tr, t) {
  const n = tr.open.length;
  const fp = Math.max(0, Math.min(n - 1.001, t / tr.hop)), i = Math.floor(fp), u = fp - i;
  const at = a => a[i] + (a[i + 1] - a[i]) * (u || 0);
  if (n < 2) return null;
  const out = { open: at(tr.open), wide: at(tr.wide), round: at(tr.round), teeth: at(tr.teeth), energy: at(tr.energy), pitch: at(tr.pitch),
    shut: tr.shut ? at(tr.shut) : 0, tuck: tr.tuck ? at(tr.tuck) : 0 };
  if (tr.vowels) out.vowels = { aa: at(tr.vowels.aa), ee: at(tr.vowels.ee), ih: at(tr.vowels.ih), oh: at(tr.vowels.oh), ou: at(tr.vowels.ou) };
  if (tr.brow) out.brow = at(tr.brow);
  if (tr.nod) out.nod = at(tr.nod);
  return out;
}

// A clip as the server sends it: a WAV of 16-bit sound. Two channels are a song as heard, then the voice alone.
export function readWav(buf) {
  const dv = new DataView(buf);
  let at = 12, sr = SR, ch = 1;
  while (at < dv.byteLength - 8 && dv.getUint32(at) !== 0x64617461) { if (dv.getUint32(at) === 0x666d7420) { ch = dv.getUint16(at + 10, true); sr = dv.getUint32(at + 12, true); } at += 8 + dv.getUint32(at + 4, true); }
  const len = Math.min(dv.getUint32(at + 4, true), dv.byteLength - at - 8) >> 1, n = Math.floor(len / ch), x = new Float32Array(n), y = ch > 1 ? new Float32Array(n) : null;
  for (let i = 0; i < n; i++) { x[i] = dv.getInt16(at + 8 + i * 2 * ch, true) / 32768; if (y) y[i] = dv.getInt16(at + 10 + i * 4, true) / 32768; }
  return y ? { samples: x, sr, voice: y } : { samples: x, sr };   // two channels: the song as heard, then her voice alone
}

// The plain facts of one clip, for comparing voices: length, level, dead air at each end, and the lip marks that came with it.
export function clipFacts(samples, sr, marks = []) {
  let sum = 0, peak = 0, first = -1, last = -1;
  samples.forEach((x, i) => { const a = Math.abs(x); sum += x * x; if (a > peak) peak = a; if (a > 0.005) { if (first < 0) first = i; last = i; } });
  const n = samples.length, ms = k => Math.round(k / sr * 1000);
  return { seconds: +(n / sr).toFixed(2), rms: Math.sqrt(sum / (n || 1)), peak, leadMs: ms(first < 0 ? n : first), tailMs: first < 0 ? 0 : ms(n - 1 - last),
    marks: marks.length, closures: marks.filter(m => m[2] === 'p').length, tucks: marks.filter(m => m[2] === 'f').length };
}

// --- Source-filter synth: glottal saw + noise through a 3-formant cascade ---
const VOWEL = { a: [850, 1350, 2800], e: [560, 2000, 2850], i: [330, 2500, 3200], o: [520, 950, 2700], u: [350, 850, 2400], m: [280, 1100, 2500] };

// phone: { v, dur, f0, f1?, amp, noise, nf, vib }
export function render(phones, sr = SR) {
  const total = Math.ceil(phones.reduce((s, p) => s + p.dur, 0) * sr) + sr >> 0;
  const out = new Float32Array(total);
  const y = [[0, 0], [0, 0], [0, 0]], nfy = [0, 0];
  let F = [...VOWEL[phones[0].v || 'a']], c = [], nfc = [0, 0, 0];
  let phase = 0, tilt = 0, amp = 0, noi = 0, w = 0;
  const glide = 1 - Math.exp(-32 / (sr * 0.022));
  for (const p of phones) {
    const n = Math.round(p.dur * sr), tgt = VOWEL[p.v || 'a'], pa = p.amp ?? 1, pn = p.noise ?? 0;
    for (let s = 0; s < n; s++, w++) {
      if (w % 32 === 0) {
        c = F.map((f, i) => {
          F[i] += (tgt[i] - f) * glide;
          const r = Math.exp(-Math.PI * [90, 120, 170][i] / sr), a1 = 2 * r * Math.cos(TAU * F[i] / sr), a2 = -r * r;
          return [1 - a1 - a2, a1, a2];
        });
        if (p.nf) { const r = Math.exp(-Math.PI * 900 / sr), a1 = 2 * r * Math.cos(TAU * p.nf / sr), a2 = -r * r; nfc = [1 - a1 - a2, a1, a2]; }
      }
      const u = s / n, age = s / sr;
      let f0 = p.f0 + ((p.f1 ?? p.f0) - p.f0) * u;
      if (p.vib) f0 *= 1 + p.vib * sat((age - 0.14) / 0.12) * Math.sin(TAU * 5.6 * age);
      phase += f0 * (1 + 0.003 * Math.sin(w * 0.0009)) / sr;
      if (phase >= 1) phase -= 1;
      amp += (pa - amp) * 0.006; noi += (pn - noi) * 0.012;
      tilt += ((1 - 2 * phase) - tilt) * 0.45;
      const white = Math.random() * 2 - 1;
      let v = tilt * (1 - noi) + white * noi * (p.nf ? 0 : 0.8);
      for (let i = 0; i < 3; i++) { const o = c[i][0] * v + c[i][1] * y[i][0] + c[i][2] * y[i][1]; y[i][1] = y[i][0]; y[i][0] = o; v = o; }
      if (p.nf) { const o = nfc[0] * white + nfc[1] * nfy[0] + nfc[2] * nfy[1]; nfy[1] = nfy[0]; nfy[0] = o; v += o * noi * 0.5; }
      out[w] = v * amp;
    }
  }
  return normalize(out.subarray(0, Math.min(total, w + Math.round(0.03 * sr))));
}

function normalize(x, peak = 0.8) {
  let m = 1e-6;
  for (const s of x) if (Math.abs(s) > m) m = Math.abs(s);
  for (let i = 0; i < x.length; i++) x[i] *= peak / m;
  return x;
}

// Crude grapheme->syllable, good enough for a mouth and a robot voice. ponytail: no phoneme dictionary, add when babble fallback matters.
const DIGRAPH = { ee: 'i', ea: 'i', ie: 'i', oo: 'u', ew: 'u', ue: 'u', ou: 'u', ai: 'e', ay: 'e', ei: 'e', ey: 'e', oa: 'o', ow: 'o', au: 'o', aw: 'o', oy: 'o', igh: 'i' };
const SINGLE = { a: 'a', e: 'e', i: 'i', o: 'o', u: 'o', y: 'i' };
export function syllabify(text) {
  const out = [];
  for (const raw of text.toLowerCase().split(/\s+/)) {
    let w = raw.replace(/[^a-z']/g, '');
    if (!w) continue;
    if (/[^aeiouy]e$/.test(w) && /[aeiouy].*e$/.test(w.slice(0, -1) + 'e') && w.length > 3) w = w.slice(0, -1);
    const parts = w.match(/[^aeiouy]*[aeiouy]+(?:[^aeiouy]+$)?/g) || [w + 'a'];
    parts.forEach((part, i) => {
      const m = part.match(/^([^aeiouy]*)([aeiouy]+)([^aeiouy]*)$/) || [0, '', 'a', ''];
      const v = DIGRAPH[m[2]] || SINGLE[m[2][0]];
      out.push({ on: m[1], v, co: m[3], end: i === parts.length - 1, punct: i === parts.length - 1 ? (raw.match(/[.,!?;:…-]+$/)?.[0] || '') : '' });
    });
  }
  return out;
}

function cons(str, f0) {
  const ph = [];
  for (const ch of str.replace(/'/g, '')) {
    if ('pbtdkgcq'.includes(ch)) ph.push({ v: 'm', dur: 0.03, f0, amp: 0 }, { v: 'e', dur: 0.018, f0, amp: 0.5, noise: 1, nf: 3200 });
    else if ('sfzxjh'.includes(ch)) ph.push({ v: 'i', dur: 0.065, f0, amp: 0.55, noise: 1, nf: ch === 'h' ? 0 : ch === 'f' ? 5200 : 6200 });
    else ph.push({ v: 'm', dur: 0.05, f0, amp: 0.45 });
  }
  return ph;
}

export function synthSpeech(text, { base = 300 } = {}) {
  const syl = syllabify(text), ph = [], q = /\?\s*$/.test(text), bang = /!\s*$/.test(text);
  syl.forEach((s, i) => {
    const u = i / Math.max(1, syl.length - 1);
    let f0 = base * (bang ? 1.12 : 1) * (1.08 - 0.22 * u) * (i % 2 ? 0.96 : 1.04);
    if (q && u > 0.7) f0 *= 1 + (u - 0.7) * 1.2;
    ph.push(...cons(s.on, f0), { v: s.v, dur: 0.13 + (s.end ? 0.03 : 0), f0, f1: f0 * (s.end ? 0.95 : 1), amp: 1 }, ...cons(s.co, f0));
    if (/[.!?]/.test(s.punct)) ph.push({ v: 'm', dur: 0.22, f0, amp: 0 });
    else if (s.punct) ph.push({ v: 'm', dur: 0.12, f0, amp: 0 });
  });
  const samples = render(ph.length ? ph : [{ v: 'm', dur: 0.2, f0: base, amp: 0 }]);
  return { samples, track: analyze(samples) };
}

// Any lyric gets a tune: pentatonic walk seeded by the words, long note at each phrase end.
const SCALE = [0, 2, 4, 7, 9, 12, 14, 16];
function walkTune(text, bpm, root, each) {
  const syl = syllabify(text), beat = 60 / bpm, notes = [];
  let seed = 7, deg = 2, t = 0, inPhrase = 0;
  for (const c of text) seed = (seed * 31 + c.charCodeAt(0)) >>> 0;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
  syl.forEach((s, i) => {
    inPhrase++;
    const phraseEnd = /[,.!?;\n]/.test(s.punct) || i === syl.length - 1 || inPhrase >= 8;
    deg = Math.max(0, Math.min(SCALE.length - 1, deg + Math.round((rnd() - 0.45) * 4)));
    if (phraseEnd) deg = rnd() < 0.5 ? 2 : 0;
    const f = root * 2 ** (SCALE[deg] / 12), dur = beat * (phraseEnd ? 2 : (i % 3 === 2 ? 1 : 0.5));
    each?.(s, f, dur, phraseEnd);
    notes.push({ t, f, dur });
    t += dur;
    if (phraseEnd) inPhrase = 0;
  });
  return { notes, t, beat };
}
export const melody = (text, { bpm = 112, root = 330 } = {}) => walkTune(text, bpm, root).notes;

export function synthSing(text, { bpm = 112, root = 330 } = {}) {
  const ph = [];
  const { notes, t, beat } = walkTune(text, bpm, root, (s, f, dur, phraseEnd) => {
    const con = [...cons(s.on, f)], cd = con.reduce((a, p) => a + p.dur, 0);
    ph.push(...con, { v: s.v, dur: Math.max(0.08, dur - cd - (phraseEnd ? 0.1 : 0.015)), f0: f, amp: 1, vib: phraseEnd ? 0.018 : 0.006 }, { v: s.v, dur: phraseEnd ? 0.1 : 0.015, f0: f, amp: 0 });
  });
  const voice = render(ph), track = analyze(voice);
  const beats = [];
  for (let b = 0; b * beat < t; b++) beats.push(b * beat);
  return { samples: mixMusicBox(voice, notes, beats, beat), track, beats };
}

// A real voice on the tune, with the same little accompaniment following it. shift: semitones the tune was moved to suit the voice.
export function singOver(samples, sr, notes, onsets, shift, { bpm = 112 } = {}) {
  const beat = 60 / bpm, timed = notes.slice(0, onsets.length).map((n, i) => ({ ...n, t: onsets[i] })), beats = [];
  for (let t = onsets[0] ?? 0; t < samples.length / sr; t += beat) beats.push(t);
  return { samples: mixMusicBox(samples, timed, beats, beat, sr, 2 ** (shift / 12)), track: analyze(samples, sr), beats, sr };
}

function mixMusicBox(voice, notes, beats, beat, sr = SR, key = 1) {
  const out = Float32Array.from(voice);
  const pluck = (t, f0, a) => {
    const f = f0 * key, at = Math.round(t * sr), len = Math.min(sr, out.length - at);
    for (let i = 0; i < len; i++) {
      const u = i / sr;
      out[at + i] += a * Math.exp(-u * 5) * (Math.sin(TAU * f * u) + 0.3 * Math.sin(TAU * 2 * f * u));
    }
  };
  const chord = [165, 247, 330, 247];
  beats.forEach((t, i) => pluck(t, chord[i % 4], 0.1));
  notes.forEach(n => pluck(n.t, n.f * 2, 0.035));
  void beat;
  return normalize(out, 0.85);
}

const REST = d => ({ v: 'm', dur: d, f0: 300, amp: 0 });
const VOCALS = {
  laugh() {
    const p = [];
    for (let i = 0; i < 7; i++) {
      const f = 470 - 26 * i;
      p.push({ v: 'a', dur: 0.05, f0: f, amp: 0.5, noise: 0.9 }, { v: 'a', dur: 0.09 + 0.006 * i, f0: f, f1: f * 0.9, amp: 1 - 0.08 * i }, REST(0.085 + 0.012 * i));
    }
    p.push({ v: 'a', dur: 0.26, f0: 300, amp: 0.3, noise: 1 });
    return p;
  },
  giggle() {
    const p = [];
    for (let i = 0; i < 5; i++) p.push({ v: 'i', dur: 0.03, f0: 620, amp: 0.4, noise: 0.8 }, { v: 'i', dur: 0.07, f0: 620 - 24 * i, amp: 1 - 0.1 * i }, REST(0.05));
    return p;
  },
  sigh: () => [{ v: 'a', dur: 0.2, f0: 260, amp: 0.45, noise: 1 }, { v: 'a', dur: 0.75, f0: 240, f1: 180, amp: 0.55, noise: 0.85 }, { v: 'm', dur: 0.2, f0: 170, amp: 0.1, noise: 1 }],
  gasp: () => [{ v: 'a', dur: 0.32, f0: 400, amp: 0.8, noise: 1 }, { v: 'o', dur: 0.1, f0: 520, amp: 0.45 }],
  hmm: () => [{ v: 'm', dur: 0.32, f0: 250, f1: 285, amp: 0.8 }, { v: 'm', dur: 0.32, f0: 285, f1: 240, amp: 0.7 }],
  wow: () => [{ v: 'u', dur: 0.1, f0: 330, f1: 500, amp: 0.8 }, { v: 'a', dur: 0.25, f0: 500, f1: 560, amp: 1 }, { v: 'o', dur: 0.14, f0: 540, f1: 380, amp: 0.9 }, { v: 'u', dur: 0.1, f0: 380, amp: 0.5 }],
  aww: () => [{ v: 'a', dur: 0.22, f0: 520, f1: 470, amp: 0.9 }, { v: 'o', dur: 0.5, f0: 470, f1: 330, amp: 0.9, vib: 0.02 }],
  yay: () => [{ v: 'i', dur: 0.08, f0: 420, f1: 560, amp: 0.8 }, { v: 'a', dur: 0.26, f0: 600, f1: 680, amp: 1 }, { v: 'e', dur: 0.2, f0: 680, f1: 620, amp: 0.9 }],
  ooh: () => [{ v: 'u', dur: 0.42, f0: 340, f1: 520, amp: 0.9, vib: 0.015 }],
};
export const VOCAL_NAMES = Object.keys(VOCALS);

export function synthVocal(name) {
  const samples = render([...VOCALS[name](), REST(0.02)]);
  return { samples, track: analyze(samples) };
}

// Vowel-only render used by the self-test.
export const synthVowel = (v, f0 = 300) => render([{ v, dur: 0.5, f0, amp: 1 }]);
