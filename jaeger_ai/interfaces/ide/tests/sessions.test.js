'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Conversation } = require('../conversation');

const readMedia = name => fs.readFileSync(path.join(__dirname, '..', 'media', name), 'utf8');

function fixture() {
  const rows = [
    { session_id: 'one', title: 'One', status: 'idle', messages: [] },
    { session_id: 'two', title: 'Two', status: 'idle', messages: [] },
  ];
  const gateway = {
    url: 'http://127.0.0.1:1234',
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: structuredClone(rows) }; },
    async session(id) { return structuredClone(rows.find(row => row.session_id === id)); },
    async approvals() { return { approvals: [] }; },
    async receipt() { return { status: 'running' }; },
    async queue() { return { items: [] }; },
    async *events() {},
  };
  const saved = [];
  const client = new Conversation(gateway, () => {}, async state => saved.push(structuredClone(state)));
  return { gateway, client, saved };
}

test('selecting a conversation opens a durable client tab without duplicating it', async () => {
  const { client, saved } = fixture();
  await client.refresh('one');
  await client.refresh('two');
  await client.refresh('one');
  assert.deepEqual(client.openSessionIds, ['one', 'two']);
  assert.deepEqual(saved.at(-1).openSessionIds, ['one', 'two']);
  client.dispose();
});

test('closing the active tab selects the remaining tab; closing the last returns to chat home', async () => {
  const { client } = fixture();
  await client.refresh('one');
  await client.refresh('two');
  await client.closeSession('two');
  assert.deepEqual(client.openSessionIds, ['one']);
  assert.equal(client.state.session.session_id, 'one');

  await client.closeSession('one');
  assert.deepEqual(client.openSessionIds, []);
  assert.equal(client.state.session, null);
  client.dispose();
});

test('closing a non-active tab keeps the current conversation selected', async () => {
  const { client } = fixture();
  await client.refresh('one');
  await client.refresh('two');
  await client.closeSession('one');
  assert.deepEqual(client.openSessionIds, ['two']);
  assert.equal(client.state.session.session_id, 'two');
  client.dispose();
});

test('the webview renders closeable session tabs from Gateway-owned sessions', () => {
  const html = readMedia('index.html');
  const view = readMedia('view.js');
  const css = readMedia('view.css');
  assert.match(html, /id="session-tabs"/);
  assert.match(view, /renderSessionTabs\(\)/);
  assert.match(view, /post\('closeSession', \{ id \}\)/);
  assert.match(css, /#session-tabs\{/);
});
