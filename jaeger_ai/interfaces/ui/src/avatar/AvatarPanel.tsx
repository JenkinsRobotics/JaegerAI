import {ClipAvatar} from "./ClipAvatar";
import type {ClipState} from "./avatar";
/** Chat › avatar panel (§1): expanded column, 64 px rail, floating Mini, or hidden. Per-agent mode; ⌥⌘A toggles. */
import "./avatar.css";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Agent } from "../api/types";
import { AgentFace } from "../unified/AgentFace";
import { label } from "../agents/agentsLogic";
import { AvatarStage } from "./AvatarStage";
import { avatarStateFor, loadMode, nextMode, PREVIEW_STATES, saveMode, STATE_TEXT, type AvatarState, type PanelMode } from "./avatarModel";
import { useAvatar, useSpeech } from "./useAvatar";
import type { SizeClass } from "../shell/breakpoints";

export function AvatarPanel({ agent, presence, onOpenAgents, size, clipState="idle" }: { clipState?:ClipState; agent: Agent; presence?: string; onOpenAgents?: (id: string) => void; size: { cls: SizeClass; short: boolean } }) {
  const { cls, short } = size;
  const [mode, setModeState] = useState<PanelMode>(() => loadMode(agent.id, cls, short));
  const [still, setStill] = useState(false);
  const [preview, setPreview] = useState<AvatarState | null>(null);
  const { record } = useAvatar(agent.id);
  const { speaking, mouth } = useSpeech(agent.id);
  const name = label(agent);
  useEffect(() => setModeState(loadMode(agent.id, cls, short)), [agent.id, cls, short]);
  const setMode = (m: PanelMode) => { setModeState(m); saveMode(agent.id, m, cls); };
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.altKey && e.metaKey && e.code === "KeyA") { e.preventDefault(); setModeState((m) => { const n = nextMode(m); saveMode(agent.id, n, cls); return n; }); } };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [agent.id, cls]);
  useEffect(() => { if (!preview) return; const t = window.setTimeout(() => setPreview(null), 3000); return () => window.clearTimeout(t); }, [preview]);
  const live = avatarStateFor(presence, { speaking });
  const state = preview ?? live;
  const emotion = record?.live.emotion ?? "neutral";
  // Announce politely only when a state lasts > 1.5 s (§4).
  const [announced, setAnnounced] = useState("");
  useEffect(() => { const t = window.setTimeout(() => setAnnounced(`${name} is ${STATE_TEXT[state].toLowerCase()}`), 1500); return () => window.clearTimeout(t); }, [state, name]);
  const builtin = agent.id === "native:jaeger" && !record?.avatar && !agent.avatar_url;
  const format = record?.avatar?.format ?? "portrait";
  const stage = (compact: boolean) => builtin ? <ClipAvatar name={name} state={clipState} size={compact ? 120 : 200} still={still} /> : (
    <AvatarStage name={name} record={record} state={state} emotion={emotion} intensity={record?.live.intensity || 1} still={still} compact={compact}
      paused={mode === "hidden" || mode === "rail"} mouth={mouth} portrait={<AgentFace agent={agent} size={compact ? 120 : 200} />} />
  );
  const live_ = <span className="jg-sr-only" aria-live="polite">{announced}</span>;
  if (mode === "hidden") return <div className="jg-av-panel" data-mode="hidden">{live_}<button type="button" className="jg-av-reveal" aria-label={`Show ${name}'s avatar (⌥⌘A)`} onClick={() => setMode("expanded")}><AgentFace agent={agent} size={28} /></button></div>;
  if (mode === "rail") return (
    <aside className="jg-av-panel" data-mode="rail" aria-label={`${name} avatar`}>{live_}
      <button type="button" className="jg-av-rail__face" data-state={state} aria-label={`Expand ${name}'s avatar (⌥⌘A)`} onClick={() => setMode("expanded")}><AgentFace agent={agent} size={40} /></button>
      <span className="jg-av-rail__state">{STATE_TEXT[state]}</span>
    </aside>
  );
  if (mode === "mini") return <>{live_}<MiniWindow name={name} small={cls === "compact"} onExpand={() => setMode("expanded")} onClose={() => setMode("rail")}>{stage(true)}</MiniWindow></>;
  return (
    <aside className="jg-av-panel" data-mode="expanded" aria-label={`${name} avatar`}>{live_}
      <header className="jg-av-panel__head">
        <strong>{name}</strong><span className="jg-av-chip">{format.toUpperCase()}</span>
        <span className="jg-av-panel__tools">
          <button type="button" className="jg-u-btn" aria-pressed={still} onClick={() => setStill((s) => !s)}>Still</button>
          <button type="button" className="jg-u-btn" onClick={() => setMode("mini")}>Mini</button>
          {onOpenAgents && <button type="button" className="jg-u-btn" onClick={() => onOpenAgents(agent.id)}>Open in Agents</button>}
          <button type="button" className="jg-u-btn" aria-label="Collapse avatar (⌥⌘A)" onClick={() => setMode("rail")}>Collapse</button>
          <button type="button" className="jg-u-btn jg-av-phone-only" aria-label="Hide avatar" onClick={() => setMode("hidden")}>Hide</button>
        </span>
      </header>
      {stage(false)}
      {!builtin && <div className="jg-av-strip" role="group" aria-label="Preview a state for 3 seconds">
        {PREVIEW_STATES.map((s) => <button key={s} type="button" className="jg-av-strip__item" data-state={s} aria-pressed={state === s} onClick={() => setPreview(s)}><i aria-hidden="true" className="jg-av-pill__dot" />{STATE_TEXT[s]}</button>)}
      </div>}
      {!builtin && !record?.avatar && <p className="jg-av-hint">No avatar saved yet; showing {name}'s portrait. Set one in Agents › Avatar.</p>}
    </aside>
  );
}

