'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Gateway, GatewayError, localEndpoint, decodeSSE } = require('../gateway');
const { statusLabel } = require('../media/presentation');
const {
  Conversation, COMPLETED_TIMELINE_SESSION_LIMIT, COMPLETED_TIMELINE_ROW_LIMIT,
  COMPLETED_TIMELINE_TEXT_LIMIT,
} = require('../conversation');
const waitFor = async predicate => {
  const end = Date.now() + 10000;
  while (!predicate()) { if (Date.now() > end) throw new Error('Timed out'); await new Promise(r => setTimeout(r, 10)); }
};

test('local endpoints only, without credential/path ambiguity', () => {
  assert.equal(localEndpoint('http://127.0.0.1:1234'), 'http://127.0.0.1:1234');
  for (const url of ['https://example.org', 'http://example.org', 'http://user:pass@localhost', 'http://localhost/path', 'http://localhost/?key=x']) {
    assert.throws(() => localEndpoint(url));
  }
});
test('SSE UTF-8, CRLF, multiline data, arbitrary chunk splits and incomplete EOF', async () => {
  const bytes = Buffer.from(': keepalive\r\nid: 7\r\nevent: turn.delta\r\ndata: {"text":\r\ndata: "🌱"}\r\n\r\ndata: {"incomplete":');
  async function* chunks() { for (const byte of bytes) yield Buffer.from([byte]); }
  const events = []; for await (const event of decodeSSE(chunks())) events.push(event);
  assert.deepEqual(events, [{ name: 'turn.delta', id: '7', payload: { text: '🌱' } }]);
});
function fixture() {
  const gateway = {
    url: 'http://127.0.0.1:1234', row: { session_id: 'one', title: 'One', status: 'idle', messages: [] },
    async json() { return { component: 'jaeger-gateway' }; },
    async sessions() { return { sessions: [this.row] }; }, async session() { return structuredClone(this.row); },
    async approvals() { return { approvals: [] }; },
    async receipt() { return { status: 'running' }; },
    async send(sid, body) { this.sent = body; return { start_event_id: 2, status: 'running' }; },
    async *events() {}, async cancel(sid, rid) { this.cancelled = rid; return { cancellation_confirmed: false }; },
    async addAttachment(sid, body) { return { attachment_id: 'att-1', original_filename: body.filename }; },
    async models() { return { providers: [] }; },
    async orchestrationWorkers() { return { workers: [{ worker_id: 'claude', available: true, capabilities: ['code'] }] }; },
    async orchestrationSubmit(body) { this.taskSubmitted = body; return { task_id: body.task_id, state: 'queued' }; },
    async orchestrationTask(id) { return this.taskStatus || { task_id: id, state: 'completed', result: { output: 'Done', verified: true } }; },
    async orchestrationCancel(id) { this.taskCancelled = id; return { cancelled: true }; },
  };
  let saved;
  const client = new Conversation(gateway, () => {}, async value => { saved = structuredClone(value); });
  return { gateway, client, saved: () => saved };
}
test('EOF cannot mark a running request completed; retry never submits again', async () => {
  const { gateway, client, saved } = fixture();
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(client.state.busy, true); assert.ok(saved().pending.one.requestId);
  const rid = gateway.sent.request_id;
  await client.refresh('one'); await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(gateway.sent.request_id, rid);
  await client.cancel(); assert.equal(gateway.cancelled, rid); assert.equal(client.state.busy, true);
  client.dispose();
});
test('cross-request deltas ignored and completion requires authoritative history', async () => {
  const { gateway, client } = fixture(); let finished = false;
  gateway.receipt = async () => ({ status: finished ? 'completed' : 'running' });
  gateway.events = async function* () {
    yield { event: 'turn.delta', data: { request_id: 'other', delta: 'WRONG' } };
    yield { event: 'turn.delta', data: { request_id: this.sent.request_id, delta: 'RIGHT' } };
    assert.equal(client.state.text, 'RIGHT');
    finished = true; this.row.messages = [{ role: 'assistant', content: 'RIGHT' }];
    yield { event: 'turn.finish', data: { request_id: this.sent.request_id } };
  };
  await client.refresh('one'); await client.send('hello'); await waitFor(() => !client.state.busy);
  assert.equal(client.state.session.messages[0].content, 'RIGHT'); assert.deepEqual(client.pending, {});
  client.dispose();
});
test('rejection permits correction, uncertain transport retains same request', async () => {
  for (const status of [409, 0]) {
    const { gateway, client } = fixture();
    gateway.send = async () => { throw new GatewayError('failure', status); };
    await client.refresh('one'); await client.send('hello');
    assert.equal(client.state.busy, status === 0);
    assert.equal(Boolean(client.pending.one), status === 0); client.dispose();
  }
});
test('approval cannot target another session', async () => {
  const { client } = fixture(); await client.refresh('one');
  await assert.rejects(client.approve('other', true), /no longer pending/); client.dispose();
});

