/* Reveal engine: paces streamed text to a stream style. Pure (no timers) so it's testable; the hook
 * drives it from a timer. Text only ever grows from what's shown; a rewrite (not a prefix) shows at once. */
import { useEffect, useRef, useState } from "react";
import type { StreamStyleParams } from "./streamStyle";

export interface RevealState {
  shown: number;
  /** Incoming characters per second (EMA), for adaptive pacing. */
  inRate: number;
  lastLen: number;
  lastAt: number;
}

export const initialReveal = (now = 0, len = 0): RevealState => ({ shown: len, inRate: 0, lastLen: len, lastAt: now });

const WORD = /\S+\s*/y;
const TOKEN = /(\S{1,4})\s*|\s+/y;

/** Index after `units` words / chars / ~4-char tokens from `from`. */
export function advance(text: string, from: number, units: number, mode: StreamStyleParams["reveal"]["mode"]): number {
  if (mode === "raw") return text.length;
  if (mode === "chars") return Math.min(text.length, from + units);
  const re = mode === "words" ? WORD : TOKEN;
  let i = from;
  // Leading whitespace never counts as a unit.
  while (i < text.length && /\s/.test(text[i])) i += 1;
  for (let n = 0; n < units && i < text.length; n += 1) {
    re.lastIndex = i;
    const m = re.exec(text);
    if (!m || m[0].length === 0) break;
    i += m[0].length;
  }
  return Math.min(i, text.length);
}

/** One tick: how much of `text` to show now. `live` false = the turn ended: show everything. */
export function step(state: RevealState, text: string, now: number, params: StreamStyleParams, live: boolean): RevealState {
  const r = params.reveal;
  let { inRate, lastLen, lastAt } = state;
  if (text.length !== lastLen) {
    const dt = Math.max(1, now - lastAt) / 1000;
    const grow = Math.max(0, text.length - lastLen);
    inRate = inRate === 0 ? grow / dt : inRate * 0.7 + (grow / dt) * 0.3;
    lastLen = text.length; lastAt = now;
  }
  if (!live || r.mode === "raw" || r.ratePerSec <= 0 || state.shown > text.length) return { shown: text.length, inRate, lastLen, lastAt };
  const lag = text.length - state.shown;
  if (lag <= 0) return { shown: state.shown, inRate, lastLen, lastAt };
  if (lag > r.maxLagChars && r.catchUp === "snap") return { shown: text.length - Math.floor(r.maxLagChars / 2), inRate, lastLen, lastAt };
  // Units per tick: the floor rate, or the incoming rate when adaptive (chars → units at ~5 chars/word,
  // ~4 chars/token); doubled while behind when catching up by acceleration.
  const perChar = r.mode === "words" ? 1 / 5 : r.mode === "tokens" ? 1 / 4 : 1;
  let rate = r.ratePerSec;
  if (r.adaptive) rate = Math.max(rate, inRate * perChar);
  if (lag > r.maxLagChars && r.catchUp === "accelerate") rate *= 2;
  const units = Math.max(1, Math.round((rate * r.tickMs) / 1000));
  return { shown: advance(text, state.shown, units, r.mode), inRate, lastLen, lastAt };
}

/** The visible part of a streaming text. Starts from what's already there when it mounts (a reload never
 * replays), paces new text while `live`, and shows everything once the turn ends. */
export function useRevealedText(text: string, live: boolean, params: StreamStyleParams): string {
  const state = useRef<RevealState>(initialReveal(Date.now(), text.length));
  const [, force] = useState(0);
  const textRef = useRef(text);
  textRef.current = text;
  const paced = live && params.reveal.mode !== "raw" && params.reveal.ratePerSec > 0;
  useEffect(() => {
    if (!paced) return;
    const timer = setInterval(() => {
      const next = step(state.current, textRef.current, Date.now(), params, true);
      if (next.shown !== state.current.shown) { state.current = next; force((n) => n + 1); } else state.current = next;
    }, Math.max(8, params.reveal.tickMs));
    return () => clearInterval(timer);
  }, [paced, params]);
  if (!paced) { state.current = { ...state.current, shown: text.length, lastLen: text.length }; return text; }
  if (state.current.shown > text.length) state.current = { ...state.current, shown: text.length };
  return text.slice(0, state.current.shown);
}
