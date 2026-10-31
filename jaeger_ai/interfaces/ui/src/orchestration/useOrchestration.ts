import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GatewayEvent, Handoff } from "../api/types";
import type { OrchestrationAdapter } from "./adapter";
import { agentsLive } from "./adapter";
import { backfill, eventRow, mergeRows, namesFrom } from "./feed";
import type { ActivityRow, OrchestrationSnapshot } from "./types";

export type StreamState = "connecting" | "live" | "reconnecting" | "polling";
export interface OrchestrationState {
  status: "loading" | "ready" | "error";
  error?: string;
  snapshot?: OrchestrationSnapshot;
  rows: ActivityRow[];
  stream: StreamState;
  retry(): void;
  /** G1 paging: undefined when there's nothing older. */
  loadOlder?: () => Promise<void>;
  /** G1 history failed; the feed still shows the snapshot backfill. */
  historyError?: string;
}

const POLL_MS = 15000;
const REFRESH_ON = new Set(["agent.handoff", "agent.handoff.finished", "task.created", "task.updated", "agent.created", "agent.updated"]);

export function useOrchestration(adapter: OrchestrationAdapter, opts: { backoffMs?: number; callerId?: string } = {}): OrchestrationState & { live: ReturnType<typeof agentsLive> } {
  const [snapshot, setSnapshot] = useState<OrchestrationSnapshot>();
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [status, setStatus] = useState<OrchestrationState["status"]>("loading");
  const [error, setError] = useState<string>();
  const [stream, setStream] = useState<StreamState>("connecting");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [nonce, setNonce] = useState(0);
  const [nextBefore, setNextBefore] = useState<number>();
  const [historyError, setHistoryError] = useState<string>();
  const seen = useRef(new Set<number>());
  const eventHandoffs = useRef(new Map<string, Handoff>());
  const snapRef = useRef<OrchestrationSnapshot | undefined>(undefined);

  const load = useCallback(async (initial = false) => {
    let snap = await adapter.snapshot();
    for (const h of eventHandoffs.current.values()) {
      const cur = snap.handoffs.find((x) => x.id === h.id);
      if (!cur || (cur.updated_at ?? 0) <= (h.updated_at ?? 0)) snap = patchHandoff(snap, h) ?? snap;
    }
    snapRef.current = snap;
    setSnapshot(snap);
    const names = namesFrom(snap.agents);
    let history: ActivityRow[] = [];
    if (adapter.gaps.activity) {
      try {
        const page = await adapter.gaps.activity({ names, agentId: opts.callerId });
        history = page.rows; if (initial) setNextBefore(page.nextBefore); // refreshes keep the paging cursor
        setHistoryError(undefined);
      } catch (e) { setHistoryError(e instanceof Error ? e.message : String(e)); }
    }
    setRows((cur) => mergeRows(cur, [...backfill(snap, names), ...history], 2000));
  }, [adapter, opts.callerId]);

  useEffect(() => {
    let alive = true;
    const ctl = new AbortController();
    setRows([]); // a new caller filter starts a fresh feed
    setStatus("loading");
    load(true).then(() => alive && setStatus("ready"), (e: unknown) => {
      if (!alive) return;
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    });

    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const onEvent = (e: GatewayEvent) => {
      if (!alive) return;
      setStream("live");
      if (typeof e.event_id === "number") { if (seen.current.has(e.event_id)) return; seen.current.add(e.event_id); }
      if (e.event === "agent.status.changed") {
        const p = e.payload ?? {};
        const id = String(p.agent_id ?? ""); if (id) setOverrides((o) => ({ ...o, [id]: String(p.status ?? "idle") }));
      }
      const h = handoffOf(e);
      if (h) {
        eventHandoffs.current.set(h.id, h); // replayed onto snapshots that load later
        const patched = patchHandoff(snapRef.current, h);
        if (patched) { snapRef.current = patched; setSnapshot(patched); }
      }
      const row = eventRow(e, namesFrom(snapRef.current?.agents ?? []));
      if (row) setRows((cur) => mergeRows(cur, [row], 2000));
      if (REFRESH_ON.has(e.event)) { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => { if (alive) load().catch(() => undefined); }, 400); }
    };

    let pollTimer: ReturnType<typeof setInterval> | undefined;
    const startPolling = () => { setStream("polling"); pollTimer = setInterval(() => load().catch(() => undefined), POLL_MS); };
    if (!adapter.follow) startPolling();
    else (async () => {
      let delay = opts.backoffMs ?? 1000;
      for (let attempt = 0; alive && attempt < 6; attempt++) {
        try { setStream(attempt ? "reconnecting" : "connecting"); await adapter.follow!(onEvent, ctl.signal); delay = opts.backoffMs ?? 1000; }
        catch { if (!alive) return; }
        if (!alive) return;
        setStream("reconnecting");
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 30000);
      }
      if (alive) startPolling();
    })();

    return () => { alive = false; ctl.abort(); clearInterval(pollTimer); clearTimeout(refreshTimer); };
  }, [adapter, load, nonce, opts.backoffMs]);

  const loadOlder = useCallback(async () => {
    if (!adapter.gaps.activity || nextBefore == null) return;
    const page = await adapter.gaps.activity({ before: nextBefore, agentId: opts.callerId, names: namesFrom(snapRef.current?.agents ?? []) });
    setNextBefore(page.nextBefore);
    setRows((cur) => mergeRows(cur, page.rows, 2000));
  }, [adapter, nextBefore, opts.callerId]);

  const live = useMemo(() => (snapshot ? agentsLive(snapshot, adapter.gaps, overrides) : []), [snapshot, adapter.gaps, overrides]);
  return { status, error, snapshot, rows, stream, live, historyError, retry: () => setNonce((n) => n + 1), loadOlder: nextBefore != null ? loadOlder : undefined };
}

/** Handoff events carry the full record ({handoff}). */
export function handoffOf(e: GatewayEvent): Handoff | undefined {
  if (!e.event.startsWith("agent.handoff")) return undefined;
  const h = (e.payload as { handoff?: Handoff } | undefined)?.handoff;
  return h && typeof h === "object" && h.id ? h : undefined;
}

/** Merge an event's handoff into the snapshot so the inspector updates with
 * the feed row (no refetch). */
export function patchHandoff(snap: OrchestrationSnapshot | undefined, h: Handoff): OrchestrationSnapshot | undefined {
  if (!snap) return undefined;
  const i = snap.handoffs.findIndex((x) => x.id === h.id);
  const handoffs = i < 0 ? [h, ...snap.handoffs] : snap.handoffs.map((x, j) => (j === i ? { ...x, ...h } : x));
  return { ...snap, handoffs };
}
