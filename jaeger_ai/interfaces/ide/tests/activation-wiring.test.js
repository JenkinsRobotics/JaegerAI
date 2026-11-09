'use strict';
// The shipped entry (package.json "main") must activate the in-IDE chat: the
// conversation panel and one streaming @jaeger participant, alongside the
// controller sidebar and native Gateway model, without registering an id twice.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

const root = path.join(__dirname, '..');
const manifest = require('../package.json');

// Any API the test does not care about is a no-op that returns a disposable.
function inert() {
  const fn = function () { return inert(); };
  return new Proxy(fn, {
    get: (target, key) => (key === 'dispose' ? () => {} : key === 'then' ? undefined
      : key === Symbol.toPrimitive ? () => '' : key in target ? target[key] : (target[key] = inert())),
  });
}

function activateEntry(appName = 'Visual Studio Code') {
  const commands = [], participants = [], views = [], executed = [];
  const vscode = new Proxy({
    ExtensionMode: { Production: 1, Development: 2, Test: 3 },
    commands: { registerCommand: (id, fn) => { commands.push(id); return { dispose() {} }; }, executeCommand: async (...args) => { executed.push(args); } },
    chat: { createChatParticipant: (id, handler) => { const p = { id, handler, dispose() {} }; participants.push(p); return p; } },
    window: new Proxy({
      registerWebviewViewProvider: id => { views.push(id); return { dispose() {} }; },
      createOutputChannel: () => ({ appendLine() {}, show() {}, dispose() {} }),
    }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) }),
    workspace: new Proxy({
      getConfiguration: () => ({ get: () => undefined, inspect: () => ({}), update: async () => {} }),
      workspaceFolders: [],
    }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) }),
    env: { appName },
    Uri: { joinPath: (...parts) => ({ toString: () => parts.join('/') }), parse: s => ({ toString: () => s }), file: s => ({ fsPath: s }) },
  }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) });
  const original = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return vscode;
    if (request === './contract.json') return { gatewayUrl: 'http://127.0.0.1:1' };
    return original.call(this, request, parent, isMain);
  };
  const cached = Object.keys(require.cache).filter(k => k.startsWith(root + path.sep) && !k.includes(`${path.sep}tests${path.sep}`));
  cached.forEach(k => delete require.cache[k]);
  try {
    const entry = require(path.join(root, manifest.main));
    const api = entry.activate({ extensionMode: 1, subscriptions: { push() {} }, extensionUri: { toString: () => 'ext' }, extensionPath: root,
      secrets: { get: async () => undefined, store: async () => {}, onDidChange: () => ({ dispose() {} }) },
      globalState: { get: () => undefined, update: async () => {} }, workspaceState: { get: () => undefined, update: async () => {} },
      globalStorageUri: { fsPath: path.join(require('node:os').tmpdir(), 'jaeger-wiring-test') } });
    entry.deactivate?.();
    return { api, commands, participants, views, executed };
  } finally { Module._load = original; }
}

test('package.json main is extension.js and keeps the chat panel in ordinary VS Code', () => {
  assert.equal(manifest.main, './extension.js');
  const { views } = activateEntry();
  assert.ok(views.includes('jaeger.conversation'), `chat panel view not registered: ${views}`);
  assert.ok(views.includes('jaeger.controller'), 'controller sidebar must stay registered');
});

test('Jaeger Desktop uses native Chat without registering the duplicate conversation webview', () => {
  const { views, executed } = activateEntry('Jaeger Desktop');
  assert.ok(views.includes('jaeger.controller'), 'Jaeger status view must stay registered');
  assert.ok(!views.includes('jaeger.conversation'), `duplicate chat panel registered: ${views}`);
  assert.ok(executed.some(args => args[0] === 'setContext' && args[1] === 'jaeger.nativeChat' && args[2] === true));
});

test('exactly one @jaeger participant, the streaming one, with follow-ups', () => {
  const { participants } = activateEntry();
  const jaeger = participants.filter(p => p.id === 'jaeger.chatParticipant');
  assert.equal(jaeger.length, 1, 'duplicate chat participant registration');
  assert.equal(typeof jaeger[0].followupProvider?.provideFollowups, 'function');
  assert.deepEqual(jaeger[0].followupProvider.provideFollowups({ metadata: { jaegerFollowUps: ['Next?'] } }), [{ prompt: 'Next?', label: 'Next?' }]);
});

test('no command id is registered twice and every contributed command is registered', () => {
  const { commands } = activateEntry();
  const dupes = commands.filter((id, i) => commands.indexOf(id) !== i);
  assert.deepEqual(dupes, [], `registered twice: ${dupes}`);
  for (const { command } of manifest.contributes.commands) {
    assert.ok(commands.includes(command), `${command} contributed but not registered`);
  }
  for (const id of ['jaeger.open', 'jaeger.newConversation', 'jaeger.openSession', 'jaeger.setToken', 'jaeger.selectModel', 'jaeger.openChat', 'jaeger.ask']) {
    assert.ok(commands.includes(id), `${id} missing`);
  }
});

test('the controller and Gateway model keep working next to the panel', () => {
  const { api } = activateEntry();
  assert.ok(api.controller, 'controller returned from activate');
  assert.equal(typeof api.getGateway, 'function');
});

test('the chat view is a visible "Chat" view and activates the extension', () => {
  const view = manifest.contributes.views.jaeger.find(v => v.id === 'jaeger.conversation');
  assert.equal(view.name, 'Chat');
  assert.notEqual(view.visibility, 'collapsed');
  assert.equal(view.when, '!jaeger.nativeChat');
  assert.ok(manifest.activationEvents.includes('onView:jaeger.conversation'));
});