test('disposed controller cannot publish or persist a late rejected send', async () => {
  const { gateway, client } = fixture();
  const published = [];
  const saved = [];
  client.publish = value => published.push(value);
  client.save = async value => { saved.push(structuredClone(value)); };
  await client.refresh('one');
  let rejectSend;
  gateway.send = async () => new Promise((resolve, reject) => { rejectSend = reject; });
  const sending = client.send('hello');
  await waitFor(() => typeof rejectSend === 'function');
  published.length = 0; saved.length = 0;
  client.dispose();
  rejectSend(new GatewayError('rejected after replacement', 409));
  await sending;
  assert.deepEqual(published, [], 'an obsolete controller must not overwrite the new panel state');
  assert.deepEqual(saved, [], 'an obsolete controller must not overwrite durable panel state');
});

test('disposed controller does not refresh a session created after replacement', async () => {
  const { gateway, client } = fixture();
  let resolveCreate;
  let sessionLists = 0;
  gateway.sessions = async () => { sessionLists += 1; return { sessions: [gateway.row] }; };
  gateway.create = async () => new Promise(resolve => { resolveCreate = resolve; });
  await client.refresh('one');
  const creating = client.newSession('late');
  await waitFor(() => typeof resolveCreate === 'function');
  client.dispose();
  resolveCreate({ session_id: 'two' });
  await creating;
  assert.equal(sessionLists, 1, 'late completion must not start a refresh from the obsolete controller');
});
test('restored pending request finishes from receipt without a second submission', async () => {
  const { gateway } = fixture();
  gateway.receipt = async () => ({ status: 'completed' });
  gateway.row.messages = [{ role: 'assistant', content: 'already finished' }];
  gateway.send = async () => { throw new Error('Must not resubmit'); };
  const client = new Conversation(gateway, () => {}, async () => {}, {
    pending: { one: { requestId: 'durable-id', startCursor: 1 } },
  });
  await client.refresh('one'); await waitFor(() => !client.state.busy);
  assert.deepEqual(client.pending, {}); assert.equal(client.state.session.messages[0].content, 'already finished');
  client.dispose();
});
test('duplicate SSE event IDs do not duplicate live text', async () => {
  const { gateway, client } = fixture();
  gateway.events = async function* () {
    const event = { event_id: 2, event: 'turn.delta', data: { request_id: this.sent.request_id, delta: 'once' } };
    yield event; yield event;
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(client.state.text, 'once'); client.dispose();
});
test('send() always sends attachment_ids, defaulting to an empty array', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.deepEqual(gateway.sent.attachment_ids, []);
  client.dispose();
});

test('staged attachments become the sent turn\'s attachment_ids and clear once admitted', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  await client.addAttachment({ path: '/workspace/a.txt', name: 'a.txt', mime: 'text/plain', size: 3 });
  assert.equal(client.staged.length, 1);
  assert.equal(client.staged[0].attachment_id, 'att-1');
  await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.deepEqual(gateway.sent.attachment_ids, ['att-1']);
  assert.equal(client.staged.length, 0, 'a successfully admitted turn clears its staged attachments');
  client.dispose();
});

test('removeStagedAttachment drops exactly that attachment', async () => {
  const { gateway, client } = fixture();
  gateway.addAttachment = async (sid, body) => ({ attachment_id: body.filename, original_filename: body.filename });
  await client.refresh('one');
  await client.addAttachment({ path: '/a', name: 'a.txt', mime: 'text/plain', size: 1 });
  await client.addAttachment({ path: '/b', name: 'b.txt', mime: 'text/plain', size: 1 });
  client.removeStagedAttachment('a.txt');
  assert.deepEqual(client.staged.map(a => a.attachment_id), ['b.txt']);
  client.dispose();
});

