'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { createFrameQueue } = require('../media/frame-queue');
const { applyEvents, createTimelineState, isStreamEvent } = require('../media/timeline');
const { KeyedRenderer } = require('../media/keyed-renderer');

class Clock {
  constructor() { this.frames = new Map(); this.timers = new Map(); this.next = 1; }
  requestFrame = fn => { const id = this.next++; this.frames.set(id, fn); return id; };
  cancelFrame = id => this.frames.delete(id);
  setTimer = fn => { const id = this.next++; this.timers.set(id, fn); return id; };
  clearTimer = id => this.timers.delete(id);
  hidden = () => false;
  frame() { const work = [...this.frames.values()]; this.frames.clear(); for (const fn of work) fn(); }
}
class Node { constructor() { this.dataset = {}; this.disclosure = { open: false }; } }
class Host {
  constructor() { this.children = []; this.scrollTop = 0; this.scrollHeight = 100; this.clientHeight = 100; }
  insertBefore(node, ref) {
    const old = this.children.indexOf(node); if (old >= 0) this.children.splice(old, 1);
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at >= 0) this.children.splice(at, 0, node); else this.children.push(node);
    this.scrollHeight = 100 + this.children.length * 40;
  }
  removeChild(node) { this.children.splice(this.children.indexOf(node), 1); }
}
const delta = (id, text) => ({ event_id: id, event: 'turn.delta', data: { request_id: 'r', delta: text } });

function rig() {
  const clock = new Clock(), host = new Host();
  let state = createTimelineState(), creates = 0, updates = 0;
  const renderer = new KeyedRenderer(host, () => { creates++; return new Node(); },
    (node, row) => { updates++; node.row = row; });
  const apply = events => {
    const next = applyEvents(state, events);
    if (next !== state) { state = next; renderer.reconcile(state.rows); }
  };
  const queue = createFrameQueue(apply, isStreamEvent, clock);
  return { clock, host, renderer, queue, state: () => state, metrics: () => ({ creates, updates }) };
}

test('500 deltas reconcile once per animation frame', () => {
  const r = rig();
  for (let id = 1; id <= 500; id++) r.queue.push(delta(id, 'x'));
  assert.equal(r.renderer.reconciliations, 0); r.clock.frame();
  assert.equal(r.renderer.reconciliations, 1);
  assert.equal(r.state().rows[0].text.length, 500);
  assert.deepEqual(r.metrics(), { creates: 1, updates: 1 });
});

test('control events flush preceding text and preserve text/tool/text order', () => {
  const r = rig();
  r.queue.push(delta(1, 'A')); r.queue.push(delta(2, 'B'));
  r.queue.push({ event_id: 3, event: 'tool.started', data: { request_id: 'r', activity_id: 'c', tool: 'read_file' } });
  r.queue.push(delta(4, 'C'));
  r.queue.push({ event_id: 5, event: 'tool.completed', data: { request_id: 'r', activity_id: 'c', tool: 'read_file', ok: true } });
  assert.deepEqual(r.state().rows.map(row => row.kind), ['progress', 'tool', 'answer']);
  assert.equal(r.state().rows[0].text, 'AB');
  assert.deepEqual(r.state().rows.filter(row => row.kind === 'answer').map(row => row.text), ['C']);
});

test('keyed rows preserve settled node and disclosure identity', () => {
  const r = rig();
  r.queue.push(delta(1, 'before'));
  r.queue.push({ event_id: 2, event: 'tool.started', data: { request_id: 'r', activity_id: 'c', tool: 'terminal' } });
  const answer = r.host.children[0], tool = r.host.children[1], disclosure = tool.disclosure;
  disclosure.open = true;
  r.queue.push({ event_id: 3, event: 'tool.completed', data: { request_id: 'r', activity_id: 'c', tool: 'terminal', ok: true } });
  r.queue.push(delta(4, 'after')); r.clock.frame();
  assert.equal(r.host.children[0], answer); assert.equal(r.host.children[1], tool);
  assert.equal(tool.disclosure, disclosure); assert.equal(disclosure.open, true);
});

