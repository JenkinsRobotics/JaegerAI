/* Live process model (HMI view). Pure fold of trace-carrying Gateway events into
 * spans: one run per user turn, model steps under it, tools under the step that
 * asked, approvals/sub-agents under their tool. Replaying the first N events
 * reproduces the plant state at that moment (scrub / replay). */
import type { GatewayEvent, TraceEnvelope } from "../api/types";

export type SpanState = NonNullable<TraceEnvelope["state"]> | "idle";
export interface Span {
  id: string;
  parent: string | null;
  kind: TraceEnvelope["kind"];
  name: string;
  state: SpanState;
  runId: string | null;
  startTs: number;
  endTs: number | null;
  durationMs: number | null;
  firstIndex: number;
  lastIndex: number;
  children: string[];
  detail?: string;
  /** 0..1 when the tool reports it (MCP-style progress/total). */
  progress?: number;
}
export interface ProcessState {
  spans: Map<string, Span>;
  runs: string[];
  /** Index of the last event folded in. */
  cursor: number;
  lastEvent?: GatewayEvent;
}

const ACTIVE: ReadonlySet<SpanState> = new Set(["running", "waiting"]);
export const isActive = (s: SpanState) => ACTIVE.has(s);
/** Spans the diagram draws (message/info/presence events annotate, they are not nodes). */
const NODE_KINDS: ReadonlySet<string> = new Set(["run", "model", "tool", "approval", "input", "subagent", "hook"]);

export function emptyState(): ProcessState {
  return { spans: new Map(), runs: [], cursor: -1 };
}

function detailOf(e: GatewayEvent): string | undefined {
  const p = (e.payload ?? {}) as Record<string, unknown>;
  if (e.event === "model.finished") {
    const u = (p.usage ?? {}) as Record<string, number>;
    const who = [p.provider, p.actual_model ?? p.model].filter((x) => typeof x === "string" && x).join(" · ");
    const tok = p.usage_reported === false ? "usage not reported" : `${u.prompt_tokens ?? 0} in · ${u.completion_tokens ?? 0} out tokens`;
    return [who, tok, typeof p.error === "string" ? p.error : ""].filter(Boolean).join(" · ").slice(0, 200);
  }
  const text = p.summary ?? p.message ?? p.prompt ?? p.error;
  return typeof text === "string" && text ? text.slice(0, 200) : undefined;
}

/** Fold one event (mutates and returns `state`). */
export function apply(state: ProcessState, e: GatewayEvent, index: number): ProcessState {
  state.cursor = index;
  state.lastEvent = e;
  const t = e.trace;
  if (!t || !t.span_id || !NODE_KINDS.has(t.kind)) return state;
  let span = state.spans.get(t.span_id);
  if (!span) {
    span = { id: t.span_id, parent: t.parent_span_id, kind: t.kind, name: t.name, state: t.state ?? "idle",
      runId: t.run_id, startTs: t.ts, endTs: null, durationMs: null, firstIndex: index, lastIndex: index, children: [] };
    state.spans.set(span.id, span);
    if (t.kind === "run") state.runs.push(span.id);
    const parent = span.parent ? state.spans.get(span.parent) : undefined;
    if (parent && !parent.children.includes(span.id)) parent.children.push(span.id);
  }
  if (t.state) span.state = t.state;
  if (t.name && t.name !== "tool" && !t.name.startsWith("model #")) span.name = t.name;
  if (!span.parent && t.parent_span_id) {
    span.parent = t.parent_span_id;
    const parent = state.spans.get(t.parent_span_id);
    if (parent && !parent.children.includes(span.id)) parent.children.push(span.id);
  }
  span.lastIndex = index;
  span.detail = detailOf(e) ?? span.detail;
  const fraction = (e.payload as Record<string, unknown> | undefined)?.fraction;
  if (typeof fraction === "number" && Number.isFinite(fraction)) span.progress = Math.max(0, Math.min(1, fraction));
  if (t.state && !isActive(t.state)) {
    span.endTs = t.ts;
    span.durationMs = t.duration_ms ?? Math.round((t.ts - span.startTs) * 1000);
  }
  return state;
}

export function foldAll(events: readonly GatewayEvent[], upTo = events.length - 1): ProcessState {
  const state = emptyState();
  for (let i = 0; i <= upTo && i < events.length; i++) apply(state, events[i], i);
  return state;
}

/** Steps of a run in order, each with its descendants flattened (tools, approvals, agents). */
export function columns(state: ProcessState, runId: string): { step: Span; below: Span[] }[] {
  const run = state.spans.get(runId);
  if (!run) return [];
  const walk = (id: string, out: Span[]) => {
    const s = state.spans.get(id); if (!s) return;
    out.push(s); s.children.forEach((c) => walk(c, out));
  };
  return run.children.map((id) => state.spans.get(id)).filter((s): s is Span => !!s)
    .sort((a, b) => a.firstIndex - b.firstIndex)
    .map((step) => { const below: Span[] = []; step.children.forEach((c) => walk(c, below)); return { step, below }; });
}

/** HMI annunciator lamps: which plant sections are energised right now. */
export function lamps(state: ProcessState) {
  let model = false, tool = false, waiting = false, fault = false, run = false;
  for (const s of state.spans.values()) {
    if (s.kind === "run" && s.state === "running") run = true;
    if (s.kind === "model" && s.state === "running") model = true;
    if ((s.kind === "tool" || s.kind === "subagent") && s.state === "running") tool = true;
    if (s.state === "waiting") waiting = true;
    if (s.state === "failed" && s.runId && state.spans.get(`run:${s.runId}`)?.state === "running") fault = true;
  }
  const last = state.runs.length ? state.spans.get(state.runs[state.runs.length - 1]) : undefined;
  if (last?.state === "failed" || last?.state === "unknown") fault = true;
  return { run, model, tool, waiting, fault };
}
