'use strict';
// The saved final answer replaces what was streamed: shown once, never dropped.
// Four cases, each for @jaeger (native-turn.js) and the panel (media/timeline.js).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { observeNativeTurn, renderNativeOutcome } = require('../native-turn');
const { applyEvents, createTimelineState } = require('../media/timeline');

const LONG = `## Summary\n\nTidepool Notes is a local-first notes library.\n\n| Script | Command |\n|---|---|\n| build | tsc |\n`;
const cases = {
  'prefix match': { deltas: [LONG.slice(0, 60), LONG.slice(60, 120)], final: LONG },
  'preamble that differs': { deltas: ["I'll read the workspace files first.", '@tool', LONG.slice(0, 80), LONG.slice(80)], final: LONG },
  'identical stream': { deltas: [LONG.slice(0, 50), LONG.slice(50)], final: LONG },
  'empty stream': { deltas: [], final: LONG },
};

function events(deltas, final, rid = 'r1') {
  let id = 1;
  const out = deltas.map(d => (d === '@tool'
    ? { event_id: ++id, event: 'tool.started', data: { request_id: rid, tool: 'read_file', activity_id: 't1' } }
    : { event_id: ++id, event: 'turn.delta', data: { request_id: rid, delta: d } }));
  out.push({ event_id: ++id, event: 'turn.finish', data: { request_id: rid, status: 'completed', output: final } });
  return out;
}

async function nativeRender({ deltas, final }) {
  const md = [], progress = [];
  const stream = { markdown: t => md.push(t), progress: t => progress.push(t) };
  const gateway = { events: async function* () { yield* events(deltas, final); }, receipt: async () => ({ status: 'completed', result: { output: final } }) };
  const outcome = await observeNativeTurn({ gateway, sessionId: 's', requestId: 'r1', admitted: { start_event_id: 1, status: 'running' }, signal: new AbortController().signal, stream });
  renderNativeOutcome(stream, outcome, false);
  return { shown: md.join(''), progress };
}

for (const [name, c] of Object.entries(cases)) {
  test(`@jaeger ${name}: the final answer appears exactly once`, async () => {
    const { shown, progress } = await nativeRender(c);
    assert.equal(shown, c.final, 'native chat shows the confirmed answer once and nothing else');
    assert.ok(!shown.includes('Final confirmed answer'));
    if (name === 'preamble that differs') assert.ok(progress.includes("I'll read the workspace files first."), 'preamble kept as progress, not dropped');
  });

  test(`panel ${name}: the answer row body is replaced by the final text`, () => {
    const state = applyEvents(createTimelineState(), events(c.deltas, c.final));
    const answers = state.rows.filter(r => r.kind === 'answer');
    assert.equal(answers.length, 1, 'one answer row');
    assert.equal(answers[0].text, c.final);
    if (name === 'preamble that differs') assert.ok(state.rows.some(r => r.kind === 'progress' && r.text.startsWith("I'll read")));
  });
}

test('panel: an identical stream keeps the same answer row object (no re-render)', () => {
  const { deltas, final } = cases['identical stream'];
  const all = events(deltas, final);
  const before = applyEvents(createTimelineState(), all.slice(0, -1));
  const after = applyEvents(before, all.slice(-1));
  assert.equal(after.rows.find(r => r.kind === 'answer').text, before.rows.find(r => r.kind === 'answer').text);
});

test('@jaeger: a server-corrected answer (stream not a prefix) is still shown once, after the streamed text', async () => {
  const final = LONG.replace('local-first', 'offline-first');
  const { shown } = await nativeRender({ deltas: [LONG], final });
  assert.equal(shown.split(final).length - 1, 1);
  assert.ok(!shown.includes('Final confirmed answer'));
});

test('@jaeger: a short answer with no final text is not dropped', async () => {
  const md = [];
  const stream = { markdown: t => md.push(t), progress() {} };
  const gateway = { events: async function* () { yield { event_id: 2, event: 'turn.delta', data: { request_id: 'r1', delta: 'Done.' } }; yield { event_id: 3, event: 'turn.finish', data: { request_id: 'r1' } }; }, receipt: async () => ({ status: 'completed', result: {} }) };
  renderNativeOutcome(stream, await observeNativeTurn({ gateway, sessionId: 's', requestId: 'r1', admitted: { start_event_id: 1, status: 'running' }, signal: new AbortController().signal, stream }), false);
  assert.equal(md.join(''), 'Done.');
});
