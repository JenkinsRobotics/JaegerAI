'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Gateway, GatewayError } = require('../gateway');
const { Conversation } = require('../conversation');

const waitFor = async predicate => {
  const end = Date.now() + 5000;
  while (!predicate()) {
    if (Date.now() > end) throw new Error('Timed out');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
};

test('Gateway client targets the request-scoped steering route', async () => {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return { ok: true, json: async () => ({ request_id: 'rid', steered: true, queued: true }) };
  };
  try {
    const gateway = new Gateway('http://127.0.0.1:1234');
    const result = await gateway.steer('session one', 'rid', 'use metric units');
    assert.equal(result.steered, true);
    assert.equal(calls[0].url, 'http://127.0.0.1:1234/v1/sessions/session%20one/requests/rid/steer');
    assert.deepEqual(JSON.parse(calls[0].init.body), { text: 'use metric units' });
  } finally {
    global.fetch = originalFetch;
  }
});

function fixture() {
  const gateway = {
    url: 'http://127.0.0.1:1234',
    row: { session_id: 'one', title: 'One', status: 'idle', messages: [] },
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: [this.row] }; },
    async session() { return structuredClone(this.row); },
    async approvals() { return { approvals: [] }; },
    async receipt() { return { status: 'running' }; },
    async send(sid, body) { this.sent = body; return { start_event_id: 2, status: 'running' }; },
    async steer(sid, rid, text) { this.steered = { sid, rid, text }; return { steered: true, queued: true }; },
    async *events() {},
  };
  const client = new Conversation(gateway, () => {}, async () => {});
  return { gateway, client };
}

test('conversation uses Gateway live steering and does not create a follow-up queue entry', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.send('hello');
  assert.equal(await client.steer('use metric units'), true);
  assert.deepEqual(gateway.steered, {
    sid: 'one', rid: gateway.sent.request_id, text: 'use metric units',
  });
  assert.equal('steers' in client, false);
  assert.equal(client.state.status, 'Steering accepted · next model step');
  client.dispose();
});

test('a no-ReAct-agent 409 is honest and never creates a client queue', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.send('hello');
  gateway.steer = async () => { throw new GatewayError('no active ReAct agent', 409); };
  assert.equal(await client.steer('queue this'), false);
  assert.equal('steers' in client, false);
  assert.equal(client.state.status, 'No live agent to steer · use Queue next');
  client.dispose();
});

test('conversation propagates transport errors instead of silently queueing', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.send('hello');
  gateway.steer = async () => { throw new GatewayError('connection failed', 0); };
  await assert.rejects(() => client.steer('queue this'), /connection failed/);
  assert.equal('steers' in client, false);
  assert.deepEqual(client.state.queue, []);
  client.dispose();
});
