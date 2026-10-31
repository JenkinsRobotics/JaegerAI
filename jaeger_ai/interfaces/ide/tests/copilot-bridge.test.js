'use strict';
// Copilot bridge: loopback HTTP server over a fake vscode.lm. Real sockets, temp HOME, no VS Code.
const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createBridge, RATE_PER_MIN, classify } = require('../copilot-bridge');

class LanguageModelError extends Error { constructor(m, code) { super(m); this.code = code; } }
LanguageModelError.NoPermissions = { name: 'NoPermissions' };
LanguageModelError.Blocked = { name: 'Blocked' };
LanguageModelError.NotFound = { name: 'NotFound' };

function fakeVscode({ chunks = ['Hel', 'lo'], fail = null, delay = 0 } = {}) {
  const calls = { cancelled: 0 };
  const model = {
    id: 'gpt-5.6-luna', name: 'GPT-5.6 Luna', family: 'gpt-5.6', vendor: 'copilot', version: '1', maxInputTokens: 128000,
    async sendRequest(_msgs, _opts, token) {
      if (fail) throw fail;
      return { text: (async function* () { for (const c of chunks) { if (delay) await new Promise((r) => setTimeout(r, delay)); if (token.isCancellationRequested) return; yield c; } })() };
    },
    async countTokens(t) { return Math.ceil(t.length / 2); },
  };
  return {
    calls, version: '1.143.0', LanguageModelError,
    LanguageModelChatMessage: { User: (t) => ({ role: 'user', content: t }) },
    CancellationTokenSource: class { constructor() { this.token = { isCancellationRequested: false }; } cancel() { this.token.isCancellationRequested = true; calls.cancelled++; } dispose() {} },
    lm: { selectChatModels: async (sel = {}) => (sel.id && sel.id !== model.id ? [] : [model]) },
    window: { showWarningMessage() {}, showInformationMessage() {} },
  };
}

function req(port, { method = 'GET', url = '/health', token, body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const r = http.request({ host: '127.0.0.1', port, method, path: url, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers } }, (res) => {
      let data = ''; res.on('data', (c) => { data += c; }); res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    r.on('error', reject); if (body) r.write(JSON.stringify(body)); r.end();
  });
}

let home; let bridge;
beforeEach(() => { home = fs.mkdtempSync(path.join(os.tmpdir(), 'jbridge-')); });
afterEach(() => { bridge?.stop(); fs.rmSync(home, { recursive: true, force: true }); });

const info = () => JSON.parse(fs.readFileSync(path.join(home, '.jaeger/run/vscode-bridge.json'), 'utf8'));

test('writes an owner-only bridge file with a fresh token on loopback', async () => {
  bridge = createBridge({ vscode: fakeVscode(), home });
  const port = await bridge.start();
  const f = path.join(home, '.jaeger/run/vscode-bridge.json');
  assert.equal(fs.statSync(f).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.dirname(f)).mode & 0o777, 0o700);
  const i = info(); assert.equal(i.port, port); assert.match(i.token, /^[0-9a-f]{64}$/);
  bridge.stop(); assert.equal(fs.existsSync(f), false);
  const b2 = createBridge({ vscode: fakeVscode(), home }); await b2.start();
  assert.notEqual(info().token, i.token, 'token is new each start'); b2.stop();
});

test('rejects missing/wrong tokens, foreign Host and browser Origin', async () => {
  bridge = createBridge({ vscode: fakeVscode(), home });
  const port = await bridge.start(); const { token } = info();
  assert.equal((await req(port)).status, 401);
  assert.equal((await req(port, { token: 'x'.repeat(64) })).status, 401);
  assert.equal((await req(port, { token, headers: { Host: `evil.example:${port}` } })).status, 403);
  assert.equal((await req(port, { token, headers: { Origin: 'https://evil.example' } })).status, 403);
  const ok = await req(port, { token }); assert.equal(ok.status, 200); assert.equal(JSON.parse(ok.body).vendor, 'copilot');
  const models = JSON.parse((await req(port, { token, url: '/models' })).body).models;
  assert.deepEqual(models.map((m) => m.id), ['gpt-5.6-luna']);
});

test('streams NDJSON deltas and token counts from vscode.lm', async () => {
  bridge = createBridge({ vscode: fakeVscode(), home });
  const port = await bridge.start(); const { token } = info();
  const r = await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } });
  const evs = r.body.trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(evs.map((e) => e.type), ['start', 'delta', 'delta', 'done']);
  assert.equal(evs.filter((e) => e.type === 'delta').map((e) => e.text).join(''), 'Hello');
  assert.equal(evs.at(-1).eval_count, 3); assert.equal(evs.at(-1).prompt_eval_count, 1); assert.equal(evs.at(-1).cost_usd, null);
  assert.equal((await req(port, { method: 'POST', url: '/chat', token, body: { model: 'nope', prompt: 'hi' } })).status, 404);
});

test('reports missing consent as needs_consent', async () => {
  bridge = createBridge({ vscode: fakeVscode({ fail: new LanguageModelError('no', 'NoPermissions') }), home });
  const port = await bridge.start(); const { token } = info();
  const r = await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } });
  const last = JSON.parse(r.body.trim().split('\n').at(-1));
  assert.equal(last.code, 'needs_consent');
  assert.equal(JSON.parse((await req(port, { token })).body).consent, 'needed');
  assert.equal(classify(fakeVscode(), new LanguageModelError('q', 'Blocked'))[0], 'quota');
});

test('client disconnect cancels the Copilot request; one per model at a time', async () => {
  const vs = fakeVscode({ chunks: ['a', 'b', 'c', 'd', 'e'], delay: 80 });
  bridge = createBridge({ vscode: vs, home });
  const port = await bridge.start(); const { token } = info();
  const r = http.request({ host: '127.0.0.1', port, method: 'POST', path: '/chat', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
  r.on('error', () => {});
  r.end(JSON.stringify({ model: 'gpt-5.6-luna', prompt: 'hi' }));
  await new Promise((res) => r.on('response', res));
  const busy = await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } });
  assert.equal(busy.status, 429);
  r.destroy();
  await new Promise((res) => setTimeout(res, 300));
  assert.equal(vs.calls.cancelled, 1);
});

test('rate limits to RATE_PER_MIN requests per minute', async () => {
  let t = 0;
  bridge = createBridge({ vscode: fakeVscode(), home, now: () => t });
  const port = await bridge.start(); const { token } = info();
  for (let i = 0; i < RATE_PER_MIN; i++) assert.equal((await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } })).status, 200);
  assert.equal((await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } })).status, 429);
  t = 61000;
  assert.equal((await req(port, { method: 'POST', url: '/chat', token, body: { model: 'gpt-5.6-luna', prompt: 'hi' } })).status, 200);
});
