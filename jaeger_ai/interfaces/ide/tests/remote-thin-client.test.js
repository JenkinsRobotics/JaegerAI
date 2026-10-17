'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const { localEndpoint, isAllowedGatewayHost, callerToken } = require('../gateway');
const {
  selectableModels, groupSelectableModels, parseProviderModel, providerModelValue, modelSelectionLabel,
} = require('../media/presentation');
const { Conversation } = require('../conversation');

// ── 1. Configuration scopes and separation of endpoint / model ─────────────

test('package.json excludes machine connection settings from sync while model remains eligible', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  const props = pkg.contributes.configuration.properties;

  // gatewayUrl is a per-device connection setting and must NOT be blindly synced across devices
  assert.equal(props['jaeger.gatewayUrl'].scope, 'machine');

  // A legacy fallback must not accidentally enter a settings-sync payload.
  assert.equal(props['jaeger.callerToken'].scope, 'machine');

  // jaeger.model is syncable across devices (window scope in VS Code)
  assert.equal(props['jaeger.model'].scope, 'window');
});

test('gateway endpoint accepts loopback and secure Tailscale / private LAN hosts without credential or path ambiguity', () => {
  // Loopback
  assert.equal(localEndpoint('http://127.0.0.1:33418'), 'http://127.0.0.1:33418');
  assert.equal(localEndpoint('http://localhost:33418'), 'http://localhost:33418');

  // Tailscale MagicDNS (*.ts.net)
  assert.equal(localEndpoint('http://home-mac.ts.net:33418'), 'http://home-mac.ts.net:33418');
  assert.equal(localEndpoint('http://laptop.tailnet-xyz.ts.net:33418'), 'http://laptop.tailnet-xyz.ts.net:33418');
  assert.equal(localEndpoint('https://home-mac.ts.net:8443'), 'https://home-mac.ts.net:8443');

  // Tailscale IPv4 CGNAT (100.64.0.0/10)
  assert.equal(localEndpoint('http://100.85.12.34:33418'), 'http://100.85.12.34:33418');

  // Local network names / mDNS
  assert.equal(localEndpoint('http://home-mac.local:33418'), 'http://home-mac.local:33418');
  assert.equal(localEndpoint('http://home-mac:33418'), 'http://home-mac:33418');

  // Rejections: credentials, paths, query params, public domains
  assert.throws(() => localEndpoint('http://user:pass@127.0.0.1:33418'), /credentials/i);
  assert.throws(() => localEndpoint('http://home-mac.ts.net:33418/path'), /path/i);
  assert.throws(() => localEndpoint('http://home-mac.ts.net:33418/?q=1'), /query/i);
  assert.throws(() => localEndpoint('http://example.org'), /Public domains/i);
  assert.throws(() => localEndpoint('https://api.github.com'), /Public domains/i);
});

test('separation of endpoint and model: changing endpoint preserves model choice', () => {
  const model = 'ollama-cloud::phi4:cloud';
  const parsed = parseProviderModel(model);
  assert.deepEqual(parsed, { provider: 'ollama-cloud', model: 'phi4:cloud' });

  // Parsing @provider:model syntax
  assert.deepEqual(parseProviderModel('@ollama-cloud:glm-5.3-flash:cloud'), {
    provider: 'ollama-cloud',
    model: 'glm-5.3-flash:cloud',
  });

  // Empty model preserves empty (Gateway default)
  assert.deepEqual(parseProviderModel(''), { provider: '', model: '' });
});

// ── 2. Dynamic runtime model catalog including Ollama Cloud-shaped entries ─