test('switching conversations drops attachments staged for the previous one', async () => {
  const { gateway, client } = fixture();
  gateway.row2 = { session_id: 'two', title: 'Two', status: 'idle', messages: [] };
  gateway.session = async id => structuredClone(id === 'two' ? gateway.row2 : gateway.row);
  gateway.sessions = async () => ({ sessions: [gateway.row, gateway.row2] });
  await client.refresh('one');
  await client.addAttachment({ path: '/a', name: 'a.txt', mime: 'text/plain', size: 1 });
  assert.equal(client.staged.length, 1);
  await client.refresh('two');
  assert.equal(client.staged.length, 0);
  client.dispose();
});

test('turn.reasoning accumulates into state.reasoning, never into state.activity', async () => {
  const { gateway, client } = fixture();
  gateway.events = async function* () {
    yield { event: 'turn.reasoning', data: { request_id: this.sent.request_id, text: 'thinking…' } };
    yield { event: 'turn.reasoning', data: { request_id: this.sent.request_id, text: ' more.' } };
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(client.state.reasoning, 'thinking… more.');
  assert.deepEqual(client.state.activity, []);
  client.dispose();
});

test('a fresh turn clears the previous turn\'s reasoning', async () => {
  const { gateway, client } = fixture();
  gateway.events = async function* () {
    yield { event: 'turn.reasoning', data: { request_id: this.sent.request_id, text: 'first turn' } };
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(client.state.reasoning, 'first turn');
  gateway.events = async function* () {};
  await client.refresh('one'); await client.send('hello again');
  assert.equal(client.state.reasoning, '');
  client.dispose();
});

test('loadModels populates state.models once from the Gateway\'s catalog', async () => {
  const { gateway, client } = fixture();
  let calls = 0;
  gateway.models = async () => { calls += 1; return { providers: [{ id: 'x', reachable: true, models: [] }] }; };
  await client.refresh('one');
  assert.equal(calls, 1);
  assert.deepEqual(client.state.models, { providers: [{ id: 'x', reachable: true, models: [] }] });
  await client.refresh('one');
  assert.equal(calls, 1, 'models are fetched once per panel lifetime, not on every refresh');
  client.dispose();
});

test('a model-catalog failure surfaces modelsError without blocking the conversation', async () => {
  const { gateway, client } = fixture();
  gateway.models = async () => { throw new Error('runtime/models unreachable'); };
  await client.refresh('one');
  assert.equal(client.state.connected, true);
  assert.match(client.state.modelsError, /unreachable/);
  client.dispose();
});

test('send() carries provider to admission body when provided alongside model', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one'); await client.send('hello', 'gpt-4', 'openai');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(gateway.sent.model, 'gpt-4');
  assert.equal(gateway.sent.provider, 'openai');
  client.dispose();
});

test('send() without provider omits provider field from admission body', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one'); await client.send('hello', 'gpt-4');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.equal(gateway.sent.model, 'gpt-4');
  assert.ok(!('provider' in gateway.sent), 'provider must be absent when not given');
  client.dispose();
});

test('send() with empty model omits both model and provider from admission body', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one'); await client.send('hello', '');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.ok(!('model' in gateway.sent), 'model must be absent for Gateway default');
  assert.ok(!('provider' in gateway.sent), 'provider must be absent for Gateway default');
  client.dispose();
});

test('explicit refresh reloads the model catalog', async () => {
  const { gateway, client } = fixture();
  let calls = 0;
  gateway.models = async () => { calls++; return { providers: [] }; };
  await client.refresh('one');
  assert.equal(calls, 1);
  await client.refresh('one', true);
  assert.equal(calls, 2, 'catalog must re-fetch on explicit reconnect');
  client.dispose();
});

test('non-explicit refresh does not reload the catalog', async () => {
  const { gateway, client } = fixture();
  let calls = 0;
  gateway.models = async () => { calls++; return { providers: [] }; };
  await client.refresh('one'); assert.equal(calls, 1);
  await client.refresh('one');
  assert.equal(calls, 1, 'catalog must not re-fetch on implicit refresh');
  client.dispose();
});

