/* Process view — watch Jaeger work as it happens. A flow canvas (React Flow +
 * dagre) of the selected turn: turn → model steps → tools → sub-agents /
 * approvals / hooks, each node a card with live status marks and animated
 * edges while running; an inspector for the selected node; the eight framework
 * responsibilities as live status cards; and a trace waterfall with a scrubber
 * that replays the session's durable event log. Everything is folded from real
 * Gateway events (trace envelope, contract/trace.py) — no demo data.
 * Visual reference: n8n's canvas and Langfuse/Honeycomb waterfalls (patterns
 * only; no code from either). */
import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider,
  useNodesInitialized, useNodesState, useReactFlow, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Ban, Bot, Brain, CheckCircle2, Clock, Cpu, Database, FlagTriangleRight, GitBranch, HelpCircle, LifeBuoy, Loader2,
  Pause, Play, Radio, Repeat, ShieldCheck, Sparkles, SquareStack, Webhook, Wrench, XCircle, type LucideIcon,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent, SessionRow } from "../api/types";
import { foldAll, isActive, tree, type ProcessState, type Span, type SpanState } from "./model";
import { layout, NODE_H, NODE_W } from "./layout";
import { respOf, responsibilities, type Resp, type RespId } from "./responsibilities";
import { useProcessEvents } from "./useProcessEvents";
import { AgentAvatar } from "../team/AgentAvatar";
import "./process.css";
import "../team/team.css";

export const fmtMs = (ms: number | null | undefined) =>
  ms == null ? "" : ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;

const KIND: Record<string, { label: string; icon: LucideIcon }> = {
  run: { label: "Turn", icon: FlagTriangleRight }, model: { label: "Model step", icon: Brain }, tool: { label: "Tool", icon: Wrench },
  approval: { label: "Approval", icon: ShieldCheck }, input: { label: "Question", icon: HelpCircle }, subagent: { label: "Agent", icon: Bot },
  hook: { label: "Hook", icon: Webhook }, end: { label: "End", icon: SquareStack },
};
const RESP_ICON: Record<RespId, LucideIcon> = {
  models: Cpu, tools: Wrench, loop: Repeat, state: Database, permissions: ShieldCheck, orchestration: GitBranch, reliability: LifeBuoy, events: Radio,
};

/** Automated probe sessions (chat checks, audits) are real but not the operator's; hidden by default. */
export function isProbeSession(row: SessionRow & { metadata?: Record<string, unknown> }): boolean {
  if (row.metadata && (row.metadata as Record<string, unknown>).probe === true) return true;
  return /^(Process view demo|Events audit observation|Chat check\b|Cleanup check\b|Process check\b)/i.test(row.title ?? "");
}

function StatusMark({ state }: { state: SpanState | "idle" }) {
  const reduce = useReducedMotion();
  if (state === "running") return <motion.span className="jg-pv-mark is-running" aria-label="running" animate={reduce ? undefined : { rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}><Loader2 size={16} /></motion.span>;
  if (state === "succeeded") return <span className="jg-pv-mark is-succeeded" aria-label="succeeded"><CheckCircle2 size={16} /></span>;
  if (state === "failed" || state === "unknown") return <span className="jg-pv-mark is-failed" aria-label={state}><XCircle size={16} /></span>;
  if (state === "waiting") return <span className="jg-pv-mark is-waiting" aria-label="waiting"><Clock size={16} /></span>;
  if (state === "denied" || state === "cancelled") return <span className={`jg-pv-mark is-${state}`} aria-label={state}><Ban size={16} /></span>;
  return null;
}

type CardData = { span?: Span; kind: string; title: string; subtitle: string; state: SpanState | "idle"; selected?: boolean; progress?: number;
  agent?: AgentFace };
/** How an agent looks (Team roster): name + avatar seed/image. */
export type AgentFace = { name: string; seed?: string | null; url?: string | null };

/** "native:jaeger-design-style" -> "Jaeger Design Style" when the roster has no card for it. */
export function agentLabel(id: string): string {
  const bare = id.replace(/^[a-z]+:/, "");
  return bare.split(/[-_]/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ") || id;
}
type CardNode = Node<CardData, "card">;

const Card = memo(function Card({ data }: NodeProps<CardNode>) {
  const k = KIND[data.kind] ?? KIND.tool;
  const Icon = k.icon;
  return (
    <motion.div className={`jg-pv-card is-${data.state} jg-pv-card--${data.kind}${data.selected ? " is-selected" : ""}`}
      initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.18 }}
      style={{ width: NODE_W, height: NODE_H }}>
      <Handle type="target" position={Position.Left} className="jg-pv-handle" isConnectable={false} />
      {data.agent
        ? <div className="jg-pv-card__agent"><AgentAvatar name={data.agent.name} seed={data.agent.seed} url={data.agent.url} size={34} status={data.state} /></div>
        : <div className="jg-pv-card__icon"><Icon size={20} strokeWidth={1.75} /></div>}
      <div className="jg-pv-card__text">
        <div className="jg-pv-card__title" title={data.title}>{data.title}</div>
        <div className="jg-pv-card__subtitle" title={data.subtitle}>{data.subtitle}</div>
        {data.progress != null && <div className="jg-pv-card__bar" role="progressbar" aria-valuenow={Math.round(data.progress * 100)}><i style={{ width: `${Math.round(data.progress * 100)}%` }} /></div>}
      </div>
      <StatusMark state={data.state} />
      <Handle type="source" position={Position.Right} className="jg-pv-handle" isConnectable={false} />
    </motion.div>
  );
});
const nodeTypes = { card: Card };

