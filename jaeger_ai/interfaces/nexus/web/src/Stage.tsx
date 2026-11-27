// The stage: the character's own face (its pack's locked screen look, `looks/screen.json`), drawn with the flat face
// copied from Jaeger Avatar (face/). Its mood follows the agent's feeling and state; its mouth follows the voice.
import { useEffect, useRef } from 'react';
import { FACE_MOODS, FaceAnimator } from './face/eyes.js';
import { fromPack, styledFace } from './face/styles.js';

export type Look = { name: string; style?: Record<string, unknown>; card?: string };

export function Stage({ look, mood, level }: { look: Look; mood: string; level: () => number }) {
  return look.style ? <Face look={look} mood={mood} level={level} />
    : <div className="face"><img className="card" src={look.card} alt={look.name} /><span className="face-name">{look.name}</span></div>;
}

function Face({ look, mood, level }: { look: Look; mood: string; level: () => number }) {
  const canvas = useRef<HTMLCanvasElement>(null), moodNow = useRef(mood);
  moodNow.current = mood;
  useEffect(() => {
    const c = canvas.current!, ctx = c.getContext('2d')!, face = styledFace(fromPack(look.style, look.name)), anim = new FaceAnimator();
    let raf = 0, last = -1, shown = 'neutral', since = 0, jaw = 0;
    const draw = (ms: number) => {
      const t = ms / 1000, dt = last < 0 ? 0 : Math.min(t - last, .05); last = t;
      const w = c.width, h = c.height;
      const m = FACE_MOODS.includes(moodNow.current) ? moodNow.current : 'neutral';
      if (m !== shown) { shown = m; since = t; }
      jaw += (Math.min(1, level() * 6) - jaw) * .35;   // ponytail: loudness drives the mouth; visemes if it looks off
      const v = { jaw, faceMood: FACE_MOODS.indexOf(m) / (FACE_MOODS.length - 1), faceMoodAge: t - since, faceEnergy: 1,
        faceReaction: 0, faceProgress: 0, gazeX: 0, gazeY: 0 };
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
      face.paint(ctx, anim.update(v, dt, t), jaw, { t, v });
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [look, level]);
  return <div className="face"><canvas ref={canvas} width={1024} height={1024} /><span className="face-name">{look.name}</span></div>;
}

