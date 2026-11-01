'use strict';
// @jaeger through the shipped entry: streamed deltas, Sources, follow-ups,
// search counts, and Retry (VS Code re-invokes the handler with the prompt).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { observeNativeTurn, renderNativeSources, nativeFollowups } = require('../native-turn');

const root = path.join(__dirname, '..');
const sid = 'session-1';

function fakeGateway(script) {
  const gw = { created: [], sent: [], url: 'http://127.0.0.1:1' };
  gw.create = async body => { gw.created.push(body); return { session_id: body.session_id }; };
  gw.send = async (sessionId, body) => { gw.sent.push({ sessionId, ...body }); return { start_event_id: 1, status: 'running' }; };
  gw.events = async function* () { yield* script(gw.sent.at(-1).request_id); };
  gw.receipt = async () => gw.receiptFor(gw.sent.at(-1).request_id);
  gw.receiptFor = () => ({ status: 'completed', result: { output: '# Hello world' } });
  return gw;
}

// Any API these tests do not exercise is a no-op returning a disposable.
function inert() {
  const fn = function () { return inert(); };
  return new Proxy(fn, { get: (t, k) => (k === 'dispose' ? () => {} : k === 'then' ? undefined
    : k === Symbol.toPrimitive ? () => '' : k in t ? t[k] : (t[k] = inert())) });
}
const lenient = obj => new Proxy(obj, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) });

function loadParticipant(gw) {
  let participant;
  const vscode = lenient({
    commands: { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} },
    chat: { createChatParticipant: (id, handler) => (participant = { id, handler, dispose() {} }) },
    window: lenient({ createOutputChannel: () => ({ appendLine() {}, dispose() {} }), registerWebviewViewProvider: () => ({ dispose() {} }),
      onDidChangeActiveTextEditor: () => ({ dispose() {} }), activeTextEditor: undefined }),
    workspace: lenient({ getConfiguration: () => ({ get: () => '', inspect: () => ({}) }), onDidChangeConfiguration: () => ({ dispose() {} }),
      workspaceFolders: [{ uri: { fsPath: root } }], getWorkspaceFolder: () => undefined }),
    Uri: { joinPath: () => ({}), parse: s => ({ scheme: 'https', s }), file: s => ({ scheme: 'file', s }) },
  });
  const original = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return vscode;
    if (request === './gateway' && parent?.filename === path.join(root, 'chat-panel.js')) {
      return { Gateway: class { constructor() { return gw; } }, GatewayError: Error, localEndpoint: u => u };
    }
    return original.call(this, request, parent, isMain);
  };
  const panel = path.join(root, 'chat-panel.js');
  delete require.cache[panel];
  try { require(panel).activate({ subscriptions: { push() {} }, extensionUri: {}, extensionPath: root,
    globalState: { get: () => undefined, update: async () => {} }, workspaceState: { get: () => undefined, update: async () => {} },
    globalStorageUri: { fsPath: '/tmp/jaeger-native-events-test' } }); }
  finally { Module._load = original; delete require.cache[panel]; }
  return participant;
}

function recorder() {
  const out = { markdown: [], references: [], progress: [] };
  return { out, stream: { markdown: t => out.markdown.push(t), progress: t => out.progress.push(t), reference: u => out.references.push(u), button() {} } };
}
const token = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };

const fullTurn = function* (rid) {
  yield { event_id: 2, event: 'turn.delta', data: { request_id: rid, delta: '# Hello ' } };
  yield { event_id: 3, event: 'sources', data: { request_id: rid, sources: [
    { kind: 'file', location: '/w/package.json' }, { kind: 'url', location: 'https://example.com/a', title: 'A' },
    { kind: 'file', location: '/w/package.json' }, { kind: 'bogus', location: 'x' }] } };
  yield { event_id: 4, event: 'turn.delta', data: { request_id: rid, delta: 'world' } };
  yield { event_id: 5, event: 'search.count', data: { request_id: rid, searches: 2, completed: 2, failed: 0 } };
  yield { event_id: 6, event: 'follow_ups', data: { request_id: rid, follow_ups: ['Show the tests?', 'x'.repeat(161), 7] } };
  yield { event_id: 7, event: 'turn.delta', data: { request_id: 'someone-else', delta: 'LEAK' } };
  yield { event_id: 8, event: 'turn.finish', data: { request_id: rid } };
};

