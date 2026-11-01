'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const ide = process.env.JAEGER_REPO || path.resolve(__dirname, '..');
const { Conversation } = require(path.join(ide, 'conversation'));

test('retry reuses the previous user index, clears errors and never sends text', async () => {
  const events = [];
  const gateway = {
    url: 'http://127.0.0.1:1234',
    async retry() { return { request_id: 'retry-1', start_event_id: 3, status: 'running' }; },
    async session() { return { session_id: 's', status: 'running', messages: [{ role: 'user', content: 'hello' }] }; },
    async receipt() { return { status: 'running' }; },
    async *events() { yield { event_id: 4, event: 'search.count', data: { request_id: 'retry-1', searches: 1, completed: 1, failed: 0 } }; yield { event_id: 5, event: 'sources', data: { request_id: 'retry-1', sources: [{ kind: 'url', location: 'https://example.org' }] } }; yield { event_id: 6, event: 'follow_ups', data: { request_id: 'retry-1', follow_ups: ['Next?'] } }; },
    async send() { throw new Error('must not resend'); },
  };
  const client = new Conversation(gateway, s => events.push(s), async () => {});
  client.state.connected = true;
  client.state.session = { session_id: 's', messages: [{ role: 'user', content: 'hello' }] };
  client.state.error = 'old error';
  assert.equal(await client.retry(), true);
  assert.equal(client.state.error, '');
  assert.equal(client.workBySession.s[0].userIndex, 0);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(client.state.timeline.some(row => row.kind === 'sources'));
  assert.ok(client.state.timeline.some(row => row.kind === 'search-count'));
  assert.equal(client.state.suggestions[0].prompt, 'Next?');
  client.dispose();
});

test('uncertain delivery never invokes retry endpoint', async () => {
  let called = 0;
  const client = new Conversation({ url: 'http://127.0.0.1:1234', retry: async () => { called++; } }, () => {}, async () => {});
  client.state.connected = true;
  client.state.session = { session_id: 's', messages: [{ role: 'user', content: 'hello' }] };
  client.pending.s = { requestId: 'possibly-accepted' };
  assert.equal(await client.retry(), false);
  assert.equal(called, 0);
  client.dispose();
});
