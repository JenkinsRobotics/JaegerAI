/* Agents › Team: a pixel-art office where every roster agent has a desk and you
 * can see who is working. State comes from the live orchestration snapshot and
 * the global event stream (useOrchestration): current chat, handoffs and tasks.
 * Nothing is staged — an
 * agent with no live signal sits idle with a coffee. Art is drawn in code
 * (sprites.ts); text (name tags, bubbles, the side panel) stays real HTML. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { GatewayClient } from "../../api/gateway";
import type { JaegerSource } from "../../api/source";
import { derivedGaps, gatewayActivity, liveAdapter, type GapProvider } from "../../orchestration/adapter";
import { useOrchestration } from "../../orchestration/useOrchestration";
import type { ActivityRow } from "../../orchestration/types";
import { foldAll, type Span } from "../../process/model";
import { useProcessEvents } from "../../process/useProcessEvents";
import { AgentAvatar } from "../AgentAvatar";
import { deriveWorkers, recoverMaskedChatStatus, type Mood, type Worker } from "./officeState";
import {
  aisleY, CELL_H, CELL_W, coffeePoint, deskGeom, dimRect, drawDesk, drawRoom, drawWalker, lookFor, PALETTE_KEYS,
  seatPoint, visitPoint, WALL_H, worldSize, type DeskGeom, type Look, type Palette,
} from "./sprites";
import "../team.css";
import "./office.css";

type Pt = { x: number; y: number };
type Goal = "seat" | "visit" | "coffee" | "away";
interface Anim { x: number; y: number; route: Pt[]; goal: Goal; key: string }

const SPEED = 42; // world px per second
const FPS = 8;
const SHOW_ALL_KEY = "jaeger.office.showTestAgents";
const MOODS: { mood: Mood; label: string }[] = [
  { mood: "working", label: "Working" }, { mood: "queued", label: "Queued" }, { mood: "handoff", label: "Handing off" }, { mood: "approval", label: "Waiting on you" },
  { mood: "idle", label: "Idle" }, { mood: "error", label: "Blocked" }, { mood: "offline", label: "Offline" },
];

function hash(s: string) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
/** Idle agents take a coffee break now and then (a fixed per-agent rhythm, idle only). */
function onBreak(id: string, ms: number) { const h = hash(id), period = 80 + (h % 70); return ((ms / 1000 + (h % 997)) % period) < 13; }

const FALLBACK: Palette = Object.fromEntries(PALETTE_KEYS.map((k) => [k, "#808080"])) as Palette;
function readPalette(el: HTMLElement): Palette {
  const probe = document.createElement("span");
  probe.style.display = "none";
  el.appendChild(probe);
  const test = document.createElement("canvas").getContext("2d");
  const out = { ...FALLBACK };
  for (const k of PALETTE_KEYS) {
    probe.style.color = `var(--jg-office-${k})`;
    const v = getComputedStyle(probe).color;
    if (!v) continue;
    if (test) { test.fillStyle = "#010203"; test.fillStyle = v; if (test.fillStyle === "#010203") continue; }
    out[k] = v;
  }
  probe.remove();
  return out;
}

function usePalette(ref: React.RefObject<HTMLElement | null>) {
  const [palette, setPalette] = useState<Palette | null>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const read = () => setPalette(readPalette(el));
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style", "data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", read);
    return () => { mo.disconnect(); mq?.removeEventListener?.("change", read); };
  }, [ref]);
  return palette;
}

