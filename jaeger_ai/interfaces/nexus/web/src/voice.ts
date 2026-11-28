// Her voice: each spoken sentence (an `audio` event: 16-bit PCM, base64, at `rate`) queued and played in order.
import { analyze } from './vrm/voice.js';

/** The clip playing now and how far into it, for lip sync (its track is Jaeger Avatar's voice analysis, made on first use). */
export type Playing = { id: number; t: number; track: ReturnType<typeof analyze> };

export function voice() {
  let ctx: AudioContext | null = null, at = 0, meter: AnalyserNode | null = null, made = 0;
  const live = new Set<AudioBufferSourceNode>(), wave = new Float32Array(512);
  let clips: { id: number; start: number; end: number; pcm: Float32Array; rate: number; track?: Playing['track'] }[] = [];
  return {
    current(): Playing | null {
      if (!ctx) return null;
      const now = ctx.currentTime;
      clips = clips.filter(c => c.end > now);
      const c = clips.find(c => now >= c.start);
      if (!c) return null;
      c.track ??= analyze(c.pcm, c.rate);
      return { id: c.id, t: now - c.start, track: c.track };
    },
    level() {   // how loud she is right now (RMS), for the face's mouth
      if (!meter || !live.size) return 0;
      meter.getFloatTimeDomainData(wave);
      return Math.sqrt(wave.reduce((s, x) => s + x * x, 0) / wave.length);
    },
    play(pcm: string, rate: number) {
      if (!ctx) { ctx = new AudioContext(); meter = ctx.createAnalyser(); meter.fftSize = 512; meter.connect(ctx.destination); }
      if (ctx.state === 'suspended') void ctx.resume();   // WebKit starts it paused; no click is needed to resume
      const bytes = Uint8Array.from(atob(pcm), c => c.charCodeAt(0));
      const n = bytes.length >> 1, view = new DataView(bytes.buffer), buf = ctx.createBuffer(1, n, rate), ch = buf.getChannelData(0);
      for (let i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 32768;
      const src = ctx.createBufferSource();
      src.buffer = buf; src.connect(meter!);
      at = Math.max(at, ctx.currentTime + 0.05); src.start(at);
      clips.push({ id: ++made, start: at, end: at + buf.duration, pcm: ch, rate });
      at += buf.duration;
      live.add(src); src.onended = () => live.delete(src);
    },
    playing: () => live.size > 0,
    /** Resolves once everything queued has played. */
    idle(): Promise<void> {
      return new Promise(ok => { const check = () => (live.size ? setTimeout(check, 100) : ok()); check(); });
    },
    stop() {
      live.forEach(s => { try { s.stop(); } catch { /* already ended */ } });
      live.clear(); clips = []; at = 0;
    },
  };
}