function spanDuration(span: Span, now: number) {
  return isActive(span.state) ? Math.max(0, (now - span.startTs) * 1000) : span.durationMs;
}

function buildGraph(state: ProcessState, runId: string, now: number, selected: string | null, faces?: ReadonlyMap<string, AgentFace>) {
  const run = state.spans.get(runId);
  if (!run) return { nodes: [] as CardNode[], edges: [] as Edge[] };
  const nodes: CardNode[] = [];
  const edges: Edge[] = [];
  const faceOf = (s: Span): AgentFace | undefined => {
    if (s.kind !== "subagent") return undefined;
    const known = s.agentId ? faces?.get(s.agentId) : undefined;
    if (known) return known;
    const name = s.agentId && (s.name === s.agentId || s.name === "agent") ? agentLabel(s.agentId) : s.name;
    return { name, seed: s.agentId ?? s.name };
  };
  const card = (s: Span): CardNode => ({
    id: s.id, type: "card", position: { x: 0, y: 0 },
    data: { span: s, kind: s.kind, title: s.kind === "run" ? "Turn" : faceOf(s)?.name ?? s.name, state: s.state, selected: s.id === selected, progress: s.progress,
      agent: faceOf(s),
      subtitle: [KIND[s.kind]?.label ?? s.kind, fmtMs(spanDuration(s, now)), s.detail].filter(Boolean).join(" · ") },
  });
  const edge = (from: Span | { id: string; state: SpanState | "idle" }, to: { id: string; state: SpanState | "idle" }): Edge => ({
    id: `${from.id}->${to.id}`, source: from.id, target: to.id, type: "smoothstep",
    animated: isActive(to.state as SpanState), className: `jg-pv-edge is-${to.state}`,
  });
  nodes.push(card(run));
  const steps = run.children.map((id) => state.spans.get(id)).filter((s): s is Span => !!s).sort((a, b) => a.firstIndex - b.firstIndex);
  let prev: Span = run;
  const walk = (parent: Span) => {
    parent.children.map((id) => state.spans.get(id)).filter((s): s is Span => !!s).sort((a, b) => a.firstIndex - b.firstIndex)
      .forEach((c) => { nodes.push(card(c)); edges.push(edge(parent, c)); walk(c); });
  };
  for (const st of steps) {
    nodes.push(card(st)); edges.push(edge(prev, st)); walk(st);
    // Model steps chain the turn; so do top-level agent turns (a room's members speak in sequence).
    if (st.kind === "model" || st.kind === "subagent") prev = st;
  }
  const endState: SpanState | "idle" = run.state === "running" ? "idle" : run.state;
  nodes.push({ id: "__end", type: "card", position: { x: 0, y: 0 },
    data: { kind: "end", title: run.state === "running" ? "Waiting for the answer" : `Turn ${run.state}`, subtitle: `End · ${fmtMs(run.durationMs ?? spanDuration(run, now))}`, state: endState } });
  edges.push(edge(prev, { id: "__end", state: endState }));
  return { nodes: layout(nodes, edges), edges };
}