const ago = (t: number) => {
  const s = Math.max(0, Date.now() / 1000 - (t > 1e12 ? t / 1000 : t));
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`;
};

export function PixelOffice({ source, onNavigate, params }: { source: JaegerSource; onNavigate: (to: string) => void; params?: URLSearchParams }) {
  const adapter = useMemo(() => {
    const base = (source as unknown as { base?: unknown }).base;
    const gaps: GapProvider = source instanceof GatewayClient
      ? { ...derivedGaps, kind: "gateway", activity: gatewayActivity(typeof base === "string" ? base : "") }
      : derivedGaps;
    const adapter = liveAdapter(source, gaps);
    return { ...adapter, snapshot: async () => recoverMaskedChatStatus(await adapter.snapshot(), source) };
  }, [source]);
  const orch = useOrchestration(adapter, { refreshMs: 8000 });
  const reduce = Boolean(useReducedMotion());
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 5000); return () => clearInterval(t); }, []);
  const gatewayDown = orch.snapshotStale || (orch.status === "error" && !orch.snapshot);
  const workers = useMemo(() => deriveWorkers(orch.live, orch.snapshot, now, gatewayDown), [orch.live, orch.snapshot, now, gatewayDown]);

  const [showAll, setShowAll] = useState(() => { try { return localStorage.getItem(SHOW_ALL_KEY) === "1"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem(SHOW_ALL_KEY, showAll ? "1" : "0"); } catch { /* private mode */ } }, [showAll]);
  // Desks never move when someone's status changes: lead first, then by name.
  const shown = useMemo(() => workers.filter((w) => showAll || !w.fixture)
    .sort((a, b) => Number(b.lead) - Number(a.lead) || a.name.localeCompare(b.name)), [workers, showAll]);
  const hidden = workers.filter((w) => w.fixture).length;

  const [selected, setSelected] = useState<string | null>(() => params?.get("agent") ?? null);
  const worker = shown.find((w) => w.id === selected) ?? workers.find((w) => w.id === selected);

  // Layout: fit columns and an integer scale to the frame; +/- zoom on top.
  const frameRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [frameW, setFrameW] = useState(0);
  useEffect(() => {
    const el = frameRef.current; if (!el) return;
    const ro = new ResizeObserver(() => setFrameW(el.clientWidth));
    ro.observe(el); setFrameW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const [zoom, setZoom] = useState(0);
  const avail = Math.max(240, frameW - 16);
  const cols = Math.max(2, Math.min(6, Math.floor(avail / (CELL_W * 2)), Math.max(2, Math.ceil(Math.sqrt(shown.length * 1.6)))));
  const world = worldSize(shown.length, cols);
  const fit = Math.max(1, Math.floor(avail / world.w));
  const scale = Math.max(1, Math.min(6, fit + zoom));
  const palette = usePalette(rootRef);

  const desks = useMemo(() => new Map(shown.map((w, i) => [w.id, deskGeom(i, cols)])), [shown, cols]);
  const looks = useMemo(() => new Map(shown.map((w) => [w.id, lookFor(w.seed)])), [shown]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const anims = useRef(new Map<string, Anim>());
  const bubbleRefs = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas || !palette) return;
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    canvas.width = world.w * scale * dpr; canvas.height = world.h * scale * dpr;
    canvas.style.width = `${world.w * scale}px`; canvas.style.height = `${world.h * scale}px`;
    const c = canvas.getContext("2d"); if (!c) return;
    c.imageSmoothingEnabled = false;
    const rows = Math.max(1, Math.ceil(shown.length / cols));
    const lastAisle = WALL_H + rows * CELL_H;
    const aisleNear = (p: Pt) => {
      if (p.y >= lastAisle) return p.y;
      const row = Math.max(0, Math.min(rows - 1, Math.floor((p.y - WALL_H) / CELL_H)));
      return WALL_H + row * CELL_H + 60;
    };

    const goalFor = (w: Worker, ms: number): { goal: Goal; pt?: Pt; key: string } => {
      const d = desks.get(w.id)!;
      if (w.mood === "offline") return { goal: "away", key: "away" };
      if (w.mood === "handoff" && w.handoffTo && desks.has(w.handoffTo)) return { goal: "visit", pt: visitPoint(desks.get(w.handoffTo)!), key: `visit:${w.handoffTo}` };
      if (w.mood === "idle" && !reduce && onBreak(w.id, ms)) return { goal: "coffee", pt: coffeePoint(world.w, world.h, hash(w.id)), key: "coffee" };
      return { goal: "seat", pt: seatPoint(d), key: "seat" };
    };
    const routeTo = (from: Pt, own: DeskGeom, goal: Goal, to: Pt, target?: DeskGeom): Pt[] => {
      const seat = seatPoint(own);
      const exit: Pt[] = Math.abs(from.x - seat.x) < 1 && Math.abs(from.y - seat.y) < 1
        ? [{ x: own.x0 + 70, y: seat.y }, { x: own.x0 + 70, y: aisleY(own) }] : [{ x: from.x, y: aisleNear(from) }];
      const enter: Pt[] = goal === "seat" ? [{ x: own.x0 + 70, y: aisleY(own) }, { x: own.x0 + 70, y: seat.y }, seat]
        : goal === "visit" && target ? [{ x: to.x, y: aisleY(target) }, to] : [{ x: to.x, y: Math.max(lastAisle - 6, to.y - 4) }, to];
      const last = exit[exit.length - 1];
      return [...exit, { x: enter[0].x, y: last.y }, ...enter];
    };

    let raf = 0, frame = 0, acc = 0, prev = performance.now();
    const draw = (ms: number, dt: number) => {
      c.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
      c.clearRect(0, 0, world.w, world.h);
      const hour = new Date().getHours();
      drawRoom(c, palette, world.w, world.h, hour < 7 || hour >= 19, reduce ? 0 : frame, rows);
      type Item = { z: number; paint: () => void };
      const items: Item[] = [];
      for (const w of shown) {
        const d = desks.get(w.id)!, look: Look = looks.get(w.id)!;
        const g = goalFor(w, ms);
        let a = anims.current.get(w.id);
        const seat = seatPoint(d);
        if (!a) { a = { ...seat, route: [], goal: "seat", key: "seat" }; anims.current.set(w.id, a); }
        if (g.goal === "away") { a.x = seat.x; a.y = seat.y; a.route = []; a.goal = "away"; a.key = "away"; }
        else if (a.key !== g.key || a.goal === "away") {
          a.route = reduce ? [g.pt!] : routeTo(a, d, g.goal, g.pt!, g.goal === "visit" ? desks.get(w.handoffTo!) : undefined);
          a.goal = g.goal; a.key = g.key;
        }
        // Advance along the route.
        let budget = reduce ? Infinity : SPEED * dt;
        while (budget > 0 && a.route.length) {
          const t = a.route[0], dx = t.x - a.x, dy = t.y - a.y, dist = Math.hypot(dx, dy);
          if (dist <= budget) { a.x = t.x; a.y = t.y; a.route.shift(); budget -= dist; }
          else { a.x += (dx / dist) * budget; a.y += (dy / dist) * budget; budget = 0; }
        }
        const moving = a.route.length > 0;
        const seated = a.goal === "seat" && !moving && Math.abs(a.x - seat.x) < 0.5 && Math.abs(a.y - seat.y) < 0.5;
        // Away from the desk: chair empty, screen asleep.
        const deskMood: Mood = seated ? w.mood : w.mood === "offline" ? "offline" : "handoff";
        items.push({ z: d.y0 + 48, paint: () => {
          drawDesk(c, palette, d, deskMood, look, seated, reduce ? 0 : frame, w.lead, !reduce);
          if (w.mood === "offline") dimRect(c, palette, d.x0 + 2, d.y0 + 4, CELL_W - 4, CELL_H - 8);
        } });
        if (!seated && a.goal !== "away") {
          const ax = a.x, ay = a.y;
          items.push({ z: ay, paint: () => drawWalker(c, palette, ax, ay, look, reduce ? 0 : frame, moving, a!.goal === "coffee" ? "mug" : a!.goal === "visit" ? "paper" : null) });
        }
        const bubble = bubbleRefs.current.get(w.id);
        if (bubble) {
          const bx = seated || a.goal === "away" ? d.cx : a.x, by = seated || a.goal === "away" ? d.y0 + (w.mood === "approval" || w.mood === "error" ? -7 : 6) : a.y - 28;
          bubble.style.transform = `translate(${Math.round(bx * scale)}px, ${Math.round(by * scale)}px) translate(-50%, -100%)`;
        }
      }
      items.sort((x, y) => x.z - y.z).forEach((i) => i.paint());
      if (gatewayDown) dimRect(c, palette, 0, 0, world.w, world.h);
    };
    const tick = (t: number) => {
      const dt = Math.min(0.1, (t - prev) / 1000); prev = t; acc += dt;
      if (acc >= 1 / FPS) { frame++; acc = 0; }
      draw(Date.now(), dt);
      raf = requestAnimationFrame(tick);
    };
    if (reduce) { draw(Date.now(), 0); return; }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [palette, shown, desks, looks, world.w, world.h, scale, cols, reduce, gatewayDown]);

  const pick = useCallback((id: string) => setSelected((cur) => (cur === id ? null : id)), []);
  const counts = useMemo(() => { const m = new Map<Mood, number>(); shown.forEach((w) => m.set(w.mood, (m.get(w.mood) ?? 0) + 1)); return m; }, [shown]);
  // "connecting" after a good snapshot = the event stream is open and quiet.
  const streamLive = !gatewayDown && Boolean(orch.snapshot) && (orch.stream === "live" || orch.stream === "connecting");
  const streamText = gatewayDown ? "Gateway offline" : !orch.snapshot ? "Connecting…" : streamLive ? "Live" : orch.stream === "polling" ? "Updating every 15 s" : "Reconnecting…";

  return (
    <div ref={rootRef} className={`jg-office${worker ? " has-panel" : ""}`}>
      <div className="jg-office__main">
        <header className="jg-office__head">
          <div className="jg-office__title">
            <h2>Team</h2>
            <span className={`jg-office__live is-${gatewayDown ? "down" : streamLive ? "live" : orch.stream}`}><i aria-hidden="true" />{streamText}</span>
          </div>
          <div className="jg-office__tools">
            {hidden > 0 && (
              <label className="jg-office__toggle">
                <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
                Show test agents ({hidden})
              </label>
            )}
            <div className="jg-office__zoom" role="group" aria-label="Zoom">
              <button type="button" aria-label="Zoom out" disabled={scale <= 1} onClick={() => setZoom((z) => Math.max(1 - fit, z - 1))}>−</button>
              <button type="button" aria-label="Fit to width" disabled={zoom === 0} onClick={() => setZoom(0)}>Fit</button>
              <button type="button" aria-label="Zoom in" disabled={scale >= 6} onClick={() => setZoom((z) => Math.min(6 - fit, z + 1))}>+</button>
            </div>
          </div>
        </header>
        <ul className="jg-office__legend" aria-label="Who is doing what">
          {MOODS.map(({ mood, label }) => <li key={mood} className={`is-${mood}`}><i aria-hidden="true" />{label}<b>{counts.get(mood) ?? 0}</b></li>)}
        </ul>
        {gatewayDown && <div className="jg-office__banner" role="alert">Can't refresh Office status. {orch.snapshot ? "" : orch.error} <button type="button" onClick={orch.retry}>Retry</button></div>}
        <div ref={frameRef} className="jg-office__frame">
          {orch.status === "loading" && !shown.length ? <div className="jg-office__empty">Opening the office…</div> : !shown.length ? <div className="jg-office__empty">No agents on the roster yet.</div> : (
            <div className="jg-office__world" style={{ width: world.w * scale, height: world.h * scale }}>
              <canvas ref={canvasRef} className="jg-office__canvas" role="img" aria-label={`Pixel office with ${shown.length} agents: ${shown.map((w) => `${w.name} ${w.statusText.toLowerCase()}`).join(", ")}`} />
              {shown.map((w) => {
                const d = desks.get(w.id)!;
                return (
                  <button key={w.id} type="button" className={`jg-office__desk is-${w.mood}${selected === w.id ? " is-selected" : ""}`}
                    style={{ left: d.x0 * scale, top: (d.y0 + 2) * scale, width: CELL_W * scale, height: (CELL_H - 4) * scale }}
                    aria-pressed={selected === w.id} aria-label={`${w.name}: ${w.statusText}${w.bubble ? ` — ${w.bubble}` : ""}`} onClick={() => pick(w.id)}>
                    <span className="jg-office__tag" style={{ top: 50 * scale }}>{w.lead && <span aria-hidden="true">★ </span>}{w.name}</span>
                  </button>
                );
              })}
              {shown.filter((w) => w.bubble).map((w) => (
                <div key={w.id} ref={(el) => { if (el) bubbleRefs.current.set(w.id, el); else bubbleRefs.current.delete(w.id); }}
                  className={`jg-office__bubble is-${w.mood}`} style={{ maxWidth: Math.max(120, (CELL_W - 6) * scale) }} aria-hidden="true">{w.bubble}</div>
              ))}
            </div>
          )}
        </div>
      </div>
      {worker && <WorkerPanel key={worker.id} worker={worker} rows={orch.rows} source={source} onNavigate={onNavigate} onClose={() => setSelected(null)} />}
    </div>
  );
}

const STEP_KINDS = new Set(["tool", "model", "approval", "subagent", "input"]);
const clip = (t: string, n: number) => { const f = t.replace(/\s+/g, " ").trim(); return f.length > n ? `${f.slice(0, n - 1).trimEnd()}…` : f; };
const fmtMs = (ms: number | null) => (ms == null ? "" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);

function WorkerPanel({ worker, rows, source, onNavigate, onClose }: { worker: Worker; rows: ActivityRow[]; source: JaegerSource; onNavigate: (to: string) => void; onClose: () => void }) {
  const { events } = useProcessEvents(source, worker.sessionId ?? null);
  const steps = useMemo(() => {
    if (!events.length) return [] as Span[];
    const state = foldAll(events);
    return [...state.spans.values()].filter((s) => STEP_KINDS.has(String(s.kind))).sort((a, b) => b.startTs - a.startTs).slice(0, 8);
  }, [events]);
  const activity = useMemo(() => rows.filter((r) => r.agentId === worker.id).slice(0, 6), [rows, worker.id]);
  const task = worker.currentTask;
  const go = (to: string) => onNavigate(to);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <aside className="jg-office__panel" aria-label={`${worker.name} details`}>
      <header>
        <AgentAvatar name={worker.name} seed={worker.seed} size={40} status={worker.mood === "working" ? "working" : worker.mood === "error" ? "failed" : undefined} />
        <div>
          <h3>{worker.name}</h3>
          <span className={`jg-office__pill is-${worker.mood}`}>{worker.statusText}</span>
          {worker.live.runner && <span className="jg-office__runner">{worker.live.runner}</span>}
        </div>
        <button type="button" className="jg-office__close" aria-label="Close" onClick={onClose}>×</button>
      </header>
      <section>
        <h4>Current task</h4>
        {task ? <p className="jg-office__task" title={task.goal || undefined}>{clip(task.goal || task.task_id, 280)}<small>{String(task.state ?? "").replace(/_/g, " ")}{task.eta ? ` · ETA ${task.eta}` : ""}</small></p>
          : worker.handoff ? <p className="jg-office__task">{clip(worker.handoff.task ?? "", 280) || worker.statusText}</p>
          : <p className="jg-office__muted">{worker.mood === "idle" ? "Nothing running." : worker.mood === "offline" ? "Live status unavailable." : worker.bubble ?? worker.statusText}</p>}
      </section>
      <section>
        <h4>Recent steps</h4>
        {!worker.sessionId ? <p className="jg-office__muted">No session yet.</p> : steps.length ? (
          <ol className="jg-office__steps">
            {steps.map((s) => <li key={s.id} className={`is-${s.state}`}><i aria-hidden="true" /><span>{s.name || s.kind}</span><small>{s.state === "running" || s.state === "waiting" ? s.state : fmtMs(s.durationMs)}</small></li>)}
          </ol>
        ) : <p className="jg-office__muted">No traced steps in this agent's session.</p>}
      </section>
      {activity.length > 0 && (
        <section>
          <h4>Activity</h4>
          <ul className="jg-office__activity">{activity.map((r) => <li key={r.key}><span>{r.action}</span><small>{ago(r.at)}</small></li>)}</ul>
        </section>
      )}
      <footer>
        {worker.sessionId && <button type="button" className="jg-u-btn" onClick={() => go(`/work/process?session=${encodeURIComponent(worker.sessionId!)}`)}>Open in Process</button>}
        <button type="button" className="jg-u-btn" onClick={() => go(`/chat?agent=${encodeURIComponent(worker.id)}`)}>Open chat</button>
        {task?.task_id && !task.task_id.startsWith("turn:") && <button type="button" className="jg-u-btn" onClick={() => go(`/work/tasks?task=${encodeURIComponent(task.task_id)}`)}>Task</button>}
      </footer>
    </aside>
  );
}

export default PixelOffice;