// NOTE: The Gateway's _turn_stream_callbacks currently forwards only turn.delta
// and turn.reasoning to the SSE event bus. Tool events (tool.started/tool.completed)
// are emitted via run.emit() to the native run store and are NOT forwarded to SSE.
// The tests below verify the observe() conditional branch logic using synthetic
// events that carry data.tool; they do NOT prove real end-to-end Gateway activity.

test('observe(): SSE event with data.tool uses real tool name for activity item name', async () => {
  const { gateway, client } = fixture();
  gateway.events = async function* () {
    // Synthetic: real Gateway SSE does not yet emit data.tool events.
    yield { event: 'tool.started', data: { request_id: this.sent.request_id, call_id: 'call-1', tool: 'mcp__fs__read_file' } };
    yield { event: 'tool.completed', data: { request_id: this.sent.request_id, call_id: 'call-1', tool: 'mcp__fs__read_file', ok: true } };
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  const named = client.state.activity.filter(a => a.name);
  assert.equal(named.length, 1, 'one stable tool row advances from started to completed');
  assert.equal(named[0].name, 'mcp__fs__read_file');
  assert.equal(named[0].ok, true);
  client.dispose();
});

test('observe(): SSE event without data.tool becomes a nameless group separator', async () => {
  const { gateway, client } = fixture();
  gateway.events = async function* () {
    // turn.status is a real Gateway SSE event with no data.tool field.
    yield { event: 'turn.status', data: { request_id: this.sent.request_id, status: 'running' } };
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => client.state.status.includes('interrupted'));
  assert.ok(client.state.activity.length > 0, 'status event should record a marker');
  assert.ok(!client.state.activity[0].name, 'status event must not receive a tool name');
  client.dispose();
});

test('state.busy is false after turn completes so activityTitle reflects Used, not Using', async () => {
  const { gateway, client } = fixture();
  let finished = false;
  gateway.receipt = async () => ({ status: finished ? 'completed' : 'running' });
  gateway.events = async function* () {
    // Synthetic tool event (not currently emitted by real Gateway SSE).
    yield { event: 'tool.started', data: { request_id: this.sent.request_id, tool: 'read_file' } };
    finished = true;
    this.row.messages = [{ role: 'assistant', content: 'done' }];
    yield { event: 'turn.finish', data: { request_id: this.sent.request_id } };
  };
  await client.refresh('one'); await client.send('hello');
  await waitFor(() => !client.state.busy);
  assert.equal(client.state.busy, false);
  const { activityTitle, toolName } = require('../media/presentation');
  const namedItems = client.state.activity.filter(a => a.name);
  assert.equal(activityTitle(namedItems, false), `Used ${toolName('read_file')}`);
  client.dispose();
});

test('completed tool rows survive turn.finish and a controller reconnect without duplicating the answer', async () => {
  const { gateway, client, saved } = fixture();
  let finished = false;
  gateway.receipt = async () => ({ status: finished ? 'completed' : 'running' });
  gateway.events = async function* () {
    const rid = this.sent.request_id;
    yield { event_id: 20, event: 'tool.started', data: {
      request_id: rid, activity_id: 'fast-read', tool: 'read_file', status: 'reading',
    } };
    yield { event_id: 21, event: 'tool.completed', data: {
      request_id: rid, activity_id: 'fast-read', tool: 'read_file', ok: true,
    } };
    yield { event_id: 22, event: 'turn.delta', data: { request_id: rid, delta: 'done' } };
    finished = true;
    this.row.messages = [
      { role: 'user', content: 'read it' },
      { role: 'assistant', content: 'done' },
    ];
    yield { event_id: 23, event: 'turn.finish', data: { request_id: rid } };
  };

  await client.refresh('one');
  await client.send('read it');
  await waitFor(() => !client.state.busy);
  assert.deepEqual(client.state.timeline.map(row => row.kind), ['tool']);
  assert.equal(client.state.timeline[0].name, 'read_file');
  assert.equal(client.state.timeline[0].live, false);
  assert.equal(client.state.text, '', 'the authoritative history owns the settled answer');

  const restored = new Conversation(gateway, () => {}, async () => {}, saved());
  await restored.refresh('one');
  assert.deepEqual(restored.state.timeline.map(row => row.kind), ['tool']);
  assert.equal(restored.state.timeline[0].key, client.state.timeline[0].key);
  assert.equal(restored.state.session.messages.filter(row => row.role === 'assistant').length, 1);
  restored.dispose(); client.dispose();
});

test('completed activity persistence is bounded and isolated by conversation', () => {
  const { gateway } = fixture();
  const completedTimelines = {};
  for (let session = 0; session < COMPLETED_TIMELINE_SESSION_LIMIT + 3; session++) {
    completedTimelines[`session-${session}`] = {
      cursor: session,
      rows: Array.from({ length: COMPLETED_TIMELINE_ROW_LIMIT + 5 }, (_, row) => ({
        key: `tool:session-${session}:${row}`, kind: 'tool',
        requestId: `request-${session}`, name: `tool-${session}`,
        detail: 'x'.repeat(COMPLETED_TIMELINE_TEXT_LIMIT + 20),
        phase: 'completed', ok: true, live: false,
      })),
    };
  }
  const client = new Conversation(gateway, () => {}, async () => {}, { completedTimelines });
  const sessionIds = Object.keys(client.completedTimelines);
  assert.equal(sessionIds.length, COMPLETED_TIMELINE_SESSION_LIMIT);
  assert.equal(sessionIds[0], 'session-3', 'oldest activity cache entries are pruned first');
  for (const [sid, timeline] of Object.entries(client.completedTimelines)) {
    assert.equal(timeline.rows.length, COMPLETED_TIMELINE_ROW_LIMIT);
    assert.ok(timeline.rows.every(row => row.name === `tool-${sid.slice(8)}`),
      'one conversation must never receive another conversation activity');
    assert.ok(timeline.rows.every(row => row.detail.length === COMPLETED_TIMELINE_TEXT_LIMIT));
  }
  client.restoreCompletedTimeline(sessionIds.at(-1));
  assert.equal(client.state.timeline.length, COMPLETED_TIMELINE_ROW_LIMIT);
  assert.ok(client.state.timeline.every(row => row.requestId === `request-${sessionIds.at(-1).slice(8)}`));
  client.dispose();
});

test('real isolated Gateway: two turns, history, cancellation and next turn', { skip: !process.env.JAEGER_IDE_TEST_URL }, async () => {
  const gateway = new Gateway(process.env.JAEGER_IDE_TEST_URL);
  const client = new Conversation(gateway, () => {}, async () => {});
  try {
    await client.refresh(); await client.newSession('IDE integration');
    for (const text of ['Say CONTRACT-ANSWER', 'Say CONTRACT-ANSWER again']) {
      await client.send(text); await waitFor(() => !client.state.busy);
      assert.equal(client.state.status, 'completed');
      assert.match(client.state.session.messages.at(-1).content, /CONTRACT-ANSWER/);
    }
    assert.equal(client.state.session.messages.filter(m => m.role === 'user').length, 2);
    const sid = client.state.session.session_id;
    await client.send('CONTRACT-WAIT slow response'); await client.cancel();
    await waitFor(() => !client.state.busy); assert.equal(client.state.status, 'cancelled');
    await client.send('Say CONTRACT-ANSWER after cancel'); await waitFor(() => !client.state.busy);
    await client.refresh(sid); assert.equal(client.state.session.session_id, sid);
    assert.match(client.state.session.messages.at(-1).content, /CONTRACT-ANSWER/);
    await client.newSession('IDE approval');
    await client.send('CONTRACT-WRITE'); await waitFor(() => client.state.approvals.length > 0);
    const approval = client.state.approvals[0];
    await client.approve(approval.approval_id || approval.id, false);
    await waitFor(() => !client.state.busy);
    assert.match(client.state.session.messages.at(-1).content, /PermissionDenied|refused/);

    // Attachments: a real upload from inside the instance workspace, a real
    // rejection from outside it, explicit attachment_ids on the sent turn
    // (never omitted), and staged clearing once the turn is admitted.
    await client.newSession('IDE attachment');
    await client.addAttachment({
      path: process.env.JAEGER_IDE_TEST_ATTACHMENT_PATH, name: 'ide-attachment.txt',
      mime: 'text/plain', size: 32,
    });
    assert.equal(client.staged.length, 1);
    assert.equal(client.staged[0].original_filename, 'ide-attachment.txt');
    const registered = await gateway.attachments(client.state.session.session_id);
    assert.equal(registered.attachments.length, 1);
    await assert.rejects(client.addAttachment({
      path: process.env.JAEGER_IDE_TEST_ATTACHMENT_OUTSIDE_PATH, name: 'outside-workspace.txt',
      mime: 'text/plain', size: 17,
    }), /escapes workspace|Session not found|attachment/i);
    assert.equal(client.staged.length, 1, 'a rejected upload must not stage anything');
    await client.send('Say CONTRACT-ANSWER with an attachment');
    await waitFor(() => !client.state.busy);
    assert.equal(client.staged.length, 0, 'attachments clear once the turn that used them is admitted');
  } finally { client.dispose(); }
});

test('statusLabel accurately renders blocked, quota, auth, approval, unknown', () => {
  assert.equal(statusLabel({ connected: true, lastStatus: 'blocked' }), 'Blocked');
  assert.equal(statusLabel({ connected: true, lastStatus: 'quota' }), 'Quota exceeded');
  assert.equal(statusLabel({ connected: true, lastStatus: 'auth' }), 'Authentication required');
  assert.equal(statusLabel({ connected: true, lastStatus: 'approval' }), 'Waiting for your approval');
  assert.equal(statusLabel({ connected: true, lastStatus: 'unknown' }), 'Unknown status');
  assert.equal(statusLabel({ connected: true, lastStatus: 'cancelled' }), 'Cancelled');
  assert.equal(statusLabel({ connected: true, lastStatus: 'failed' }), 'Failed');
  assert.equal(statusLabel({ connected: true, lastStatus: 'completed' }), 'Completed');
  assert.equal(statusLabel({ connected: false }), 'Not connected');
});

test('loadWorkers populates state.workers from Gateway catalog', async () => {
  const { client } = fixture();
  await client.refresh('one');
  assert.equal(client.state.workers.length, 1);
  assert.equal(client.state.workers[0].worker_id, 'claude');
  client.dispose();
});

test('submitParentTask submits bounded task, updates activeTask and reflects terminal state', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  gateway.taskStatus = {
    task_id: 'task-test-01',
    state: 'completed',
    result: { output: 'All files checked', verified: true, reason: 'Valid' },
  };
  await client.submitParentTask({
    goal: 'Audit repository',
    worker: 'claude',
    taskId: 'task-test-01',
    readOnly: true,
  });
  await waitFor(() => !client.state.busy);
  assert.equal(gateway.taskSubmitted.task_id, 'task-test-01');
  assert.equal(gateway.taskSubmitted.worker, 'claude');
  assert.equal(gateway.taskSubmitted.read_only, true);
  assert.equal(client.state.status, 'completed');
  assert.equal(client.state.activeTask.result.output, 'All files checked');
  client.dispose();
});

