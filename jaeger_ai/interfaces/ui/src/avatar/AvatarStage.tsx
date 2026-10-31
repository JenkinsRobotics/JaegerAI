/** AvatarStage (§2): portrait first (≤50 ms), then the VRM/GLB/Rive renderer swaps in. A failed or missing model never blanks. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ariaLabel, assetUrl, STATE_TEXT, type AvatarRecord, type AvatarState } from "./avatarModel";
import type { StageHandle } from "./threeStage";

type Status = "portrait" | "loading" | "ready" | "error" | "unsupported";

export function useReducedMotion() {
  const q = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const [r, setR] = useState(Boolean(q?.matches));
  useEffect(() => { if (!q) return; const f = () => setR(q.matches); q.addEventListener?.("change", f); return () => q.removeEventListener?.("change", f); }, [q]);
  return r;
}

export interface StageProps {
  name: string; record: AvatarRecord | null; portrait?: ReactNode; state: AvatarState; emotion: string; intensity?: number;
  still?: boolean; paused?: boolean; orbit?: { yaw: number; pitch: number; zoom: number }; mouth?: string | null; caption?: string; compact?: boolean;
  onStats?: (s: { triangles: number; drawCalls: number }) => void; onStatus?: (s: Status) => void;
}

export function AvatarStage({ name, record, portrait, state, emotion, intensity = 1, still, paused, orbit, mouth, caption, compact, onStats, onStatus }: StageProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const handle = useRef<StageHandle | null>(null);
  const rive = useRef<{ set(n: string, v: number | boolean): void; setPaused(p: boolean): void; dispose(): void } | null>(null);
  const [status, setStatus] = useState<Status>("portrait");
  const reduced = useReducedMotion();
  const calm = still || reduced;
  const ext = record?.avatar;
  const modelUrl = ext && ext.format !== "image" ? assetUrl(ext.asset?.uri) : undefined;
  const fallbackUrl = assetUrl(ext?.fallback?.uri) ?? (ext?.format === "image" ? assetUrl(ext.asset?.uri) : undefined);
  useEffect(() => { onStatus?.(status); }, [status, onStatus]);
  useEffect(() => {
    if (!ext || !modelUrl || !canvas.current) { setStatus(ext && ext.format !== "image" && !modelUrl ? "unsupported" : "portrait"); return; }
    let live = true; setStatus("loading");
    const c = canvas.current;
    (ext.format === "rive"
      ? import("./riveStage").then((m) => m.mountRive(c, modelUrl)).then((r) => { if (!live) return r.dispose(); rive.current = r; setStatus("ready"); })
      : import("./threeStage").then((m) => m.mountThree(c, modelUrl, { still: calm, fps: compact ? 30 : 60 })).then((h) => { if (!live) return h.dispose(); handle.current = h; setStatus("ready"); onStats?.(h.stats()); })
    ).catch(() => { if (live) setStatus("error"); });
    return () => { live = false; handle.current?.dispose(); handle.current = null; rive.current?.dispose(); rive.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelUrl, ext?.format, calm, compact]);
  useEffect(() => { if (orbit) handle.current?.setOrbit(orbit.yaw, orbit.pitch, orbit.zoom); }, [orbit, status]);
  useEffect(() => { handle.current?.setPaused(Boolean(paused)); rive.current?.setPaused(Boolean(paused)); }, [paused, status]);
  useEffect(() => {
    const w = ext?.emotions?.[emotion] ?? ext?.emotions?.neutral ?? {};
    const exprState = ext?.states?.[state]?.expression;
    const weights: Record<string, number> = { ...Object.fromEntries(Object.entries(w).map(([k, v]) => [k, v * intensity])) };
    if (exprState && exprState !== "neutral" && !(exprState in weights)) weights[exprState] = 1;
    handle.current?.setExpression(weights);
    rive.current?.set("state", ["idle", "listening", "thinking", "speaking", "blocked", "offline"].indexOf(state));
    rive.current?.set("emotion", Math.max(0, ["neutral", "happy", "warm", "focused", "curious", "concerned", "surprised", "sad"].indexOf(emotion)));
  }, [ext, state, emotion, intensity, status]);
  useEffect(() => {
    const target = mouth == null ? null : ext?.visemes?.map?.[mouth] ?? null;
    handle.current?.setMouth(calm && target ? "aa" : target);
    rive.current?.set("mouth", target ? 1 : 0);
  }, [mouth, ext, calm, status]);
  const showPortrait = status !== "ready";
  return (
    <figure className="jg-av-stage" data-state={state} data-still={calm || undefined} data-compact={compact || undefined} role="img" aria-label={ariaLabel(name, state, emotion)}>
      <div className="jg-av-stage__ring" aria-hidden="true" />
      {modelUrl && <canvas ref={canvas} className="jg-av-stage__canvas" data-ready={status === "ready" || undefined} aria-hidden="true" />}
      {showPortrait && (
        <div className="jg-av-stage__portrait" data-loading={status === "loading" || undefined} aria-hidden="true">
          {fallbackUrl ? <img src={fallbackUrl} alt="" draggable={false} /> : portrait}
        </div>
      )}
      <figcaption className="jg-av-stage__pills">
        <span className="jg-av-pill" data-state={state}><i aria-hidden="true" className="jg-av-pill__dot" />{STATE_TEXT[state]}</span>
        <span className="jg-av-pill">{emotion}</span>
      </figcaption>
      {status === "error" && <p className="jg-av-stage__note" role="status">Model failed, using portrait</p>}
      {status === "unsupported" && <p className="jg-av-stage__note">Model not reachable, using portrait</p>}
      {caption && !compact && <p className="jg-av-stage__caption">{caption}</p>}
    </figure>
  );
}
