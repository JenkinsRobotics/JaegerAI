'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { observeNativeTurn, renderNativeOutcome } = require('../native-turn');

function fixture() {
  const markdown = [], progress = [], approvals = [], cursors = [], results = [];
  const done = { status: 'completed', result: { output: 'Hello 🌱' } };
  const controller = new AbortController();
  const event = (id, name, data = {}) => ({ event_id: id, event: name, session_id: 's', data: { request_id: 'r', ...data } });
  const gateway = { receipt: async () => done, async *events(sid, cursor) { cursors.push(cursor); },
    ideResult: async (...args) => results.push(args) };
  const stream = { markdown: t => markdown.push(t), progress: t => progress.push(t) };
  const run = () => observeNativeTurn({ gateway, sessionId: 's', requestId: 'r', admitted: { status: 'running', start_event_id: 1 },
    signal: controller.signal, stream, ideHandler: async () => ({ file: 'a.py' }), onApproval: d => approvals.push(d) });
  return { gateway, stream, controller, event, done, run, markdown, progress, approvals, cursors, results };
}

test('native stream delivers deltas before completion, ignores foreign/replayed events, and does not repeat final text', async () => {
  const f = fixture();
  f.gateway.events = async function* () {
    yield f.event(1, 'turn.delta', { request_id: 'other', delta: 'wrong' });
    yield { ...f.event(2, 'turn.delta', { delta: 'wrong' }), session_id: 'other' };
    yield f.event(3, 'turn.delta', { delta: 'Hello ' });
    assert.deepEqual(f.markdown, ['Hello '], 'first delta must render before the next event');
    yield f.event(3, 'turn.delta', { delta: 'duplicate' });
    yield f.event(4, 'turn.delta', { delta: '🌱' });
    yield f.event(5, 'turn.finish');
  };
  const result = await f.run();
  renderNativeOutcome(f.stream, result, false);
  assert.deepEqual(f.markdown, ['Hello ', '🌱']);
});

test('native observer reconnects from cursor without a new admission and exposes approvals and editor requests', async () => {
  const f = fixture(); let reads = 0;
  f.gateway.receipt = async () => ++reads === 1 ? { status: 'running' } : f.done;
  f.gateway.events = async function* (sid, cursor) {
    f.cursors.push(cursor);
    if (cursor === 0) {
      yield f.event(1, 'turn.delta', { delta: 'Hello ' });
      throw new Error('connection reset');
    }
    yield f.event(1, 'turn.delta', { delta: 'replay' });
    yield f.event(2, 'approval.request', { approval_id: 'a' });
    yield f.event(3, 'approval.resolved');
    yield f.event(4, 'ide.request', { ide_request_id: 'i', kind: 'context' });
    yield f.event(5, 'turn.delta', { delta: '🌱' });
    yield f.event(6, 'turn.finish');
  };
  const result = await f.run(); renderNativeOutcome(f.stream, result, false);
  assert.deepEqual(f.cursors, [0, 1]);
  assert.equal(f.approvals.length, 1);
  assert.match(f.progress.join('\n'), /Reconnecting/);
  assert.match(f.progress.join('\n'), /Approval resolved/);
  assert.deepEqual(f.results, [['s', 'i', { ok: true, result: { file: 'a.py' } }]]);
  assert.deepEqual(f.markdown, ['Hello ', '🌱']);
});

test('native observer bounds retries and reports an unconfirmed execution outcome after EOF', async () => {
  const f = fixture(); f.gateway.receipt = async () => ({ status: 'running' });
  const result = await f.run(); renderNativeOutcome(f.stream, result, false);
  assert.deepEqual(f.cursors, [0, 0, 0]);
  assert.match(f.markdown.join(''), /Connection interrupted.*not confirmed/s);
  assert.doesNotMatch(f.markdown.join(''), /completed/);
});

test('cancellation stops observation, but a running receipt is not claimed cancelled', async () => {
  const f = fixture(); f.gateway.receipt = async () => ({ status: 'running' });
  f.gateway.events = async function* () { f.controller.abort(); throw new Error('aborted'); };
  const result = await f.run(); renderNativeOutcome(f.stream, result, true);
  assert.match(f.markdown.join(''), /Cancellation requested.*not confirmed/s);
});

test('confirmed cancellation and failed/unknown receipts remain distinct from completion', async () => {
  for (const status of ['cancelled', 'failed', 'execution_unknown']) {
    const f = fixture(); f.gateway.receipt = async () => ({ status, result: { error: 'detail' } });
    const result = await f.run(); renderNativeOutcome(f.stream, result, true);
    assert.match(f.markdown.join(''), new RegExp(`request ${status}`));
    assert.doesNotMatch(f.markdown.join(''), /completed/);
  }
});

test('receipt failure reports uncertainty, and a corrected final answer is explicitly labelled', async () => {
  const f = fixture(); f.gateway.receipt = async () => { throw new Error('offline'); };
  renderNativeOutcome(f.stream, await f.run(), false);
  assert.match(f.markdown.join(''), /not confirmed/);
  const g = fixture();
  renderNativeOutcome(g.stream, { receipt: g.done, text: 'provisional' }, false);
  assert.deepEqual(g.markdown, ['\n\n**Final confirmed answer**\n\nHello 🌱']);
});


test('already-terminal admission still loads the authoritative receipt', async () => {
  const f = fixture();
  f.gateway.events = async function* () { assert.fail('terminal admission must not start observation'); };
  const result = await observeNativeTurn({ gateway: f.gateway, sessionId: 's', requestId: 'r', admitted: { status: 'completed' },
    signal: f.controller.signal, stream: f.stream });
  renderNativeOutcome(f.stream, result, false);
  assert.deepEqual(f.markdown, ['Hello 🌱']);
});
