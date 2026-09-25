'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Gateway, GatewayError } = require('../gateway');
const { Conversation } = require('../conversation');

const readMedia = name => fs.readFileSync(path.join(__dirname, '..', 'media', name), 'utf8');

test('Gateway client targets the Gateway-owned queue routes', async () => {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, init) => {
    calls.push({ url: String(url), init: { ...init, body: init.body ? JSON.parse(init.body) : undefined } });
    return { ok: true, json: async () => ({ items: [], ok: true }) };
  };
  try {
    const gateway = new Gateway('http://127.0.0.1:1234');
    await gateway.queue('session one');
    await gateway.queueAdd('session one', { text: 'next' });
    await gateway.queueReorder('session one', ['a', 'b']);
    await gateway.queueUpdate('session one', 'a', { text: 'changed' });
    await gateway.queueDelete('session one', 'a');

    assert.deepEqual(calls.map(call => [call.url, call.init.method]), [
      ['http://127.0.0.1:1234/v1/sessions/session%20one/queue', 'GET'],
      ['http://127.0.0.1:1234/v1/sessions/session%20one/queue', 'POST'],
      ['http://127.0.0.1:1234/v1/sessions/session%20one/queue/reorder', 'POST'],
      ['http://127.0.0.1:1234/v1/sessions/session%20one/queue/a', 'PATCH'],
      ['http://127.0.0.1:1234/v1/sessions/session%20one/queue/a', 'DELETE'],
    ]);
    assert.deepEqual(calls[1].init.body, { text: 'next' });
    assert.deepEqual(calls[2].init.body, { order: ['a', 'b'] });
    assert.deepEqual(calls[3].init.body, { text: 'changed' });
  } finally {
    global.fetch = originalFetch;
  }
});

function fixture(queueRows = []) {
  const gateway = {
    url: 'http://127.0.0.1:1234',
    row: { session_id: 'one', title: 'One', status: 'idle', messages: [] },
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: [this.row] }; },
    async session() { return structuredClone(this.row); },
    async approvals() { return { approvals: [] }; },
    async receipt() { return { status: 'running' }; },
    async queue() { return { items: structuredClone(queueRows) }; },
    async queueAdd(sid, body) { this.queued = { sid, body }; return { status: 'queued', queued: true }; },
    async queueUpdate(sid, id, patch) { this.updated = { sid, id, patch }; return { item: {} }; },
    async queueDelete(sid, id) { this.deleted = { sid, id }; return { deleted: true }; },
    async queueReorder(sid, order) { this.reordered = { sid, order }; return { items: [] }; },
    async steer(sid, rid, text) { this.steered = { sid, rid, text }; return { steered: true, queued: true }; },
    async *events() {},
  };
  const client = new Conversation(gateway, () => {}, async () => {});
  return { gateway, client };
}

test('conversation queues follow-up work in the Gateway, not locally', async () => {
  const row = { request_id: 'q1', input_text: 'next work', status: 'queued', queue_position: 1 };
  const { gateway, client } = fixture([row]);
  await client.refresh('one');
  await client.queue('next work');
  assert.equal(gateway.queued.body.text, 'next work');
  assert.deepEqual(client.state.queue, [row]);
  assert.equal(client.state.status, 'Queued · waiting for the current turn');
  assert.equal('steers' in client, false);
  client.dispose();
});

test('a queued item that starts immediately is followed by this client', async () => {
  const { gateway, client } = fixture([]);
  await client.refresh('one');
  let sentBody;
  gateway.queueAdd = async (sid, body) => {
    sentBody = body;
    return { status: 'running', queued: false, request_id: body.request_id, start_event_id: 7 };
  };
  let observed;
  client.observe = async (sid, rid, cursor) => { observed = { sid, rid, cursor }; };
  await client.queue('start now');
  assert.equal(client.pending.one.requestId, sentBody.request_id);
  assert.equal(client.pending.one.startCursor, 6);
  assert.equal(client.state.busy, true);
  assert.deepEqual(observed, { sid: 'one', rid: sentBody.request_id, cursor: 6 });
  client.dispose();
});

test('steering does not create a hidden queue when the Gateway honestly returns 409', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  client.pending.one = { requestId: 'rid', startCursor: 0 };
  client.state.busy = true;
  gateway.steer = async () => { throw new GatewayError('no active ReAct agent', 409); };
  assert.equal(await client.steer('queue this'), false);
  assert.equal(client.state.status, 'No live agent to steer · use Queue next');
  assert.equal('steers' in client, false);
  client.dispose();
});

test('conversation edits, reorders, and deletes queue items through the Gateway', async () => {
  const { gateway, client } = fixture([{ request_id: 'q1', input_text: 'x', status: 'queued' }]);
  await client.refresh('one');
  await client.queueUpdate('q1', { text: 'edited' });
  assert.deepEqual(gateway.updated, { sid: 'one', id: 'q1', patch: { text: 'edited' } });

  await client.queueReorder(['q1']);
  assert.deepEqual(gateway.reordered, { sid: 'one', order: ['q1'] });

  gateway.queue = async () => ({ items: [] });
  await client.queueDelete('q1');
  assert.deepEqual(gateway.deleted, { sid: 'one', id: 'q1' });
  assert.deepEqual(client.state.queue, []);
  client.dispose();
});

test('the webview has explicit queue controls and no client-owned steering queue', () => {
  const html = readMedia('index.html');
  const js = readMedia('view.js');
  const css = readMedia('view.css');
  assert.match(html, /id="queue"/);
  assert.match(html, /id="queue-next"/);
  assert.match(js, /renderQueue\(\)/);
  assert.match(js, /queue-next/);
  assert.match(css, /#queue\{/);
  assert.doesNotMatch(js, /state\.steers/);
  assert.doesNotMatch(js, /steerNote/);
});
