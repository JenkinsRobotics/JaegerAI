import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GatewayEvent } from "../api/types";
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
}

const POLL_MS = 15000;
const REFRESH_ON = new Set(["agent.handoff", "agent.handoff.finished", "task.created", "task.updated", "agent.created", "agent.updated"]);

export function useOrchestration(adapter: OrchestrationAdapter, opts: { backoffMs?: number } = {}): OrchestrationState & { live: ReturnType<typeof agentsLive> } {
  const [snapshot, setSnapshot] = useState<OrchestrationSnapshot>();
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [status, setStatus] = useState<OrchestrationState["status"]>("loading");
  const [error, setError] = useState<string>();
  const [stream, setStream] = useState<StreamState>("connecting");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [nonce, setNonce] = useState(0);
  const [nextBefore, setNextBefore] = useState<number>();
  const seen = useRef(new Set<number>());
  const snapRef = useRef<OrchestrationSnapshot | undefined>(undefined);

  const load = useCallback(async (initial = false) => {
    const snap = await adapter.snapshot();
    snapRef.current = snap;
    setSnapshot(snap);
    const names = namesFrom(snap.agents);
    let history: ActivityRow[] = [];
    if (adapter.gaps.activity) {
      const page = await adapter.gaps.activity({ names });
      history = page.rows; if (initial) setNextBefore(page.nextBefore); // refreshes keep the paging cursor
    }
    setRows((cur) => mergeRows(cur, [...backfill(snap, names), ...history], 2000));
  }, [adapter]);

  useEffect(() => {
    let alive = true;
    const ctl = new AbortController();
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
    const page = await adapter.gaps.activity({ before: nextBefore, names: namesFrom(snapRef.current?.agents ?? []) });
    setNextBefore(page.nextBefore);
    setRows((cur) => mergeRows(cur, page.rows, 2000));
  }, [adapter, nextBefore]);

  const live = useMemo(() => (snapshot ? agentsLive(snapshot, adapter.gaps, overrides) : []), [snapshot, adapter.gaps, overrides]);
  return { status, error, snapshot, rows, stream, live, retry: () => setNonce((n) => n + 1), loadOlder: nextBefore != null ? loadOlder : undefined };
}
