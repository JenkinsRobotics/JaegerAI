'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');
const { resolveDefaultEndpoint } = require('../gateway');

const CURRENT = 'http://127.0.0.1:1';
const LEGACY = 'http://127.0.0.1:2';

test('current Gateway URL wins when it answers', async () => {
  const seen = [];
  const url = await resolveDefaultEndpoint({ gatewayUrl: CURRENT, legacyGatewayUrl: LEGACY },
    async u => { seen.push(u); return u === CURRENT; });
  assert.equal(url, CURRENT);
  assert.deepEqual(seen, [CURRENT]);
});

test('falls back to the legacy URL only when the current one is down', async () => {
  const url = await resolveDefaultEndpoint({ gatewayUrl: CURRENT, legacyGatewayUrl: LEGACY },
    async u => u === LEGACY);
  assert.equal(url, LEGACY);
});

test('neither answering keeps the current URL so errors name it', async () => {
  const url = await resolveDefaultEndpoint({ gatewayUrl: CURRENT, legacyGatewayUrl: LEGACY }, async () => false);
  assert.equal(url, CURRENT);
});

test('no legacy URL in the contract means no probing', async () => {
  let probed = false;
  const url = await resolveDefaultEndpoint({ gatewayUrl: CURRENT }, async () => { probed = true; return false; });
  assert.equal(url, CURRENT);
  assert.equal(probed, false);
});

test('default probe hits /health on a real loopback server', async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(req.url === '/health' ? 200 : 404, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const legacy = `http://127.0.0.1:${server.address().port}`;
  try {
    // Port 9 (discard) on loopback is closed on a normal host: the current URL is down.
    const url = await resolveDefaultEndpoint({ gatewayUrl: 'http://127.0.0.1:9', legacyGatewayUrl: legacy });
    assert.equal(url, legacy);
  } finally {
    server.close();
  }
});
