'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { Conversation } = require('../conversation');

test('admitted turn starts stream while session refresh is stalled', async () => {
  let streamStarted = false;
  let sessionReads = 0;
  const gateway = {
    url: 'http://127.0.0.1:1234',
    async send() { return { status: 'running', start_event_id: 4 }; },
    async session() { sessionReads++; return new Promise(() => {}); },
    async receipt() { return { status: 'running' }; },
    async *events(_sid, cursor) { assert.equal(cursor, 3); streamStarted = true; yield { event_id: 4, event: 'turn.delta', data: { request_id: this.requestId, delta: 'Hi' } }; await new Promise(() => {}); },
  };
  const client = new Conversation(gateway, () => {}, async () => {});
  client.state.connected = true;
  client.state.session = { session_id: 'one', messages: [] };
  try {
    await client.send('hello');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(streamStarted, true);
    assert.equal(sessionReads, 0);
  } finally { client.dispose(); }
});