function Canvas({ state, runId, now, selected, onSelect, faces }: { state: ProcessState; runId: string; now: number; selected: string | null; onSelect: (id: string | null) => void; faces?: ReadonlyMap<string, AgentFace> }) {
  const graph = useMemo(() => buildGraph(state, runId, now, selected, faces), [state, runId, now, selected, faces]);
  const flow = useReactFlow();
  // React Flow keeps each card's measured size on the node object it is given.
  // Rebuilt nodes would drop it (and hide the card until re-measured), so merge
  // fresh layout + data onto the nodes React Flow already measured.
  const [nodes, setNodes, onNodesChange] = useNodesState<CardNode>([]);
  useEffect(() => {
    setNodes((prev) => {
      const byId = new Map(prev.map((n) => [n.id, n]));
      return graph.nodes.map((n) => {
        const old = byId.get(n.id);
        return old ? { ...old, position: n.position, data: n.data } : n;
      });
    });
  }, [graph, setNodes]);
  // Count the nodes React Flow holds (not the freshly built graph), so a refit
  // waits until the new cards are in the store and measured.
  const count = nodes.length;
  const measured = useNodesInitialized();
  const lastFit = useRef("");
  const fit = useCallback(() => void flow.fitView({ padding: 0.15, duration: 250, maxZoom: 1.1 }), [flow]);
  useEffect(() => {
    const key = `${runId}:${count}`;
    if (!count || key === lastFit.current) return;
    lastFit.current = key;
    // New cards are measured a frame or two after they mount; fit once they
    // are (when React Flow reports them initialised) and once more shortly after.
    const timers = [setTimeout(fit, 120), setTimeout(fit, 600)];
    return () => timers.forEach(clearTimeout);
  }, [fit, runId, count]);
  useEffect(() => { if (measured && count) fit(); }, [measured, count, fit]);
  // Refit when the canvas itself resizes (inspector opens/closes, window resize).
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let t: ReturnType<typeof setTimeout> | undefined;
    let w = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - w) < 8) return;
      w = el.clientWidth;
      clearTimeout(t);
      t = setTimeout(fit, 120);
    });
    ro.observe(el);
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [fit]);
  return (
    <div ref={box} className="jg-pv__flow">
    <ReactFlow nodes={nodes} edges={graph.edges} onNodesChange={onNodesChange} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false}
      elementsSelectable onNodeClick={(_, n) => onSelect(n.id === "__end" ? null : n.id)} onPaneClick={() => onSelect(null)}
      minZoom={0.2} maxZoom={1.75} proOptions={{ hideAttribution: true }} fitView>
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} className="jg-pv-bg" />
      <Controls showInteractive={false} className="jg-pv-controls" />
      <MiniMap pannable zoomable className="jg-pv-minimap" style={{ width: 168, height: 112 }} nodeClassName={(n) => `is-${(n.data as CardData).state}`} />
    </ReactFlow>
    </div>
  );
}

const PAYLOAD_KEYS = ["tool", "input", "args", "model", "actual_model", "provider", "location", "route_reason", "lane", "usage", "usage_reported",
  "duration_ms", "elapsed_s", "ok", "outcome", "error", "summary", "text", "message", "decision", "policy", "action", "hook", "reason", "status", "kind", "task", "name", "fraction"];

