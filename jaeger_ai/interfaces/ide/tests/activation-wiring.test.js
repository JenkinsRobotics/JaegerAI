'use strict';
// The shipped entry (package.json "main") must activate the in-IDE chat: the
// conversation panel and one streaming @jaeger participant, alongside the
// controller sidebar and the Copilot bridge, without registering an id twice.
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

function activateEntry() {
  const commands = [], participants = [], views = [], bridge = [];
  const vscode = new Proxy({
    ExtensionMode: { Production: 1, Development: 2, Test: 3 },
    commands: { registerCommand: (id, fn) => { commands.push(id); return { dispose() {} }; }, executeCommand: async () => {} },
    chat: { createChatParticipant: (id, handler) => { const p = { id, handler, dispose() {} }; participants.push(p); return p; } },
    window: new Proxy({
      registerWebviewViewProvider: id => { views.push(id); return { dispose() {} }; },
      createOutputChannel: () => ({ appendLine() {}, show() {}, dispose() {} }),
    }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) }),
    workspace: new Proxy({
      getConfiguration: () => ({ get: () => undefined, inspect: () => ({}), update: async () => {} }),
      workspaceFolders: [],
    }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) }),
    Uri: { joinPath: (...parts) => ({ toString: () => parts.join('/') }), parse: s => ({ toString: () => s }), file: s => ({ fsPath: s }) },
  }, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) });
  const original = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') return vscode;
    if (request === './copilot-bridge') return { activateBridge: () => { bridge.push('activated'); } };
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
    return { api, commands, participants, views, bridge };
  } finally { Module._load = original; }
}

test('package.json main is extension.js and activates the chat panel view', () => {
  assert.equal(manifest.main, './extension.js');
  const { views } = activateEntry();
  assert.ok(views.includes('jaeger.conversation'), `chat panel view not registered: ${views}`);
  assert.ok(views.includes('jaeger.controller'), 'controller sidebar must stay registered');
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
  // jaeger.copilotBridge.* are registered by copilot-bridge.js, stubbed here.
  for (const { command } of manifest.contributes.commands.filter(c => !c.command.startsWith('jaeger.copilotBridge.'))) {
    assert.ok(commands.includes(command), `${command} contributed but not registered`);
  }
  for (const id of ['jaeger.open', 'jaeger.newConversation', 'jaeger.openSession', 'jaeger.setToken', 'jaeger.selectModel', 'jaeger.openChat', 'jaeger.ask']) {
    assert.ok(commands.includes(id), `${id} missing`);
  }
});

test('the controller and Copilot bridge keep working next to the panel', () => {
  const { api, bridge } = activateEntry();
  assert.ok(api.controller, 'controller returned from activate');
  assert.equal(typeof api.getGateway, 'function');
  assert.deepEqual(bridge, ['activated']);
});

test('the chat view is a visible "Chat" view and activates the extension', () => {
  const view = manifest.contributes.views.jaeger.find(v => v.id === 'jaeger.conversation');
  assert.equal(view.name, 'Chat');
  assert.notEqual(view.visibility, 'collapsed');
  assert.ok(manifest.activationEvents.includes('onView:jaeger.conversation'));
});
