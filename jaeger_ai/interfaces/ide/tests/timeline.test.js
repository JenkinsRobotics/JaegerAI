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
  assert.deepEqual(r.state().rows.map(row => row.kind), ['answer', 'tool', 'answer']);
  assert.deepEqual(r.state().rows.filter(row => row.kind === 'answer').map(row => row.text), ['AB', 'C']);
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
