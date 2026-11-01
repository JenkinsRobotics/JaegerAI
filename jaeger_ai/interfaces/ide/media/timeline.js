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
    // Text preceding a tool call is commentary, not the final answer.
    // Preserve its chronological position in the turn's work history.
    if (event.event === 'tool.started') rows = rows.map(row =>
      row.requestId === rid && row.kind === 'answer' ? { ...row, kind: 'progress', live: false } : row);
    const identity = event.data?.activity_id || event.data?.call_id || eventId(event);
    const key = `tool:${rid}:${identity}`;
    const index = rows.findIndex(row => row.key === key);
    const old = index >= 0 ? rows[index] : null;
    const phase = event.event.endsWith('started') ? 'running'
      : event.event.endsWith('failed') ? 'failed' : 'completed';
    const row = { key, kind: 'tool', requestId: rid,
      name: String(event.data?.tool || old?.name || 'tool'),
      detail: String(event.data?.text || event.data?.status || old?.detail || ''),
      input: String(event.data?.input || old?.input || ''), output: String(event.data?.output || old?.output || ''),
      phase, ok: phase === 'failed' ? false : event.data?.ok, live: phase === 'running' };
    return index >= 0 ? replaceAt(rows, index, row) : [...rows, row];
  }

  const PLAN_STATUSES = new Set(['pending', 'in_progress', 'completed']);

  // The latest plan wins: the model resends the whole plan each time it changes,
  // so one row per request is replaced in place and keeps its chronological spot.
  function applyPlan(rows, event) {
    const rid = requestId(event), key = `plan:${rid}`;
    const plan = (Array.isArray(event.data?.plan) ? event.data.plan : [])
      .map(item => ({ step: String(item?.step || ''), status: PLAN_STATUSES.has(item?.status) ? item.status : 'pending' }))
      .filter(item => item.step);
    if (!plan.length) return rows;
    const row = { key, kind: 'plan', requestId: rid, plan,
      explanation: String(event.data?.explanation || ''), live: false };
    const index = rows.findIndex(existing => existing.key === key);
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
    if (event.event === 'turn.progress' || event.event === 'turn.checkpoint') {
      const rid = requestId(event), kind = event.event === 'turn.checkpoint' ? 'checkpoint' : 'progress';
      const candidates = rows.filter(row => row.requestId === rid && row.kind === 'answer');
      const next = rows.map(row => candidates.includes(row) ? { ...row, kind, live: false } : row);
      if (kind === 'checkpoint' && !candidates.length && event.data?.text) {
        next.push({ key: `checkpoint:${rid}:${eventId(event)}`, kind, requestId: rid, text: event.data.text, live: false });
      }
      return next;
    }
    if (event.event === 'turn.plan') return applyPlan(rows, event);
    if (event.event === 'search.count') {
      const rid = requestId(event), count = event.data?.searches;
      if (!Number.isSafeInteger(count) || count < 1) return rows;
      const completed = event.data?.completed, failed = event.data?.failed;
      if (![completed, failed].every(n => Number.isSafeInteger(n) && n >= 0 && n <= count)) return rows;
      const key = `search-count:${rid}`;
      const row = { key, kind: 'search-count', requestId: rid, searches: count, completed, failed, live: false };
      const index = rows.findIndex(item => item.key === key);
      return index >= 0 ? replaceAt(rows, index, row) : [...rows, row];
    }
    if (event.event === 'sources') {
      const sources = (Array.isArray(event.data?.sources) ? event.data.sources : [])
        .filter(item => ['url', 'file'].includes(item?.kind) && typeof item?.location === 'string')
        .slice(0, 20);
      return sources.length ? [...rows, { key: `sources:${requestId(event)}:${eventId(event)}`,
        kind: 'sources', requestId: requestId(event), sources, live: false }] : rows;
    }
    if (STREAM_EVENTS.has(event.event)) return appendStream(rows, event);
    if (['tool.started', 'tool.completed', 'tool.failed'].includes(event.event)) return applyTool(rows, event);
    if (TERMINAL_EVENTS.has(event.event)) {
      const rid = requestId(event), settled = settle(reconcileAnswer(rows, event), rid);
      return [...settled, { key: `terminal:${rid}:${eventId(event) || settled.length}`,
        kind: 'terminal', requestId: rid, status: event.event.slice(5), live: false }];
    }
    return [...rows, { key: `control:${requestId(event)}:${eventId(event) || rows.length}`,
      kind: 'control', requestId: requestId(event), name: event.event,
      detail: String(event.data?.text || event.data?.status || ''), live: false }];
  }

  // The saved final text is the answer. Replace the streamed body with it so it
  // is shown once: identical keeps the rows, a prefix or a different stream is
  // replaced in place, and an empty stream gains the answer row.
  function reconcileAnswer(rows, event) {
    const output = event.event === 'turn.finish' && typeof event.data?.output === 'string' ? event.data.output : '';
    if (!output) return rows;
    const rid = requestId(event);
    const indexes = rows.map((row, i) => (row.requestId === rid && row.kind === 'answer' ? i : -1)).filter(i => i >= 0);
    if (indexes.map(i => rows[i].text).join('') === output) return rows;
    if (!indexes.length) return [...rows, { key: `answer:${rid}:final`, kind: 'answer', requestId: rid, text: output, live: false }];
    const [first, ...rest] = indexes;
    const next = rows.filter((_, i) => !rest.includes(i));
    const at = next.indexOf(rows[first]);
    return replaceAt(next, at, { ...rows[first], text: output });
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
