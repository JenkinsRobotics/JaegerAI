/* Process view — watch Jaeger like a plant HMI. Annunciator lamps on top, a live
 * flow diagram (turn → model steps → tools → approvals / sub-agents) lit by span
 * state, a Gantt timeline with a playhead, and a scrubber that replays the
 * session's durable event log. Everything is folded from the Gateway's single
 * event stream (trace envelope, contract/trace.py); nothing is polled. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent, SessionRow } from "../api/types";
import { columns, foldAll, isActive, lamps, type Span } from "./model";
import "./process.css";

const MAX_EVENTS = 5000;
const BACKOFF = [250, 500, 1000, 2000, 4000];

const fmtMs = (ms: number | null | undefined) =>
  ms == null ? "" : ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
const KIND_LABEL: Record<string, string> = { run: "Turn", model: "Model", tool: "Tool", approval: "Approval", input: "Question", subagent: "Agent", hook: "Hook" };

function Lamp({ on, label, tone }: { on: boolean; label: string; tone: string }) {
  return <div className={`jg-proc-lamp jg-proc-lamp--${tone}${on ? " is-on" : ""}`} role="status" aria-label={`${label} ${on ? "on" : "off"}`}><i />{label}</div>;
}

function Node({ span, now }: { span: Span; now: number }) {
  const live = isActive(span.state);
  const dur = live ? Math.max(0, Math.round((now - span.startTs) * 1000)) : span.durationMs;
  return (
    <div className={`jg-proc-node jg-proc-node--${span.kind} is-${span.state}`} title={span.detail ?? span.id} data-span={span.id}>
      <div className="jg-proc-node__kind">{KIND_LABEL[span.kind] ?? span.kind}</div>
      <div className="jg-proc-node__name">{span.name}</div>
      <div className="jg-proc-node__meta"><span className="jg-proc-node__state">{span.state}</span>{dur != null && <span>{fmtMs(dur)}</span>}</div>
    </div>
  );
}

export function ProcessView({ source, params }: { source: JaegerSource; params?: URLSearchParams }) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(params?.get("session") ?? null);
  const [events, setEvents] = useState<GatewayEvent[]>([]);
  const [scrub, setScrub] = useState<number | null>(null); // null = live
  const [runPick, setRunPick] = useState<string | null>(null);
  const [link, setLink] = useState<"connecting" | "live" | "retrying" | "unsupported">("connecting");
  const [clock, setClock] = useState(() => Date.now() / 1000);
  const playing = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let live = true;
    void source.sessions().then((rows) => {
      if (!live) return;
      const sorted = [...rows].filter((r) => !r.archived).sort((a, b) => (b.last_activity_at ?? b.updated_at ?? 0) - (a.last_activity_at ?? a.updated_at ?? 0));
      setSessions(sorted.slice(0, 40));
      setSessionId((cur) => cur ?? sorted[0]?.session_id ?? null);
    }).catch(() => undefined);
    return () => { live = false; };
  }, [source]);

  // One live, resumable subscription per session (cursor = last seen event_id).
  useEffect(() => {
    if (!sessionId) return;
    if (!source.processStream) { setLink("unsupported"); return; }
    const abort = new AbortController();
    let cursor = 0, attempt = 0;
    setEvents([]); setScrub(null); setRunPick(null); setLink("connecting");
    const batch: GatewayEvent[] = [];
    let flush: ReturnType<typeof setTimeout> | undefined;
    const push = (e: GatewayEvent) => {
      if (typeof e.event_id === "number") { if (e.event_id <= cursor) return; cursor = e.event_id; }
      batch.push(e);
      if (!flush) flush = setTimeout(() => {
        flush = undefined;
        const add = batch.splice(0);
        setEvents((cur) => { const next = cur.concat(add); return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next; });
      }, 50); // ≤20 renders/s however fast tokens arrive
    };
    void (async () => {
      while (!abort.signal.aborted) {
        try {
          setLink(attempt ? "retrying" : "connecting");
          const opened = source.processStream!(sessionId, cursor, (e) => { attempt = 0; setLink("live"); push(e); }, abort.signal);
          setTimeout(() => { if (!abort.signal.aborted) setLink((l) => (l === "connecting" ? "live" : l)); }, 400);
          await opened;
        } catch (err) {
          if (abort.signal.aborted) return;
          if ((err as { status?: number }).status === 410) cursor = 0; // cursor aged out: restart
        }
        if (abort.signal.aborted) return;
        setLink("retrying");
        await new Promise((r) => setTimeout(r, BACKOFF[Math.min(attempt++, BACKOFF.length - 1)]));
      }
    })();
    return () => { abort.abort(); clearTimeout(flush); };
  }, [source, sessionId]);

  useEffect(() => { const t = setInterval(() => setClock(Date.now() / 1000), 250); return () => clearInterval(t); }, []);
  useEffect(() => () => { if (playing.current) clearInterval(playing.current); }, []);

  const upTo = scrub ?? events.length - 1;
  const state = useMemo(() => foldAll(events, upTo), [events, upTo]);
  const runId = runPick && state.spans.has(runPick) ? runPick : state.runs[state.runs.length - 1] ?? null;
  const run = runId ? state.spans.get(runId) : undefined;
  const cols = runId ? columns(state, runId) : [];
  const lamp = lamps(state);
  const now = scrub == null ? clock : (events[upTo]?.trace?.ts ?? events[upTo]?.created_at ?? clock);

  const play = () => {
    if (playing.current) { clearInterval(playing.current); playing.current = null; return; }
    const start = run ? run.firstIndex : 0;
    setScrub(start);
    playing.current = setInterval(() => {
      setScrub((cur) => {
        const next = (cur ?? start) + 1;
        if (next >= events.length - 1) { if (playing.current) clearInterval(playing.current); playing.current = null; return null; }
        return next;
      });
    }, 120);
  };

  const gantt = useMemo(() => {
    if (!run) return { rows: [] as Span[], t0: 0, span: 1 };
    const rows: Span[] = [run];
    cols.forEach((c) => { rows.push(c.step, ...c.below); });
    const t0 = run.startTs;
    const tEnd = Math.max(now, ...rows.map((r) => r.endTs ?? now));
    return { rows, t0, span: Math.max(0.001, tEnd - t0) };
  }, [run, cols, now]);

  const log = events.slice(Math.max(0, upTo - 39), upTo + 1).reverse();

  return (
    <section className="jg-proc" aria-label="Live process view">
      <header className="jg-proc__bar">
        <label>Session <select value={sessionId ?? ""} onChange={(e) => setSessionId(e.target.value || null)}>
          {sessions.map((s) => <option key={s.session_id} value={s.session_id}>{(s.title || s.session_id).slice(0, 60)}</option>)}
        </select></label>
        <div className="jg-proc__lamps">
          <Lamp on={lamp.run} label="RUN" tone="run" />
          <Lamp on={lamp.model} label="MODEL" tone="model" />
          <Lamp on={lamp.tool} label="TOOL" tone="tool" />
          <Lamp on={lamp.waiting} label="WAITING ON YOU" tone="wait" />
          <Lamp on={lamp.fault} label="FAULT" tone="fault" />
        </div>
        <span className={`jg-proc__link is-${link}`}>{link === "live" ? "● live" : link}</span>
      </header>

      {link === "unsupported" && <p className="jg-proc__empty">The process view needs the live Gateway.</p>}

      <nav className="jg-proc__runs" aria-label="Turns">
        {state.runs.slice(-10).map((id, i, arr) => { const r = state.spans.get(id)!; return (
          <button key={id} type="button" aria-pressed={id === runId} className={`is-${r.state}`} onClick={() => setRunPick(id)}>
            Turn {state.runs.length - arr.length + i + 1}<small>{r.state}{r.durationMs != null ? ` · ${fmtMs(r.durationMs)}` : ""}</small>
          </button>); })}
      </nav>

      <div className="jg-proc__flow" role="group" aria-label="Flow">
        {!run && <p className="jg-proc__empty">No turns yet in this session. Send a message and watch it run.</p>}
        {run && <>
          <div className="jg-proc__col"><Node span={run} now={now} /></div>
          {cols.map(({ step, below }) => (
            <div className="jg-proc__col" key={step.id}>
              <span className={`jg-proc__pipe${isActive(step.state) ? " is-flowing" : ""}`} aria-hidden />
              <Node span={step} now={now} />
              {below.map((b) => <div className="jg-proc__branch" key={b.id}><span className={`jg-proc__drop${isActive(b.state) ? " is-flowing" : ""}`} aria-hidden /><Node span={b} now={now} /></div>)}
            </div>
          ))}
          <div className="jg-proc__col">
            <span className={`jg-proc__pipe${run.state === "running" ? " is-flowing" : ""}`} aria-hidden />
            <div className={`jg-proc-node jg-proc-node--end is-${run.state === "running" ? "idle" : run.state}`}>
              <div className="jg-proc-node__kind">End</div><div className="jg-proc-node__name">{run.state === "running" ? "…" : run.state}</div>
            </div>
          </div>
        </>}
      </div>

      {run && <div className="jg-proc__gantt" aria-label="Timeline">
        {gantt.rows.map((r) => {
          const left = ((r.startTs - gantt.t0) / gantt.span) * 100;
          const width = Math.max(0.6, (((r.endTs ?? now) - r.startTs) / gantt.span) * 100);
          return <div className="jg-proc__grow" key={r.id}><span className="jg-proc__glabel">{KIND_LABEL[r.kind]} · {r.name}</span>
            <span className="jg-proc__gtrack"><i className={`jg-proc__gbar is-${r.state}`} style={{ left: `${left}%`, width: `${Math.min(100 - left, width)}%` }} /></span></div>;
        })}
        <div className="jg-proc__playhead" style={{ left: `calc(12rem + (100% - 12rem) * ${Math.min(1, Math.max(0, (now - gantt.t0) / gantt.span))})` }} aria-hidden />
      </div>}

      <div className="jg-proc__scrub">
        <button type="button" onClick={play}>{playing.current ? "Pause" : "Replay turn"}</button>
        <input type="range" min={0} max={Math.max(0, events.length - 1)} value={Math.max(0, upTo)} aria-label="Scrub event history"
          onChange={(e) => { const v = Number(e.target.value); setScrub(v >= events.length - 1 ? null : v); }} />
        <button type="button" aria-pressed={scrub == null} onClick={() => { if (playing.current) { clearInterval(playing.current); playing.current = null; } setScrub(null); }}>Live</button>
        <span>{Math.max(0, upTo + 1)} / {events.length} events</span>
      </div>

      <ol className="jg-proc__log" aria-label="Event log">
        {log.map((e) => <li key={`${e.event_id}-${e.event}`} className={e.trace?.state ? `is-${e.trace.state}` : ""}>
          <code>#{e.event_id}</code><b>{e.event}</b>{e.trace ? <span>{e.trace.span_id}{e.trace.state ? ` → ${e.trace.state}` : ""}{e.trace.duration_ms != null ? ` (${fmtMs(e.trace.duration_ms)})` : ""}</span> : null}
        </li>)}
      </ol>
    </section>
  );
}