test('selectableModels dynamically extracts Ollama Cloud models without hardcoded IDs', () => {
  // Shape A: providers array with ollama-cloud provider
  const catalogA = {
    providers: [
      {
        id: 'ollama-cloud',
        display_name: 'Ollama Cloud',
        reachable: true,
        models: [
          { id: 'server-custom-cloud-1:cloud', available: true },
          { id: 'server-custom-cloud-2:cloud', available: true },
          { id: 'offline-cloud-model', available: false },
        ],
      },
      {
        id: 'ollama',
        display_name: 'Ollama',
        reachable: true,
        models: [
          { id: 'local-model-1', available: true },
          { id: 'cloud-tagged-model:cloud', available: true, remote_host: 'cloud' },
        ],
      },
      {
        id: 'unreachable-provider',
        reachable: false,
        models: [{ id: 'hidden-model', available: true }],
      },
    ],
  };

  const rowsA = selectableModels(catalogA);
  // Offline and unreachable models are excluded
  assert.equal(rowsA.some(r => r.id === 'offline-cloud-model'), false);
  assert.equal(rowsA.some(r => r.id === 'hidden-model'), false);

  // Available cloud models are included
  assert.equal(rowsA.some(r => r.provider === 'ollama-cloud' && r.id === 'server-custom-cloud-1:cloud'), true);
  assert.equal(rowsA.some(r => r.provider === 'ollama-cloud' && r.id === 'server-custom-cloud-2:cloud'), true);
  assert.equal(rowsA.some(r => r.provider === 'ollama-cloud' && r.id === 'cloud-tagged-model:cloud'), true);

  // Groups grouping preservation
  const groupsA = groupSelectableModels(rowsA);
  assert.ok(groupsA.has('Ollama Cloud'));
  assert.ok(groupsA.has('Ollama'));

  // Shape B: canonical / WebUI groups shape with Ollama Cloud
  const catalogB = {
    webui_catalog: {
      groups: [
        {
          provider: 'Ollama Cloud',
          provider_id: 'ollama-cloud',
          status: 'online',
          models: [
            { id: '@ollama-cloud:dynamic-model-xyz', name: 'dynamic-model-xyz', available: true },
          ],
        },
        {
          provider: 'Offline Provider',
          status: 'unavailable',
          models: [{ id: 'offline-model', available: true }],
        },
      ],
    },
  };

  const rowsB = selectableModels(catalogB);
  assert.equal(rowsB.length, 1);
  assert.equal(rowsB[0].provider, 'ollama-cloud');
  assert.equal(rowsB[0].id, '@ollama-cloud:dynamic-model-xyz');
});

// ── 3. Explicit unavailable/auth error surfacing ───────────────────────────

test('authentication failure (401/403) surfaces clear actionable error without silent fallback', async () => {
  const fakeGateway = {
    url: 'http://127.0.0.1:33418',
    auth() { return { Authorization: 'Bearer invalid' }; },
    async json() {
      const err = new Error('Gateway rejected credentials');
      err.status = 401;
      throw err;
    },
    async sessions() { throw new Error('Unreachable'); },
  };

  const conv = new Conversation(fakeGateway, () => {}, async () => {});
  await conv.refresh();

  assert.equal(conv.state.connected, false);
  assert.equal(conv.state.status, 'Authentication required');
  assert.match(conv.state.error, /Gateway authentication failed \(401\)/);
  assert.match(conv.state.error, /Jaeger: Set Caller Token/);
  // Reconnect timer is cancelled on auth error to prevent endless loops
  assert.equal(conv.reconnectTimer, null);
});

test('turn admission auth rejection surfaces clear authentication error', async () => {
  const fakeGateway = {
    url: 'http://127.0.0.1:33418',
    auth() { return {}; },
    async create() { return { session_id: 's-1' }; },
    async send() {
      const err = new Error('Unauthorized');
      err.status = 403;
      throw err;
    },
    async session() { return { session_id: 's-1', messages: [] }; },
    async persist() {},
  };

  const conv = new Conversation(fakeGateway, () => {}, async () => {});
  conv.state.connected = true;
  conv.state.session = { session_id: 's-1', messages: [] };

  await conv.send('Hello with invalid token');
  assert.equal(conv.state.status, 'Authentication required');
  assert.match(conv.state.error, /Gateway authentication failed \(403\)/);
  assert.equal(conv.state.busy, false);
});

// ── 4. Capability handshake, status lines, and settings scopes ─────────────