function Inspector({ span, events, now, onClose }: { span: Span; events: readonly GatewayEvent[]; now: number; onClose: () => void }) {
  const k = KIND[span.kind] ?? KIND.tool;
  const Icon = k.icon;
  const own = span.events.map((i) => events[i]).filter(Boolean);
  const merged: Record<string, unknown> = {};
  own.forEach((e) => Object.entries((e.payload ?? {}) as Record<string, unknown>).forEach(([key, v]) => {
    if (PAYLOAD_KEYS.includes(key) && v !== null && v !== "" && !(typeof v === "object" && !Object.keys(v as object).length)) merged[key] = v;
  }));
  return (
    <aside className="jg-pv-inspector" aria-label="Selected node">
      <header>
        <span className={`jg-pv-inspector__icon is-${span.state}`}><Icon size={18} /></span>
        <div><div className="jg-pv-inspector__title">{span.kind === "run" ? "Turn" : span.name}</div><div className="jg-pv-inspector__sub">{k.label} · <StatusMark state={span.state} /> {span.state}</div></div>
        <button type="button" className="jg-pv-iconbtn" onClick={onClose} aria-label="Close inspector">×</button>
      </header>
      <dl className="jg-pv-kv">
        <dt>Started</dt><dd>{new Date(span.startTs * 1000).toLocaleTimeString()}</dd>
        <dt>Duration</dt><dd>{fmtMs(spanDuration(span, now)) || "—"}{isActive(span.state) ? " (running)" : ""}</dd>
        <dt>Span</dt><dd><code>{span.id}</code></dd>
        {Object.entries(merged).map(([key, v]) => <Fragment key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{typeof v === "object" ? <pre>{JSON.stringify(v, null, 2)}</pre> : String(v)}</dd></Fragment>)}
      </dl>
      <h4>Events ({own.length})</h4>
      <ol className="jg-pv-raw">
        {own.map((e) => <li key={`${e.event_id}-${e.event}`}><details><summary><code>#{e.event_id}</code> {e.event} {e.trace?.state ? <em>→ {e.trace.state}</em> : null}</summary><pre>{JSON.stringify({ payload: e.payload, trace: e.trace }, null, 2)}</pre></details></li>)}
      </ol>
    </aside>
  );
}

function RespCard({ r, active, onClick }: { r: Resp; active: boolean; onClick: () => void }) {
  const Icon = RESP_ICON[r.id];
  return (
    <button type="button" className={`jg-pv-resp is-${r.tone}${active ? " is-active" : ""}`} onClick={onClick} title={r.detail} aria-pressed={active}>
      <span className="jg-pv-resp__icon"><Icon size={16} /></span>
      <span className="jg-pv-resp__body"><span className="jg-pv-resp__label">{r.label}<i className="jg-pv-dot" /></span><span className="jg-pv-resp__value">{r.value}</span><span className="jg-pv-resp__detail">{r.detail}</span></span>
    </button>
  );
}

function Waterfall({ state, runId, now, selected, onSelect }: { state: ProcessState; runId: string; now: number; selected: string | null; onSelect: (id: string) => void }) {
  const rows = tree(state, runId);
  const run = state.spans.get(runId);
  if (!run) return null;
  const t0 = run.startTs;
  // A finished turn's axis ends where its last span ended, not at the wall clock.
  const tEnd = isActive(run.state) ? Math.max(now, ...rows.map((r) => r.span.endTs ?? now))
    : Math.max(run.endTs ?? run.startTs, ...rows.map((r) => r.span.endTs ?? r.span.startTs));
  const total = Math.max(0.001, tEnd - t0);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="jg-pv-wf" role="table" aria-label="Trace waterfall">
      <div className="jg-pv-wf__head" role="row"><span role="columnheader">Span</span><span role="columnheader" className="jg-pv-wf__axis">{ticks.map((t) => <i key={t} style={{ left: `${t * 100}%` }}>{fmtMs(t * total * 1000) || "0 ms"}</i>)}</span><span role="columnheader">Duration</span></div>
      {rows.map(({ span, depth }) => {
        const k = KIND[span.kind] ?? KIND.tool;
        const Icon = k.icon;
        const left = ((span.startTs - t0) / total) * 100;
        const width = Math.max(0.4, (((span.endTs ?? now) - span.startTs) / total) * 100);
        return (
          <div key={span.id} role="row" className={`jg-pv-wf__row${span.id === selected ? " is-selected" : ""}`} onClick={() => onSelect(span.id)} tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") onSelect(span.id); }}>
            <span role="cell" className="jg-pv-wf__name" style={{ paddingLeft: `${depth * 14 + 6}px` }}><Icon size={13} /> {span.kind === "run" ? "Turn" : span.name}</span>
            <span role="cell" className="jg-pv-wf__track">
              {ticks.slice(1, -1).map((t) => <b key={t} style={{ left: `${t * 100}%` }} />)}
              <i className={`jg-pv-wf__bar is-${span.state}`} style={{ left: `${Math.min(99.6, left)}%`, width: `${Math.min(100 - left, width)}%` }} />
              <span className="jg-pv-wf__playhead" style={{ left: `${Math.min(100, ((now - t0) / total) * 100)}%` }} />
            </span>
            <span role="cell" className="jg-pv-wf__dur">{fmtMs(spanDuration(span, now))}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Team roster faces (name + avatar) by agent id, so agent nodes look like the Team page. */
function useAgentFaces(source: JaegerSource): ReadonlyMap<string, AgentFace> | undefined {
  const [faces, setFaces] = useState<ReadonlyMap<string, AgentFace>>();
  useEffect(() => {
    let live = true;
    source.team?.snapshot().then((snap) => {
      if (live) setFaces(new Map(snap.agents.map((a) => [a.id, { name: a.display_name, seed: a.avatar.seed, url: a.avatar.url }])));
    }).catch(() => undefined);
    return () => { live = false; };
  }, [source]);
  return faces;
}

function ProcessInner({ source, params }: { source: JaegerSource; params?: URLSearchParams }) {
  const faces = useAgentFaces(source);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [showProbes, setShowProbes] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(params?.get("session") ?? null);
  const [scrub, setScrub] = useState<number | null>(null); // null = live
  const [runPick, setRunPick] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"waterfall" | "log">("waterfall");
  const [respFilter, setRespFilter] = useState<RespId | null>(null);
  const [clock, setClock] = useState(() => Date.now() / 1000);
  const playing = useRef<ReturnType<typeof setInterval> | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    let live = true;
    void source.sessions().then((rows) => { if (live) setSessions([...rows].filter((r) => !r.archived).sort((a, b) => (b.last_activity_at ?? b.updated_at ?? 0) - (a.last_activity_at ?? a.updated_at ?? 0))); }).catch(() => undefined);
    return () => { live = false; };
  }, [source]);
  const visible = useMemo(() => sessions.filter((r) => showProbes || !isProbeSession(r) || r.session_id === sessionId).slice(0, 60), [sessions, showProbes, sessionId]);
  useEffect(() => { if (!sessionId && visible[0]) setSessionId(visible[0].session_id); }, [sessionId, visible]);

  const { events, health, hasOlder, loadOlder } = useProcessEvents(source, sessionId);
  useEffect(() => { setScrub(null); setRunPick(null); setSelected(null); }, [sessionId]);
  useEffect(() => { const t = setInterval(() => setClock(Date.now() / 1000), 250); return () => clearInterval(t); }, []);
  useEffect(() => () => { if (playing.current) clearInterval(playing.current); }, []);

  const upTo = scrub ?? events.length - 1;
  const state = useMemo(() => foldAll(events, upTo), [events, upTo]);
  const runId = runPick && state.spans.has(runPick) ? runPick : state.runs[state.runs.length - 1] ?? null;
  const run = runId ? state.spans.get(runId) : undefined;
  const now = scrub == null ? clock : (events[upTo]?.trace?.ts ?? events[upTo]?.created_at ?? clock);
  const resp = useMemo(() => responsibilities(events, upTo, runId, health), [events, upTo, runId, health]);
  const selSpan = selected ? state.spans.get(selected) : undefined;

  const stop = useCallback(() => { if (playing.current) clearInterval(playing.current); playing.current = null; setIsPlaying(false); }, []);
  const play = () => {
    if (playing.current) { stop(); return; }
    const start = run ? run.firstIndex : 0;
    setScrub(start); setIsPlaying(true);
    playing.current = setInterval(() => setScrub((cur) => {
      const next = (cur ?? start) + 1;
      if (next >= events.length - 1) { stop(); return null; }
      return next;
    }), 120);
  };

  const log = useMemo(() => {
    const rid = runId?.replace(/^run:/, "");
    return events.slice(0, upTo + 1).filter((e) => (!respFilter || respOf(e.event) === respFilter) && (!rid || ((e.payload as Record<string, unknown>)?.request_id ?? rid) === rid)).slice(-200).reverse();
  }, [events, upTo, respFilter, runId]);

  return (
    <section className="jg-pv" aria-label="Live process view">
      <header className="jg-pv__bar">
        <div className="jg-pv__title"><Sparkles size={16} /> Process</div>
        <label className="jg-pv__field">Session
          <select value={sessionId ?? ""} onChange={(e) => setSessionId(e.target.value || null)}>
            {visible.length === 0 && <option value="">No conversations yet</option>}{visible.map((s) => <option key={s.session_id} value={s.session_id}>{(s.title || s.session_id).slice(0, 60)}</option>)}
          </select>
        </label>
        <label className="jg-pv__check"><input type="checkbox" checked={showProbes} onChange={(e) => setShowProbes(e.target.checked)} /> Show test sessions</label>
        {hasOlder && <button type="button" className="jg-pv-btn" onClick={() => void loadOlder()}>Load older turns</button>}
        <span className={`jg-pv__link is-${health.link}`} title={`replayed ${health.replayed} · reconnects ${health.reconnects} · seq gaps ${health.gaps}`}><i className="jg-pv-dot" />{health.link === "live" ? "Live" : health.link}</span>
      </header>

      {health.link === "unsupported" ? <p className="jg-pv__empty">Process needs a live Gateway connection.</p> : <>
        <div className="jg-pv__resps" role="list" aria-label="Status">
          {resp.map((r) => <RespCard key={r.id} r={r} active={respFilter === r.id} onClick={() => { setRespFilter((f) => (f === r.id ? null : r.id)); setTab("log"); }} />)}
        </div>

        {state.runs.length > 0 && <div className="jg-pv__runs" role="tablist" aria-label="Turns">
          {state.runs.map((id, i) => { const r = state.spans.get(id)!; return (
            <button key={id} type="button" role="tab" aria-selected={id === runId} className={`jg-pv-chip is-${r.state}`} onClick={() => { setRunPick(id); setSelected(null); }}>
              <i className="jg-pv-dot" />Turn {i + 1}<small>{fmtMs(r.durationMs ?? spanDuration(r, now))}</small>
            </button>); })}
        </div>}

        <div className={`jg-pv__main${selSpan ? " has-inspector" : ""}`}>
          <div className="jg-pv__canvas">
            {runId ? <Canvas state={state} runId={runId} now={now} selected={selected} onSelect={setSelected} faces={faces} />
              : <p className="jg-pv__empty">{!sessionId ? "Select a conversation to inspect its turns." : events.length ? "This conversation has no recorded activity yet." : "Waiting for events…"}</p>}
          </div>
          {selSpan && <Inspector span={selSpan} events={events} now={now} onClose={() => setSelected(null)} />}
        </div>

        <div className="jg-pv__replay">
          <button type="button" className="jg-pv-btn" onClick={play} disabled={!events.length} aria-label={isPlaying ? "Pause replay" : "Replay turn"}>{isPlaying ? <Pause size={14} /> : <Play size={14} />} {isPlaying ? "Pause" : "Replay"}</button>
          <button type="button" className={`jg-pv-btn${scrub == null ? " is-on" : ""}`} onClick={() => { stop(); setScrub(null); }}><Radio size={14} /> Live</button>
          <input type="range" min={0} max={Math.max(0, events.length - 1)} value={upTo < 0 ? 0 : upTo} aria-label="Scrub the event log"
            onChange={(e) => { stop(); const v = Number(e.target.value); setScrub(v >= events.length - 1 ? null : v); }} />
          <span className="jg-pv__pos">{events.length ? `event ${upTo + 1} / ${events.length}` : "no events"}{events[upTo]?.created_at ? ` · ${new Date(events[upTo].created_at! * 1000).toLocaleTimeString()}` : ""}</span>
        </div>

        <div className="jg-pv__panel">
          <div className="jg-pv__tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "waterfall"} onClick={() => setTab("waterfall")}>Waterfall</button>
            <button type="button" role="tab" aria-selected={tab === "log"} onClick={() => setTab("log")}>Event log{respFilter ? ` · ${resp.find((r) => r.id === respFilter)?.label}` : ""}</button>
            {respFilter && <button type="button" className="jg-pv-link" onClick={() => setRespFilter(null)}>clear filter</button>}
          </div>
          {tab === "waterfall" ? (runId ? <Waterfall state={state} runId={runId} now={now} selected={selected} onSelect={setSelected} /> : null) : (
            <ol className="jg-pv-log">
              {log.map((e) => <li key={`${e.event_id}-${e.event}`} className={e.trace?.state ? `is-${e.trace.state}` : ""}>
                <code>#{e.event_id ?? "—"}</code><b>{e.event}</b><span>{e.trace ? `${e.trace.span_id}${e.trace.state ? ` → ${e.trace.state}` : ""}${e.trace.duration_ms != null ? ` (${fmtMs(e.trace.duration_ms)})` : ""}` : ""}</span>
              </li>)}
            </ol>)}
        </div>
      </>}
    </section>
  );
}

export function ProcessView(props: { source: JaegerSource; params?: URLSearchParams }) {
  return <ReactFlowProvider><ProcessInner {...props} /></ReactFlowProvider>;
}
export default ProcessView;
