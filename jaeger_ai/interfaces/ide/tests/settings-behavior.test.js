'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

// Load the controller extension with only VS Code, Gateway, and bridge fakes.
function activateWith(settings) {
  const original = Module._load;
  const commands = new Map();
  const vscode = {
    workspace: { getConfiguration: () => ({ get: key => settings[key] }) },
    window: { createOutputChannel: () => ({ appendLine() {}, dispose() {} }), registerWebviewViewProvider: () => ({ dispose() {} }) },
    languages: { registerCodeActionsProvider: () => ({ dispose() {} }), registerInlineCompletionItemProvider: () => ({ dispose() {} }) },
    CodeActionKind: { QuickFix: {}, Refactor: {}, RefactorRewrite: {}, RefactorExtract: {} },
    chat: { createChatParticipant: () => ({ dispose() {} }) },
    Uri: { joinPath: () => ({}) },
    commands: { registerCommand: (name, fn) => { commands.set(name, fn); return { dispose() {} }; } },
  };
  class Gateway {
    constructor(url, options) { this.url = url; this.options = options; }
    auth() { const value = this.options.token('ide'); return { Authorization: `Bearer ${value}` }; }
  }
  class Controller { constructor(_context, gateway) { this.gateway = gateway; } activate() {} dispose() {} }
  const extensionPath = require.resolve('../extension');
  delete require.cache[extensionPath];
  Module._load = function(request, parent, isMain) {
    if (parent?.filename === extensionPath) {
      if (request === 'vscode') return vscode;
      if (request === './gateway') return { Gateway, GatewayError: Error, callerToken: () => 'fallback-token' };
      if (request === './controller') return { JaegerController: Controller, JaegerCodeActionProvider: class {}, JaegerInlineCompletionsProvider: class {}, JaegerSidebarProvider: class {} };
      if (request === './copilot-bridge') return { activateBridge() {} };
    }
    return original.call(this, request, parent, isMain);
  };
  try { return { ...require('../extension').activate({ subscriptions: { push() {} } }), commands }; }
  finally { Module._load = original; delete require.cache[extensionPath]; }
}

test('gatewayUrl selects the Gateway client endpoint', () => {
  assert.equal(activateWith({ gatewayUrl: 'http://127.0.0.1:4455' }).getGateway().url, 'http://127.0.0.1:4455');
  assert.equal(activateWith({ gatewayUrl: '' }).getGateway().url, 'http://127.0.0.1:33418');
});

test('callerToken changes the authorization header synchronously', () => {
  const configured = activateWith({ callerToken: 'fixture-token' }).getGateway().auth();
  const fallback = activateWith({ callerToken: '' }).getGateway().auth();
  assert.deepEqual(configured, { Authorization: 'Bearer fixture-token' });
  assert.deepEqual(fallback, { Authorization: 'Bearer fallback-token' });
});