test('@jaeger streams deltas in the IDE, then Sources and follow-ups', async () => {
  const gw = fakeGateway(fullTurn);
  const participant = loadParticipant(gw);
  assert.equal(participant.id, 'jaeger.chatParticipant');
  const { out, stream } = recorder();
  const result = await participant.handler({ prompt: 'Summarize' }, { history: [] }, stream, token);
  assert.deepEqual(out.markdown.slice(0, 2), ['# Hello ', 'world'], 'deltas stream in order, no "Request sent" stub');
  assert.ok(!out.markdown.join('').includes('LEAK'));
  assert.ok(!out.markdown.join('').includes('Request sent'));
  assert.match(out.markdown.join(''), /Searched 2 times/);
  assert.deepEqual(out.references, [{ scheme: 'file', s: '/w/package.json' }, { scheme: 'https', s: 'https://example.com/a' }]);
  assert.deepEqual(result.metadata.jaegerFollowUps, ['Show the tests?']);
  assert.deepEqual(participant.followupProvider.provideFollowups(result), [{ prompt: 'Show the tests?', label: 'Show the tests?' }]);
  assert.equal(gw.created[0].workspace_folder, root, 'workspace_folder sent on session create');
  assert.equal(gw.sent[0].text, 'Summarize');
});

test('Retry re-invokes in the same Gateway session with a new request id', async () => {
  let fail = true;
  const gw = fakeGateway(function* (rid) { yield { event_id: 2, event: fail ? 'turn.failed' : 'turn.finish', data: { request_id: rid } }; });
  gw.receiptFor = () => (fail ? { status: 'failed', result: { error: 'model timeout' } } : { status: 'completed', result: { output: 'Recovered' } });
  const participant = loadParticipant(gw);
  const first = recorder();
  const failed = await participant.handler({ prompt: 'Summarize' }, { history: [] }, first.stream, token);
  assert.match(first.out.markdown.join(''), /request failed:\*\* model timeout/);
  assert.equal(failed.metadata.jaegerFollowUps, undefined, 'no follow-ups for a failed turn');
  fail = false;
  const second = recorder();
  const retried = await participant.handler({ prompt: 'Summarize' }, { history: [{ result: failed }] }, second.stream, token);
  assert.equal(gw.created.length, 1, 'retry reuses the session');
  assert.equal(retried.metadata.jaegerSessionId, failed.metadata.jaegerSessionId);
  assert.notEqual(gw.sent[1].request_id, gw.sent[0].request_id, 'retry is a new request, not a replay');
  assert.deepEqual(second.out.markdown, ['Recovered']);
});

test('/explain streams an answer with editor context instead of firing and forgetting', async () => {
  const gw = fakeGateway(function* (rid) { yield { event_id: 2, event: 'turn.delta', data: { request_id: rid, delta: 'It does X' } }; yield { event_id: 3, event: 'turn.finish', data: { request_id: rid } }; });
  gw.receiptFor = () => ({ status: 'completed', result: { output: 'It does X' } });
  const participant = loadParticipant(gw);
  const { out, stream } = recorder();
  await participant.handler({ prompt: '', command: 'explain' }, { history: [] }, stream, token);
  assert.match(gw.sent[0].text, /^Explain the current file or selection/);
  assert.deepEqual(out.markdown, ['It does X']);
});

test('observeNativeTurn filters sources, follow-ups and search counts like the panel', async () => {
  const gw = { events: async function* () { yield* fullTurn('r1'); }, receipt: async () => ({ status: 'completed', result: { output: '# Hello world' } }) };
  const { out, stream } = recorder();
  const outcome = await observeNativeTurn({ gateway: gw, sessionId: sid, requestId: 'r1', admitted: { start_event_id: 1, status: 'running' }, signal: new AbortController().signal, stream });
  assert.equal(outcome.text, '# Hello world');
  assert.deepEqual(outcome.sources.map(s => s.location), ['/w/package.json', 'https://example.com/a']);
  assert.deepEqual(outcome.followUps, ['Show the tests?']);
  assert.deepEqual(outcome.searchCount, { searches: 2, completed: 2, failed: 0 });
  assert.deepEqual(out.markdown, ['# Hello ', 'world']);
});

test('without stream.reference, Sources render as a markdown list', () => {
  const md = [];
  renderNativeSources({ markdown: t => md.push(t) }, { sources: [{ kind: 'url', location: 'https://e.com', title: 'E [1]' }, { kind: 'file', location: '/w/a`b.js' }] });
  assert.equal(md.join(''), '\n\n**Sources**\n\n- [E 1](https://e.com)\n- `/w/ab.js`');
  assert.deepEqual(nativeFollowups({}), []);
});
