'use strict';
// jaeger.gatewayUrl written as <origin>/v1 or <origin>/v1/ means the same Gateway.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Gateway, localEndpoint, normalizeGatewayUrl } = require('../gateway');

test('/v1 and /v1/ normalize to the origin the client expects', () => {
  for (const value of ['http://127.0.0.1:43418/v1', 'http://127.0.0.1:43418/v1/', 'http://127.0.0.1:43418/', 'http://127.0.0.1:43418', ' http://127.0.0.1:43418/v1 ']) {
    assert.equal(normalizeGatewayUrl(value), 'http://127.0.0.1:43418', value);
    assert.equal(localEndpoint(value), 'http://127.0.0.1:43418', value);
  }
  assert.equal(new Gateway('http://localhost:33418/v1/').url, 'http://localhost:33418');
});

test('other paths, queries and credentials are still refused', () => {
  assert.throws(() => localEndpoint('http://127.0.0.1:43418/v2'), /must not contain a path/);
  assert.throws(() => localEndpoint('http://127.0.0.1:43418/v1/sessions'), /must not contain a path/);
  assert.throws(() => localEndpoint('http://127.0.0.1:43418/v1?x=1'), /query string/);
  assert.throws(() => localEndpoint('http://u:p@127.0.0.1:43418/v1'), /credentials/);
  assert.throws(() => localEndpoint('https://example.com/v1'), /Public domains/);
});

test('the shipped entry activates with a /v1 gatewayUrl (no "must not contain a path")', () => {
  const Module = require('node:module'); const path = require('node:path');
  const root = path.join(__dirname, '..');
  function inert() { const fn = function () { return inert(); }; return new Proxy(fn, { get: (t, k) => (k === 'dispose' ? () => {} : k === 'then' ? undefined : k === Symbol.toPrimitive ? () => '' : k in t ? t[k] : (t[k] = inert())) }); }
  const lenient = o => new Proxy(o, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) });
  const cfg = { gatewayUrl: 'http://127.0.0.1:43418/v1' };
  const vscode = lenient({
    ExtensionMode: { Production: 1, Development: 2, Test: 3 },
    commands: lenient({ registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} }),
    chat: { createChatParticipant: () => ({ dispose() {} }) },
    window: lenient({ createOutputChannel: () => ({ appendLine() {}, show() {}, dispose() {} }) }),
    workspace: lenient({ getConfiguration: () => ({ get: (k, d) => cfg[k] ?? d, inspect: () => ({}), update: async () => {} }), workspaceFolders: [] }),
    Uri: { joinPath: () => ({}), parse: s => ({ toString: () => s }), file: s => ({ fsPath: s }) },
  });
  const original = Module._load;
  Module._load = function (r, p, m) { return r === 'vscode' ? vscode : original.call(this, r, p, m); };
  for (const k of Object.keys(require.cache)) if (k.startsWith(root + path.sep) && !k.includes(`${path.sep}tests${path.sep}`)) delete require.cache[k];
  try {
    const ext = require(path.join(root, 'extension.js'));
    const api = ext.activate({ extensionMode: 2, subscriptions: { push() {} }, extensionUri: {}, extensionPath: root,
      secrets: { get: async () => undefined, store: async () => {}, onDidChange: () => ({ dispose() {} }) },
      globalState: { get: () => undefined, update: async () => {} }, workspaceState: { get: () => undefined, update: async () => {} },
      globalStorageUri: { fsPath: require('node:os').tmpdir() } });
    assert.equal(api.getGateway().url, 'http://127.0.0.1:43418');
    ext.deactivate?.();
  } finally { Module._load = original; }
});
