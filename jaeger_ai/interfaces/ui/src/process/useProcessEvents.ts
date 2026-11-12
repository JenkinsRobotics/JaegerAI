/* One session's process events: durable history first (older turns replay even
 * after they leave the bounded SSE window), then the live scoped stream resumed
 * from the newest history id. Also reports stream health (connected, replayed,
 * reconnects, per-run seq gaps) — the "Events" responsibility, measured here. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";

export const MAX_EVENTS = 8000;
const BACKOFF = [250, 500, 1000, 2000, 4000];

export type Link = "connecting" | "live" | "retrying" | "unsupported";
export interface StreamHealth {
  link: Link;
  /** Events loaded from durable history before going live. */
  replayed: number;
  /** Successful reconnects after the first connect. */
  reconnects: number;
  /** Missing per-run sequence numbers observed live (0 = gap-free). */
  gaps: number;
  /** A cursor aged out of retention and the stream restarted from history. */
  expired: number;
  lastEventAt: number | null;
}

export function useProcessEvents(source: JaegerSource, sessionId: string | null) {
  const [events, setEvents] = useState<GatewayEvent[]>([]);
  const [hasOlder, setHasOlder] = useState(false);
  const [health, setHealth] = useState<StreamHealth>({ link: "connecting", replayed: 0, reconnects: 0, gaps: 0, expired: 0, lastEventAt: null });
  const oldest = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!sessionId) return;
    if (!source.processStream) { setHealth((h) => ({ ...h, link: "unsupported" })); return; }
    const abort = new AbortController();
    let cursor = 0, attempt = 0, connects = 0;
    const lastSeq = new Map<string, number>();
    setEvents([]); setHasOlder(false); oldest.current = undefined;
    setHealth({ link: "connecting", replayed: 0, reconnects: 0, gaps: 0, expired: 0, lastEventAt: null });
    const batch: GatewayEvent[] = [];
    let flush: ReturnType<typeof setTimeout> | undefined;
    const push = (e: GatewayEvent) => {
      if (typeof e.event_id === "number") { if (e.event_id <= cursor) return; cursor = e.event_id; }
      const t = e.trace;
      if (t?.run_id && typeof t.seq === "number") {
        const prev = lastSeq.get(t.run_id);
        if (prev != null && t.seq > prev + 1) setHealth((h) => ({ ...h, gaps: h.gaps + (t.seq! - prev - 1) }));
        lastSeq.set(t.run_id, t.seq);
      }
      batch.push(e);
      if (!flush) flush = setTimeout(() => {
        flush = undefined;
        const add = batch.splice(0);
        setHealth((h) => ({ ...h, lastEventAt: Date.now() / 1000 }));
        setEvents((cur) => { const next = cur.concat(add); return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next; });
      }, 50); // ≤20 renders/s however fast tokens arrive
    };
    const loadHistory = async () => {
      if (!source.processHistory) return;
      try {
        const page = await source.processHistory(sessionId);
        if (abort.signal.aborted) return;
        const newest = page.events.at(-1)?.event_id ?? 0;
        cursor = Math.max(cursor, newest);
        oldest.current = page.events[0]?.event_id;
        setHasOlder(page.hasMore);
        setEvents(page.events);
        setHealth((h) => ({ ...h, replayed: page.events.length }));
      } catch { /* history is optional; the live stream still replays its window */ }
    };
    void (async () => {
      await loadHistory();
      while (!abort.signal.aborted) {
        try {
          setHealth((h) => ({ ...h, link: attempt ? "retrying" : "connecting" }));
          const opened = source.processStream!(sessionId, cursor, (e) => {
            if (attempt || connects === 0) { connects++; if (connects > 1) setHealth((h) => ({ ...h, reconnects: h.reconnects + 1 })); }
            attempt = 0; setHealth((h) => (h.link === "live" ? h : { ...h, link: "live" })); push(e);
          }, abort.signal);
          setTimeout(() => { if (!abort.signal.aborted) setHealth((h) => (h.link === "connecting" ? { ...h, link: "live" } : h)); }, 400);
          await opened;
        } catch (err) {
          if (abort.signal.aborted) return;
          if ((err as { status?: number }).status === 410) { // cursor aged out: rebuild from durable history
            setHealth((h) => ({ ...h, expired: h.expired + 1 }));
            cursor = 0; await loadHistory();
          }
        }
        if (abort.signal.aborted) return;
        setHealth((h) => ({ ...h, link: "retrying" }));
        await new Promise((r) => setTimeout(r, BACKOFF[Math.min(attempt++, BACKOFF.length - 1)]));
      }
    })();
    return () => { abort.abort(); clearTimeout(flush); };
  }, [source, sessionId]);

  const loadOlder = useCallback(async () => {
    if (!sessionId || !source.processHistory || oldest.current == null) return;
    const page = await source.processHistory(sessionId, oldest.current);
    oldest.current = page.events[0]?.event_id ?? oldest.current;
    setHasOlder(page.hasMore);
    setEvents((cur) => page.events.concat(cur));
  }, [source, sessionId]);

  return { events, health, hasOlder, loadOlder };
}