function MiniWindow({ name, small, children, onExpand, onClose }: { name: string; small: boolean; children: React.ReactNode; onExpand: () => void; onClose: () => void }) {
  const [pos, setPos] = useState(() => { try { return JSON.parse(localStorage.getItem("jaeger.avatar.mini") ?? "") as { x: number; y: number }; } catch { return { x: -1, y: -1 }; } });
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const W = small ? 120 : 160;
  const snap = (x: number, y: number) => {
    const vw = window.innerWidth, vh = window.innerHeight, m = 8, cs = getComputedStyle(document.documentElement);
    const inset = (k: string) => parseFloat(cs.getPropertyValue(`--jg-safe-${k}`)) || 0;
    return { x: x + W / 2 < vw / 2 ? m + inset("left") : vw - W - m - inset("right"), y: y + W / 2 < vh / 2 ? m + 48 + inset("top") : vh - W - m - 72 - inset("bottom") };
  };
  const at = pos.x < 0 ? snap(window.innerWidth, window.innerHeight) : pos;
  return createPortal(
    <div className="jg-av-mini" data-small={small || undefined} role="dialog" aria-label={`${name} avatar (mini)`} style={{ left: at.x, top: at.y }} onDoubleClick={onExpand}
      onPointerDown={(e) => { if ((e.target as HTMLElement).closest("button")) return; drag.current = { dx: e.clientX - at.x, dy: e.clientY - at.y }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (drag.current) setPos({ x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }); }}
      onPointerUp={() => { if (!drag.current) return; drag.current = null; const s = snap(at.x, at.y); setPos(s); localStorage.setItem("jaeger.avatar.mini", JSON.stringify(s)); }}>
      {children}
      <span className="jg-av-mini__tools"><button type="button" className="jg-u-btn" onClick={onExpand} aria-label="Expand">⤢</button><button type="button" className="jg-u-btn" onClick={onClose} aria-label="Close mini">×</button></span>
    </div>, document.body);
}
