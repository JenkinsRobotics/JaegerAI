'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Conversation } = require('../conversation');
const { parse } = require('../media/slash-commands');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

function fixture() {
  const sessions = [
    { session_id: 'one', title: 'One', metadata: {}, status: 'idle', messages: [] },
    { session_id: 'two', title: 'Two', metadata: { archived: true }, status: 'idle', messages: [] },
  ];
  const gateway = {
    url: 'http://127.0.0.1:1234',
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: structuredClone(sessions) }; },
    async session(id) { return structuredClone(sessions.find(row => row.session_id === id)); },
    async approvals() { return { approvals: [] }; },
    async receipt() { return { status: 'running' }; },
    async queue() { return { items: [] }; },
    async archive(sid, archived) { this.archived = { sid, archived }; return structuredClone({ ...sessions[0], metadata: { archived } }); },
    async *events() {},
  };
  const client = new Conversation(gateway, () => {}, async () => {});
  return { gateway, client };
}

test('archive and unarchive are real session commands', () => {
  assert.equal(parse('/archive', { session: true }).command.name, 'archive');
  assert.equal(parse('/unarchive', { session: true }).command.name, 'unarchive');
  assert.equal(parse('/archive', {}), null);
});

test('conversation updates Gateway archive state and its local projection', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.setArchived('one', true);
  assert.deepEqual(gateway.archived, { sid: 'one', archived: true });
  assert.equal(client.state.session.metadata.archived, true);
  assert.equal(client.state.sessions.find(row => row.session_id === 'one').metadata.archived, true);
  client.dispose();
});

test('the chat list separates active and Gateway-archived sessions', () => {
  const view = read('media/view.js');
  const css = read('media/view.css');
  assert.match(view, /const active = sessions\.filter\(session => !session\.metadata\?\.archived\)/);
  assert.match(view, /const archived = sessions\.filter\(session => Boolean\(session\.metadata\?\.archived\)\)/);
  assert.match(view, /archiveHeading\(\)/);
  assert.match(css, /\.chat-archive-label\{/);
});