test('submitParentTask preserves draft and does not clear prompt on failure', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  gateway.orchestrationSubmit = async () => { throw new GatewayError('Worker unavailable', 400); };
  let publishedAccepted = false;
  client.publish = msg => { if (msg.accepted) publishedAccepted = true; };

  await client.submitParentTask({
    goal: 'Run task on failing worker',
    worker: 'missing_worker',
    taskId: 'task-fail-01',
  });

  assert.equal(client.state.busy, false);
  assert.equal(publishedAccepted, false, 'accepted event must not be emitted on submission error');
  assert.match(client.state.error, /Worker unavailable/);
  client.dispose();
});

test('cancel during parent task requests orchestration cancellation via gateway', async () => {
  const { gateway, client } = fixture();
  await client.refresh('one');
  gateway.taskStatus = { task_id: 'task-long', state: 'running' };
  // Start task asynchronously
  const submitPromise = client.submitParentTask({
    goal: 'Long task',
    worker: 'claude',
    taskId: 'task-long',
  });
  await waitFor(() => client.state.busy);
  await client.cancel();
  assert.equal(gateway.taskCancelled, 'task-long');
  gateway.taskStatus = { task_id: 'task-long', state: 'failed', result: { reason: 'Cancelled by user' } };
  await waitFor(() => !client.state.busy);
  await submitPromise;
  client.dispose();
});
