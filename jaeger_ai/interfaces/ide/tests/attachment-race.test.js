'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Conversation } = require('../conversation');

function makeGateway(overrides = {}) {
  return {
    url: 'http://127.0.0.1:1234',
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: [] }; },
    async session(id) { return { session_id: id, title: id, status: 'idle', messages: [] }; },
    async approvals() { return { approvals: [] }; },
    async models() { return { providers: [] }; },
    async addAttachment(sid, body) { return { attachment_id: `att-${body.filename}`, original_filename: body.filename }; },
    async send(sid, body) { return { start_event_id: 1, status: 'completed' }; },
    async receipt(sid, rid) { return { status: 'completed', result: {} }; },
    async session_after_finish(id) { return { session_id: id, title: id, status: 'completed', messages: [] }; },
    ...overrides,
  };
}

test('stale attachment completing after session switch is discarded', async () => {
  let resolveUpload;
  const gateway = makeGateway({
    addAttachment: async () => new Promise(resolve => { resolveUpload = resolve; }),
  });
  const client = new Conversation(gateway, () => {}, async () => {});
  await client.refresh('first');
  const uploading = client.addAttachment({ path: '/w/a.txt', name: 'a.txt' });
  await client.refresh('second');
  resolveUpload({ attachment_id: 'belongs-to-first' });
  await uploading;
  assert.equal(client.state.session.session_id, 'second');
  assert.deepEqual(client.staged, [], 'attachment from first session must not appear in second composer');
  client.dispose();
});

test('attachment completing in the same session is staged normally', async () => {
  const gateway = makeGateway();
  const client = new Conversation(gateway, () => {}, async () => {});
  await client.refresh('s1');
  await client.addAttachment({ path: '/w/b.txt', name: 'b.txt' });
  assert.equal(client.staged.length, 1);
  assert.equal(client.staged[0].attachment_id, 'att-b.txt');
  client.dispose();
});

test('upload in-flight when send fires does not resurrect cleared attachments', async () => {
  let resolveUpload;
  const gateway = makeGateway({
    addAttachment: async () => new Promise(resolve => { resolveUpload = resolve; }),
    receipt: async () => ({ status: 'completed', result: {} }),
    async *events() {},
  });
  const client = new Conversation(gateway, () => {}, async () => {});
  await client.refresh('s2');
  const uploading = client.addAttachment({ path: '/w/c.txt', name: 'c.txt' });
  // send resolves immediately and clears staged on successful admission
  await client.send('hello');
  // upload completes after send already cleared staged — must not resurrect
  resolveUpload({ attachment_id: 'late-upload' });
  await uploading;
  assert.deepEqual(client.staged, [], 'completed upload must not resurrect attachments cleared by send');
  client.dispose();
});

test('removing an older attachment does not discard a different in-flight upload', async () => {
  let resolveUpload;
  const gateway = makeGateway({
    addAttachment: async () => new Promise(resolve => { resolveUpload = resolve; }),
  });
  const client = new Conversation(gateway, () => {}, async () => {});
  await client.refresh('s4');
  client.staged = [{ attachment_id: 'older' }];
  const uploading = client.addAttachment({ path: '/w/e.txt', name: 'e.txt' });
  client.removeStagedAttachment('older');
  resolveUpload({ attachment_id: 'newer' });
  await uploading;
  assert.deepEqual(client.staged, [{ attachment_id: 'newer' }], 'in-flight upload must land after an unrelated removal');
  client.dispose();
});

test('stale attachment completing after dispose is discarded', async () => {
  let resolveUpload;
  const gateway = makeGateway({
    addAttachment: async () => new Promise(resolve => { resolveUpload = resolve; }),
  });
  const client = new Conversation(gateway, () => {}, async () => {});
  await client.refresh('s3');
  const uploading = client.addAttachment({ path: '/w/d.txt', name: 'd.txt' });
  client.dispose();
  resolveUpload({ attachment_id: 'post-dispose' });
  await uploading;
  assert.deepEqual(client.staged, [], 'disposed client must not accumulate staged attachments');
});
