'use strict';

/*
 * Stable-key/referential-reuse strategy adapted from Kilo Code v7.7.9:
 * packages/kilo-vscode/webview-ui/src/context/transcript-rows.ts
 * commit d52877ea1c0a02284a4a87d2da0082d2f6dbefb7 (MIT).
 * Gateway event shapes and reducer rules are Jaeger-specific modifications.
 */

(function expose(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.JaegerTimeline = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  const STREAM_EVENTS = new Set(['turn.delta', 'turn.reasoning']);
  const TERMINAL_EVENTS = new Set(['turn.finish', 'turn.failed', 'turn.cancelled', 'turn.unknown', 'turn.reconciled']);

  const createTimelineState = () => ({ cursor: 0, seen: new Set(), rows: [] });
  const requestId = event => String(event.data?.request_id || 'unknown');
  const eventId = event => {
    const value = Number(event.event_id);
    return Number.isFinite(value) && value > 0 ? value : 0;
  };
  const replaceAt = (rows, index, row) => {
    const next = rows.slice(); next[index] = row; return next;
  };

  function appendStream(rows, event) {
    const kind = event.event === 'turn.delta' ? 'answer' : 'reasoning';
    const text = String(event.event === 'turn.delta' ? event.data?.delta || '' : event.data?.text || '');
    if (!text) return rows;
    const rid = requestId(event), last = rows.at(-1);
    if (last?.kind === kind && last.requestId === rid && last.live) {
      return replaceAt(rows, rows.length - 1, { ...last, text: last.text + text });
    }
    return [...rows, { key: `${kind}:${rid}:${eventId(event) || rows.length}`, kind,
      requestId: rid, text, live: true }];
  }

  function applyTool(rows, event) {
    const rid = requestId(event);
    const identity = event.data?.activity_id || event.data?.call_id || eventId(event);
    const key = `tool:${rid}:${identity}`;
    const index = rows.findIndex(row => row.key === key);
    const old = index >= 0 ? rows[index] : null;
    const phase = event.event.endsWith('started') ? 'running'
      : event.event.endsWith('failed') ? 'failed' : 'completed';
    const row = { key, kind: 'tool', requestId: rid,
      name: String(event.data?.tool || old?.name || 'tool'),
      detail: String(event.data?.text || event.data?.status || old?.detail || ''),
      phase, ok: phase === 'failed' ? false : event.data?.ok, live: phase === 'running' };
    return index >= 0 ? replaceAt(rows, index, row) : [...rows, row];
  }

  function settle(rows, rid) {
    let changed = false;
    const next = rows.map(row => {
      if (row.requestId !== rid || !row.live) return row;
      changed = true; return { ...row, live: false };
    });
    return changed ? next : rows;
  }

  function applyOne(rows, event) {
    if (STREAM_EVENTS.has(event.event)) return appendStream(rows, event);
    if (['tool.started', 'tool.completed', 'tool.failed'].includes(event.event)) return applyTool(rows, event);
    if (TERMINAL_EVENTS.has(event.event)) {
      const rid = requestId(event), settled = settle(rows, rid);
      return [...settled, { key: `terminal:${rid}:${eventId(event) || settled.length}`,
        kind: 'terminal', requestId: rid, status: event.event.slice(5), live: false }];
    }
    return [...rows, { key: `control:${requestId(event)}:${eventId(event) || rows.length}`,
      kind: 'control', requestId: requestId(event), name: event.event,
      detail: String(event.data?.text || event.data?.status || ''), live: false }];
  }

  function applyEvents(state, events) {
    let rows = state.rows, cursor = state.cursor, seen = state.seen, changed = false;
    for (const event of events) {
      const id = eventId(event);
      if (id && (seen.has(id) || id <= cursor)) continue;
      const next = applyOne(rows, event);
      if (next !== rows) { rows = next; changed = true; }
      if (id) {
        if (seen === state.seen) seen = new Set(state.seen);
        seen.add(id); cursor = Math.max(cursor, id);
      }
    }
    return changed || cursor !== state.cursor ? { cursor, seen, rows } : state;
  }

  return { applyEvents, createTimelineState, isStreamEvent: event => STREAM_EVENTS.has(event.event) };
});