test('statusLines formats capabilities, permissions, health, and scopes cleanly', () => {
  const { statusLines } = require('../commands');
  const lines = statusLines({
    version: { component: 'jaeger-gateway', version: '0.13.0' },
    endpoint: 'http://home-mac.ts.net:33418',
    model: 'ollama-cloud::synthetic-cloud-model:cloud',
    session: { title: 'Refactor auth', messages: [{}, {}], workspace: '/remote/workspace', status: 'idle' },
    autonomy: 'auto',
    tier: 'agent',
    capabilities: { audio: { available: true }, vision: { available: true }, frameworks: { available: true } },
    connectionHealth: 'connected (remote Tailscale/LAN)',
    scopes: true,
  });

  assert.ok(lines.some(l => l.includes('Gateway: jaeger-gateway 0.13.0')));
  assert.ok(lines.some(l => l.includes('Endpoint: http://home-mac.ts.net:33418')));
  assert.ok(lines.some(l => l.includes('Model: ollama-cloud::synthetic-cloud-model:cloud')));
  assert.ok(lines.some(l => l.includes('Connection: connected (remote Tailscale/LAN)')));
  assert.ok(lines.some(l => l.includes('Permissions: Autonomy: auto · Tier: agent')));
  assert.ok(lines.some(l => l.includes('Capabilities: Audio, Vision, Frameworks')));
  assert.ok(lines.some(l => l.includes('Scopes: Endpoint & token are machine-specific')));
});

test('Gateway.capabilities() calls /v1/runtime/capabilities', async () => {
  const { Gateway } = require('../gateway');
  let requestedPath = '';
  const gw = new Gateway('http://127.0.0.1:33418');
  gw.json = async path => { requestedPath = path; return { frameworks: { available: true } }; };
  const res = await gw.capabilities();
  assert.equal(requestedPath, '/v1/runtime/capabilities');
  assert.equal(res.frameworks.available, true);
});

test('onboarding guidance truthfully specifies zero local models and Settings Sync boundaries', () => {
  const extSource = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  // Thin client: zero local models downloaded or executed
  assert.match(extSource, /Zero local models are downloaded, installed, or executed/);
  // Remote execution: all models run on or are accessed by remote server
  assert.match(extSource, /All models.*run on or are accessed by your remote server/);
  // Settings sync: machine-scoped endpoint and SecretStorage are not synced
  assert.match(extSource, /machine-scoped Gateway endpoint and caller-token fallback are not synced/);
  assert.match(extSource, /SecretStorage is encrypted and not synced across machines/);
  // VSIX: does not auto-install everywhere
  assert.match(extSource, /Do not assume a private\/local VSIX installs on another device/);
});

test('endpoint changes do not reuse or leak credentials across unrelated servers', async () => {
  const secrets = new Map();
  const mockSecrets = {
    async get(key) { return secrets.get(key) || ''; },
    async store(key, val) { secrets.set(key, val); },
    async delete(key) { secrets.delete(key); },
  };

  let currentEndpoint = 'http://server-alpha.ts.net:33418';
  const getStoredCallerToken = async () => {
    const ep = currentEndpoint;
    const scopedSecret = await mockSecrets.get(`jaeger.callerToken:${ep}`);
    if (scopedSecret) return scopedSecret;
    const paired = await mockSecrets.get('jaeger.pairedEndpoint');
    if (paired && paired !== ep) return '';
    return mockSecrets.get('jaeger.callerToken') || '';
  };

  // Pair server-alpha with a secret token
  await mockSecrets.store('jaeger.callerToken', 'alpha-secret-token');
  await mockSecrets.store('jaeger.callerToken:http://server-alpha.ts.net:33418', 'alpha-secret-token');
  await mockSecrets.store('jaeger.pairedEndpoint', 'http://server-alpha.ts.net:33418');

  // Verify server-alpha retrieves its paired token
  assert.equal(await getStoredCallerToken(), 'alpha-secret-token');

  // Now change endpoint to server-beta: must NOT return alpha's token
  currentEndpoint = 'http://server-beta.ts.net:33418';
  assert.equal(await getStoredCallerToken(), '', 'unrelated server must not receive alpha token');

  // Explicitly pair server-beta
  await mockSecrets.store('jaeger.callerToken:http://server-beta.ts.net:33418', 'beta-secret-token');
  assert.equal(await getStoredCallerToken(), 'beta-secret-token');
});