test('manual scroll and stale event rejection survive streaming', () => {
  const r = rig(); r.queue.push(delta(1, 'A')); r.clock.frame();
  r.host.scrollHeight = 600; r.host.scrollTop = 120;
  r.queue.push(delta(2, 'B')); r.clock.frame(); assert.equal(r.host.scrollTop, 120);
  const reconciliations = r.renderer.reconciliations;
  r.queue.push(delta(2, 'duplicate')); r.queue.push(delta(1, 'stale')); r.clock.frame();
  assert.equal(r.renderer.reconciliations, reconciliations);
  assert.equal(r.state().rows[0].text, 'AB');
});

test('explicit checkpoint stays in order and is never part of final answer', () => {
  const state = applyEvents(createTimelineState(), [
    { event_id: 1, event: 'turn.delta', data: { request_id: 'r', delta: 'Inspected.' } },
    { event_id: 2, event: 'turn.checkpoint', data: { request_id: 'r', text: 'Inspected.' } },
    { event_id: 3, event: 'turn.delta', data: { request_id: 'r', delta: 'Implemented and verified.' } },
    { event_id: 4, event: 'turn.finish', data: { request_id: 'r' } },
  ]);
  assert.deepEqual(state.rows.map(r => r.kind), ['checkpoint', 'answer', 'terminal']);
  assert.equal(state.rows[0].text, 'Inspected.');
  assert.equal(state.rows[1].text, 'Implemented and verified.');
});

const planEvent = (id, plan, extra = {}) => ({
  event_id: id, event: 'turn.plan', data: { request_id: 'r', plan, ...extra },
});

test('turn.plan becomes one plan row per request and the latest plan replaces it in place', () => {
  let state = createTimelineState();
  state = applyEvents(state, [
    delta(1, 'looking'),
    planEvent(2, [{ step: 'read', status: 'in_progress' }, { step: 'fix', status: 'pending' }], { explanation: 'start' }),
    { event_id: 3, event: 'tool.started', data: { request_id: 'r', activity_id: 'a', tool: 'read_file' } },
    planEvent(4, [{ step: 'read', status: 'completed' }, { step: 'fix', status: 'in_progress' }]),
  ]);
  const plans = state.rows.filter(row => row.kind === 'plan');
  assert.equal(plans.length, 1);
  assert.deepEqual(plans[0].plan.map(item => item.status), ['completed', 'in_progress']);
  assert.equal(plans[0].explanation, '');
  // The plan keeps the chronological position of its first appearance.
  assert.deepEqual(state.rows.map(row => row.kind), ['progress', 'plan', 'tool']);
});

test('plan rows for different requests stay separate', () => {
  const state = applyEvents(createTimelineState(), [
    planEvent(1, [{ step: 'a', status: 'pending' }]),
    { event_id: 2, event: 'turn.plan', data: { request_id: 'other', plan: [{ step: 'b', status: 'pending' }] } },
  ]);
  assert.deepEqual(state.rows.map(row => row.key), ['plan:r', 'plan:other']);
});

test('malformed plans are cleaned or ignored, never rendered raw', () => {
  const state = applyEvents(createTimelineState(), [
    planEvent(1, [{ step: 'ok', status: 'weird' }, { step: '', status: 'pending' }, null, { step: 'kept' }]),
    planEvent(2, 'not a list'),
    planEvent(3, []),
  ]);
  const [row] = state.rows;
  assert.deepEqual(row.plan, [{ step: 'ok', status: 'pending' }, { step: 'kept', status: 'pending' }]);
  assert.equal(state.rows.length, 1);
});

test('replayed plan events are applied once', () => {
  const event = planEvent(5, [{ step: 'a', status: 'pending' }]);
  const once = applyEvents(createTimelineState(), [event]);
  assert.equal(applyEvents(once, [event]), once);
});

test('a tool row keeps its command and output across started and completed events', () => {
  const state = applyEvents(createTimelineState(), [
    { event_id: 1, event: 'tool.started', data: { request_id: 'r', activity_id: 'a', tool: 'exec_command', input: 'ls -la' } },
    { event_id: 2, event: 'tool.completed', data: { request_id: 'r', activity_id: 'a', tool: 'exec_command', output: 'total 8' } },
  ]);
  assert.equal(state.rows[0].input, 'ls -la');
  assert.equal(state.rows[0].output, 'total 8');
});
