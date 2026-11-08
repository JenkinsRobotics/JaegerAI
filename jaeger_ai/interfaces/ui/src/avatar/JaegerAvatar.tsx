import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { ClipAvatar } from "./ClipAvatar";
import { useReducedMotion } from "./AvatarStage";
import { STATUS_TEXT, type ClipState } from "./avatar";
import type { JaegerStageHandle } from "./jaegerStage";
import "./jaegerAvatar.css";

export function JaegerAvatar({ state = "idle", size = 94, name = "Jaeger", still = false, showStatus = false, portraitOverride }: { state?: ClipState; size?: number; name?: string; still?: boolean; showStatus?: boolean; portraitOverride?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const handle = useRef<JaegerStageHandle | null>(null);
  const [status, setStatus] = useState<"fallback" | "loading" | "ready">("fallback");
  const reduced = useReducedMotion();
  const calm = still || reduced;
  const live = !portraitOverride && typeof window.WebGLRenderingContext !== "undefined";
  useEffect(() => {
    if (!live || !canvas.current) { setStatus("fallback"); return; }
    let active = true; const node = canvas.current; setStatus("loading");
    const lost = (event: Event) => { event.preventDefault(); if (active) setStatus("fallback"); };
    node.addEventListener("webglcontextlost", lost);
    void import("./jaegerStage").then(module => {
      if (!active) return;
      const mounted = module.mountJaegerStage(node, { state, still: calm });
      handle.current = mounted; setStatus("ready");
    }).catch(() => { if (active) setStatus("fallback"); });
    return () => { active = false; node.removeEventListener("webglcontextlost", lost); handle.current?.dispose(); handle.current = null; };
  }, [calm, live]);
  useEffect(() => handle.current?.setState(state), [state, status]);
  const point = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    handle.current?.setPointer(((event.clientX - rect.left) / rect.width) * 2 - 1, ((event.clientY - rect.top) / rect.height) * 2 - 1);
  };
  return <span className="jg-jaeger-avatar" data-live-status={status} data-avatar-state={state} style={{ width: size, height: size }}>
    <ClipAvatar state={state} size={size} name={name} still={calm || status === "ready"} portraitOverride={portraitOverride} />
    {live && <canvas ref={canvas} aria-hidden="true" onPointerMove={point} onPointerLeave={() => handle.current?.setPointer(0, 0)} />}
    {showStatus && <span className="jg-clip-status" role="status">{STATUS_TEXT[state]}</span>}
  </span>;
}
