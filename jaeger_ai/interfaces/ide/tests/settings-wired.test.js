'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');

function fixture(settings = {}) {
  const events = [];
  let onChange;
  const item = { show: () => events.push('show'), hide: () => events.push('hide'), dispose() {} };
  const vscode = {
    workspace: {
      getConfiguration: () => ({ get: (key, fallback) => settings[key] ?? fallback }),
      onDidChangeConfiguration: fn => { onChange = fn; return { dispose() {} }; },
      workspaceFolders: [],
    },
    window: { createStatusBarItem: () => item },
    commands: { executeCommand: async (...args) => { events.push(['simple', ...args]); } },
    env: { openExternal: async uri => { events.push(['external', uri.value]); } },
    Uri: { parse: value => ({ value }) },
    ViewColumn: { Beside: 2 }, StatusBarAlignment: { Left: 1 },
    ThemeColor: class {}, Disposable: class { constructor(fn) { this.dispose = fn; } },
  };
  const filename = path.join(__dirname, '../controller.js');
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod.require = request => request === 'vscode' ? vscode : request === './gateway' ? { Gateway: class {}, GatewayError: Error }
    : require(request.startsWith('./') ? path.join(path.dirname(filename), request) : request);
  mod._compile(fs.readFileSync(filename, 'utf8'), filename);
  const sent = [];
  const gateway = { create: async () => ({ id: 'session' }), send: async (_id, body) => { sent.push(body); return {}; } };
  const controller = new mod.exports.JaegerController({ subscriptions: [] }, gateway);
  controller._startPolling = () => {};
  controller._connectEvents = () => {};
  controller.getWorkspaceContext = () => ({});
  return { controller, events, settings, sent, change: key => onChange({ affectsConfiguration: name => name === `jaeger.${key}` }) };
}

test('showStatusBar hides when disabled and responds to setting changes', () => {
  const f = fixture({ showStatusBar: false }); f.controller.activate();
  assert.deepEqual(f.events, ['hide']);
  f.settings.showStatusBar = true; f.change('showStatusBar');
  assert.deepEqual(f.events, ['hide', 'show']);
  f.settings.showStatusBar = false; f.change('showStatusBar');
  assert.deepEqual(f.events, ['hide', 'show', 'hide']);
});

test('openChatInBrowser opens externally without Simple Browser', async () => {
  const f = fixture({ openChatInBrowser: true });
  await f.controller.openChat();
  assert.deepEqual(f.events, [['external', 'http://127.0.0.1:8790/?ui=apple']]);
});

test('model setting reaches the Gateway turn body', async () => {
  const f = fixture({ model: 'ollama::test-model' });
  f.controller.openChat = async () => {};
  await f.controller.ask('hello');
  // The panel's picker stores provider::model; the Gateway takes them apart.
  assert.deepEqual([f.sent[0].provider, f.sent[0].model], ['ollama', 'test-model']);
  f.settings.model = 'plain-model';
  await f.controller.ask('plain');
  assert.deepEqual([f.sent[1].provider, f.sent[1].model], [undefined, 'plain-model']);
  f.settings.model = '';
  await f.controller.ask('again');
  assert.equal('model' in f.sent[2], false);
});

test('webuiUrl overrides derived chat URL for normal and session chat', async () => {
  const f = fixture({ webuiUrl: 'http://127.0.0.1:9999/base', openChatInBrowser: true });
  await f.controller.openChat();
  await f.controller.openChatSession('abc');
  assert.deepEqual(f.events, [
    ['external', 'http://127.0.0.1:9999/base/?ui=apple'],
    ['external', 'http://127.0.0.1:9999/base/chat?session=abc'],
  ]);
  await f.controller.openChatSession('agent-native:jaeger');
  assert.equal(f.events.at(-1)[1], 'http://127.0.0.1:9999/base/chat?session=agent-native%3Ajaeger');
});

test('copilotBridge.enabled starts and stops bridge on configuration change', () => {
  const { activateBridge } = require('../copilot-bridge');
  let enabled = true, onChange;
  const calls = [];
  const vscode = {
    lm: { selectChatModels() {} },
    workspace: {
      getConfiguration: () => ({ get: () => enabled }),
      onDidChangeConfiguration: fn => { onChange = fn; return { dispose() {} }; },
    },
    commands: { registerCommand: () => ({ dispose() {} }) },
  };
  const context = { subscriptions: [] };
  activateBridge(vscode, context, () => {}, () => ({ start: () => { calls.push('start'); return Promise.resolve(); }, stop: () => calls.push('stop') }));
  enabled = false; onChange({ affectsConfiguration: key => key === 'jaeger.copilotBridge' });
  enabled = true; onChange({ affectsConfiguration: key => key === 'jaeger.copilotBridge' });
  assert.deepEqual(calls, ['start', 'stop', 'start']);
});
