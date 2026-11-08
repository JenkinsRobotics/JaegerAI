'use strict';
// The Copilot bridge writes ~/.jaeger/run/vscode-bridge.json. A dev host
// (Development), a test run (Test) or JAEGER_COPILOT_BRIDGE=off must never
// write it. HOME points at a temp dir, so the real ~/.jaeger is never used.
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');

const realHome = process.env.HOME;
const realState = process.env.JAEGER_STATE_DIR;
const realJaegerHome = process.env.JAEGER_HOME;
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'jaeger-bridge-home-'));
process.env.HOME = home;
process.env.JAEGER_STATE_DIR = path.join(home, '.jaeger');
process.env.JAEGER_HOME = path.join(home, '.jaeger');
after(() => {
  process.env.HOME = realHome;
  for (const [key,value] of [['JAEGER_STATE_DIR',realState],['JAEGER_HOME',realJaegerHome]]) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
  fs.rmSync(home, { recursive: true, force: true });
});
const root = path.join(__dirname, '..');
const ExtensionMode = { Production: 1, Development: 2, Test: 3 };

function inert() { const fn = function () { return inert(); }; return new Proxy(fn, { get: (t, k) => (k === 'dispose' ? () => {} : k === 'then' ? undefined : k === Symbol.toPrimitive ? () => '' : k in t ? t[k] : (t[k] = inert())) }); }
const lenient = o => new Proxy(o, { get: (t, k) => (k in t ? t[k] : (t[k] = inert())) });

async function activateIn(extensionMode) {
  const lines = [], subs = [];
  const vscode = lenient({
    ExtensionMode,
    lm: { selectChatModels: async () => [] },
    commands: lenient({ registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} }),
    chat: { createChatParticipant: () => ({ dispose() {} }) },
    window: lenient({ createOutputChannel: () => ({ appendLine: l => lines.push(l), show() {}, dispose() {} }) }),
    workspace: lenient({ getConfiguration: () => ({ get: (k, d) => d, inspect: () => ({}), update: async () => {} }), workspaceFolders: [] }),
    Uri: { joinPath: () => ({}), parse: s => ({ toString: () => s }), file: s => ({ fsPath: s }) },
  });
  const original = Module._load;
  Module._load = function (r, p, m) {
    if (r === 'vscode') return vscode;
    if (r === './contract.json') return { gatewayUrl: 'http://127.0.0.1:1' };
    return original.call(this, r, p, m);
  };
  for (const k of Object.keys(require.cache)) if (k.startsWith(root + path.sep) && !k.includes(`${path.sep}tests${path.sep}`)) delete require.cache[k];
  try {
    const ext = require(path.join(root, 'extension.js'));
    ext.activate({ extensionMode, subscriptions: { push: (...d) => subs.push(...d) }, extensionUri: {}, extensionPath: root,
      secrets: { get: async () => undefined, store: async () => {}, onDidChange: () => ({ dispose() {} }) },
      globalState: { get: () => undefined, update: async () => {} }, workspaceState: { get: () => undefined, update: async () => {} },
      globalStorageUri: { fsPath: path.join(home, 'storage') } });
    await new Promise(r => setTimeout(r, 300)); // bridge.start() is async
    const wrote = fs.existsSync(path.join(home, '.jaeger'));
    for (const d of subs) { try { d?.dispose?.(); } catch {} }
    ext.deactivate?.();
    return { lines, wrote };
  } finally { Module._load = original; }
}

for (const [name, mode] of [['Development', 2], ['Test', 3]]) {
  test(`${name} mode never writes under ~/.jaeger`, async () => {
    const { lines, wrote } = await activateIn(mode);
    assert.equal(wrote, false, `${home}/.jaeger was created`);
    assert.ok(lines.some(l => l.includes(`Copilot bridge off: extension mode ${name}`)), lines.join('\n'));
    assert.ok(!lines.some(l => /bridge listening/.test(l)));
  });
}

test('JAEGER_COPILOT_BRIDGE=off keeps an installed extension off ~/.jaeger', async () => {
  process.env.JAEGER_COPILOT_BRIDGE = 'off';
  try {
    const { lines, wrote } = await activateIn(1);
    assert.equal(wrote, false);
    assert.ok(lines.some(l => l.includes('Copilot bridge off: JAEGER_COPILOT_BRIDGE=off')));
  } finally { delete process.env.JAEGER_COPILOT_BRIDGE; }
});

test('control: an installed (Production) extension still publishes the bridge, in the temp HOME', async () => {
  const { wrote } = await activateIn(1);
  assert.equal(wrote, true, 'the positive control proves the check can see a write');
  fs.rmSync(path.join(home, '.jaeger'), { recursive: true, force: true });
});
