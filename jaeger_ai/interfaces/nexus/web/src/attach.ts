// What the person attaches: pictures (photos, a video's keyframes, camera snaps) go to her eye as JPEG; a sound clip
// goes to her hearing as 16 kHz 16-bit mono. Everything is turned into that here, in the page.
const MAX = 896;   // longest side sent: the model fits pictures to its own size anyway

export type Attachment = { kind: 'picture' | 'sound'; name: string; data: string };   // picture: data URL; sound: base64 PCM

function jpeg(source: CanvasImageSource, w: number, h: number): string {
  const k = Math.min(1, MAX / Math.max(w, h)), c = document.createElement('canvas');
  c.width = Math.round(w * k); c.height = Math.round(h * k);
  c.getContext('2d')!.drawImage(source, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', .85);
}

export const snap = (v: HTMLVideoElement) => jpeg(v, v.videoWidth, v.videoHeight);

async function picture(file: File): Promise<string> {
  const b = await createImageBitmap(file);
  try { return jpeg(b, b.width, b.height); } finally { b.close(); }
}

async function keyframes(file: File, n = 4): Promise<string[]> {   // ponytail: evenly spaced frames, scene cuts if needed
  const v = document.createElement('video'), url = URL.createObjectURL(file);
  v.muted = true; v.src = url;
  try {
    await new Promise((ok, no) => { v.onloadeddata = ok; v.onerror = no; });
    const out: string[] = [];
    for (let i = 0; i < n; i++) {
      v.currentTime = v.duration * (i + .5) / n;
      await new Promise(ok => { v.onseeked = ok; });
      out.push(snap(v));
    }
    return out;
  } finally { URL.revokeObjectURL(url); }
}

export function pcm16k(samples: Float32Array, rate: number): string {
  const n = Math.floor(samples.length * 16000 / rate), out = new Int16Array(n);
  for (let i = 0; i < n; i++) {   // each 16 kHz sample is the mean of the samples it covers (no aliasing from skipping)
    const a = Math.floor(i * rate / 16000), b = Math.max(a + 1, Math.floor((i + 1) * rate / 16000));
    let sum = 0; for (let j = a; j < b; j++) sum += samples[j];
    out[i] = Math.round(Math.max(-1, Math.min(1, sum / (b - a))) * 32767);
  }
  let s = ''; const b = new Uint8Array(out.buffer);
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000));
  return btoa(s);
}

async function sound(file: File): Promise<string> {
  const ctx = new OfflineAudioContext(1, 1, 16000), a = await ctx.decodeAudioData(await file.arrayBuffer());
  const mono = new Float32Array(a.length);
  for (let c = 0; c < a.numberOfChannels; c++) a.getChannelData(c).forEach((x, i) => { mono[i] += x / a.numberOfChannels; });
  return pcm16k(mono, a.sampleRate);
}

export async function attach(file: File): Promise<Attachment[]> {
  if (file.type.startsWith('image/')) return [{ kind: 'picture', name: file.name, data: await picture(file) }];
  if (file.type.startsWith('video/')) return (await keyframes(file)).map((data, i) => ({ kind: 'picture', name: `${file.name} · ${i + 1}`, data }));
  if (file.type.startsWith('audio/')) return [{ kind: 'sound', name: file.name, data: await sound(file) }];
  return [];
}
