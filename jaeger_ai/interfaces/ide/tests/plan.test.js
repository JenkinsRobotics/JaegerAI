'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Conversation } = require('../conversation');
const { parse } = require('../media/slash-commands');

const readMedia = name => fs.readFileSync(path.join(__dirname, '..', 'media', name), 'utf8');

test('/plan is a real command that takes a request', () => {
  const parsed = parse('/plan repair the login loop', {});
  assert.equal(parsed.command.name, 'plan');
  assert.equal(parsed.args, 'repair the login loop');
  assert.equal(parse('/plan', {}).command.takesArgs, true);
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
    async send(sid, body) { this.sent = { sid, body }; return { start_event_id: 2, status: 'running' }; },
    async queue() { return { items: [] }; },
    async queueAdd(sid, body) { this.queueAdd = { sid, body }; return { status: 'queued', queued: true }; },
    async *events() {},
  };
  const client = new Conversation(gateway, () => {}, async () => {});
  return { gateway, client };
}

test('plan mode sends the Gateway-enforced update_plan-only grant', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.send('repair the login loop', '', '', '', null, ['update_plan']);
  assert.deepEqual(gateway.sent.body.allowed_tools, ['update_plan']);
  assert.equal(gateway.sent.body.text, 'repair the login loop');
  client.dispose();
});

test('queued plan work also carries the update_plan-only grant', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.queue('plan the deploy check', '', '', '', null, ['update_plan']);
  assert.deepEqual(gateway.queueAdd ? gateway.queueAdd.body.allowed_tools : undefined, ['update_plan']);
  client.dispose();
});

test('the webview and extension expose the real Plan mode contract', () => {
  const html = readMedia('index.html');
  const view = readMedia('view.js');
  const extension = readMedia('../extension.js');
  assert.match(html, /id="plan-mode"/);
  assert.match(view, /planModeOn/);
  assert.match(view, /planOnly: planModeOn/);
  assert.match(extension, /message\.planOnly \? \['update_plan'\] : null/);
  assert.doesNotMatch(view, /plan-only prompt only/);
});
