// An artist-made VRM avatar (a pack's model, e.g. Vita), drawn with Jaeger Avatar's VRM renderer (vrm/, copied from
// JaegerAvatar app/web: the same rig, flattening, cel look and ink). The rig gives idle life and blinks; its emotion
// follows the agent's mood; the lips follow Jaeger Avatar's analysis of the voice actually playing.
import { useEffect, useRef, useState } from 'react';
import { VrmChar } from './vrm/render-vrm.js';
import { EMOTIONS, Rig } from './vrm/rig.js';
import { sampleTrack } from './vrm/voice.js';
import type { Face } from './agent.ts';
import type { Playing } from './voice.ts';

const LOOKAHEAD = 0.05;
type Cues = { emph: { t: number; s: number }[]; pauses: number[] };   // what analyze() marks, beside the mouth shapes   // the mouth leads the sound a little, as in Jaeger Avatar

export function Vrm({ face, mood, playing }: { face: Face; mood: string; playing: () => Playing | null }) {
  const box = useRef<HTMLDivElement>(null), moodNow = useRef(mood);
  const [note, setNote] = useState('Loading…');
  moodNow.current = mood;
  useEffect(() => {
    const el = box.current!, c = document.createElement('canvas'), ov = document.createElement('canvas');
    ov.style.cssText = c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
    el.append(c, ov);
    const ch = new VrmChar(c, ov, face.model!) as VrmChar & { onProgress?: (p: number) => void }, rig = new Rig();
    ch.onProgress = (p: number) => setNote(`Loading ${Math.round(p * 100)}%`);
    ch.loaded.then(() => setNote(''), (e: Error) => setNote(`Could not load ${face.name}: ${e.message}`));
    let raf = 0, last = -1, shown = '', said = { id: -1, iE: 0, iP: 0 };
    const frame = (ms: number) => {
      raf = requestAnimationFrame(frame);
      const t = ms / 1000, dt = last < 0 ? 0 : Math.min(0.05, t - last); last = t;
      const m = moodNow.current, p = playing();
      const emotion = m in EMOTIONS && m !== 'listening' ? m : 'neutral';
      if (emotion !== shown) { shown = emotion; rig.setEmotion(emotion); }
      if (m === 'listening') rig.listen();
      rig.mode = p ? 'speaking' : m === 'thinking' ? 'thinking' : 'idle';
      if (p) {
        const tr = p.track as unknown as Cues, at = p.t + LOOKAHEAD;
        if (p.id !== said.id) said = { id: p.id, iE: 0, iP: 0 };
        rig.voice = sampleTrack(p.track, at);
        while (said.iE < tr.emph.length && tr.emph[said.iE].t <= at + 0.03) rig.emphasis(tr.emph[said.iE++].s);
        while (said.iP < tr.pauses.length && tr.pauses[said.iP] <= p.t) { rig.blink(); said.iP++; }
      } else rig.voice = null;
      rig.tick(dt);
      const dpr = Math.min(devicePixelRatio || 1, 2), W = Math.round(el.clientWidth * dpr), H = Math.round(el.clientHeight * dpr);
      if (W && H) ch.draw(rig, W, H, dt);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); ch.r.dispose(); el.replaceChildren(); };
  }, [face.model, face.name, playing]);
  return <div className="face vrm"><div className="vrm-box" ref={box} />{note ? <span className="vrm-note">{note}</span> : null}<span className="face-name">{face.name}</span></div>;
}
