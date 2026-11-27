// The window's microphone, recorded as one clip for the Gateway's hearing (16 kHz 16-bit mono). Copied from Omni's
// live mic and made a press-to-talk clip: the Gateway hears whole clips (/v1/droid/transcribe), not a live stream.
import { pcm16k } from './attach.ts';

/** Starts recording; the returned function stops it and resolves to the clip (base64 PCM). */
export async function recordClip(): Promise<() => Promise<string>> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const ctx = new AudioContext();
  if (ctx.state === 'suspended') await ctx.resume();   // WebKit starts it paused
  const src = ctx.createMediaStreamSource(stream), node = ctx.createScriptProcessor(4096, 1, 1);   // ponytail: an AudioWorklet if this ever stutters
  const parts: Float32Array[] = [];
  node.onaudioprocess = e => parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(node); node.connect(ctx.destination);   // it writes nothing: silence out
  return async () => {
    node.disconnect(); src.disconnect(); stream.getTracks().forEach(t => t.stop());
    const all = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
    let at = 0; for (const p of parts) { all.set(p, at); at += p.length; }
    const rate = ctx.sampleRate; await ctx.close();
    return pcm16k(all, rate);
  };
}
