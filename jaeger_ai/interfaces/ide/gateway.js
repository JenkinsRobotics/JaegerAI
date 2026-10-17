'use strict';

// Transport only. Never starts a runtime or opens an application database.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

// The IDE is the Gateway's `ide` caller. Its token can be provided via settings,
// JAEGER_CALLER_TOKEN / JAEGER_IDE_TOKEN, ~/.jaeger/caller_tokens/ide.token (0600),
// JAEGER_CALLER_TOKEN_DIR, or the macOS Keychain (service ai.jaeger.gateway.caller).
const KEYCHAIN_SERVICE = 'ai.jaeger.gateway.caller';
let cachedToken = null;
function callerToken(caller = 'ide', customToken = '') {
  if (typeof customToken === 'string' && customToken.trim()) return customToken.trim();
  if (cachedToken && Date.now() - cachedToken.at < 30000) return cachedToken.value;
  let value = '';
  try {
    if (process.env.JAEGER_CALLER_TOKEN || process.env.JAEGER_IDE_TOKEN) {
      value = (process.env.JAEGER_CALLER_TOKEN || process.env.JAEGER_IDE_TOKEN).trim();
    }
    if (!value) {
      const candidateDirs = [];
      if (process.env.JAEGER_CALLER_TOKEN_DIR) candidateDirs.push(process.env.JAEGER_CALLER_TOKEN_DIR);
      const home = process.env.HOME || process.env.USERPROFILE || '';
      if (home) {
        candidateDirs.push(path.join(home, '.jaeger', 'caller_tokens'));
        candidateDirs.push(path.join(home, '.jaeger', 'tokens'));
      }
      for (const dir of candidateDirs) {
        const file = path.join(dir, `${caller}.token`);
        if (fs.existsSync(file)) {
          try {
            const content = fs.readFileSync(file, 'utf8').trim();
            if (content) { value = content; break; }
          } catch (_) {}
        }
      }
    }
    if (!value && process.platform === 'darwin') {
      value = execFileSync('/usr/bin/security', ['find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', caller, '-w'],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 }).trim();
    }
  } catch (_) { value = ''; }
  cachedToken = value ? { value, at: Date.now() } : null;
  return value;
}

class GatewayError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

function isAllowedGatewayHost(hostname) {
  const host = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (['localhost', '127.0.0.1', '::1'].includes(host)) return true;
  // Tailscale MagicDNS hostnames (e.g. *.ts.net)
  if (host.endsWith('.ts.net')) return true;
  // Local network / mDNS names (e.g. *.local or single-label hostnames like "home-mac")
  if (host.endsWith('.local') || !host.includes('.')) return true;
  // Tailscale IPv4 CGNAT (100.64.0.0/10)
  const ip4 = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (ip4) {
    const b0 = Number(ip4[1]), b1 = Number(ip4[2]);
    if (b0 === 100 && b1 >= 64 && b1 <= 127) return true; // Tailscale
    if (b0 === 10 || (b0 === 172 && b1 >= 16 && b1 <= 31) || (b0 === 192 && b1 === 168)) return true; // Private LAN
  }
  // Tailscale IPv6 ULA (fd7a:115c:a1e0::/48) or link-local IPv6
  if (host.startsWith('fd7a:115c:a1e0:') || host.startsWith('fe80:')) return true;
  return false;
}

function localEndpoint(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('Gateway URL must use http: or https:');
  }
  if (url.username || url.password) {
    throw new Error('Do not put credentials in the Gateway URL. Use the secure token store or jaeger.setToken.');
  }
  if (url.search || url.hash) {
    throw new Error('Gateway URL must not contain a query string or hash.');
  }
  if (url.pathname !== '/' && url.pathname !== '') {
    throw new Error('Gateway URL must not contain a path.');
  }
  if (!isAllowedGatewayHost(url.hostname)) {
    throw new Error('Use a local loopback (localhost/127.0.0.1) or secure Tailscale/LAN host for the Gateway URL. Public domains are not allowed.');
  }
  return url.origin;
}

// VS Code extension hosts may install a proxy-aware global fetch. For a local
// Gateway that proxy layer is unnecessary and can leave loopback requests
// pending even though the endpoint is healthy. Keep fetch as the default and
// let the extension explicitly opt into Node's direct loopback transport.
function nativeRequest(urlValue, options = {}) {
  const url = new URL(urlValue);
  const transport = url.protocol === 'https:' ? https : http;
  const body = options.body;
  const headers = { ...(options.headers || {}) };
  if (body !== undefined && body !== null && !headers['Content-Length']) {
    headers['Content-Length'] = Buffer.byteLength(body);
  }
  return new Promise((resolve, reject) => {
    const request = transport.request({
      protocol: url.protocol, hostname: url.hostname, port: url.port || undefined,
      path: `${url.pathname}${url.search}`, method: options.method || 'GET', headers,
      signal: options.signal,
    }, response => {
      const result = {
        status: response.statusCode || 0,
        ok: (response.statusCode || 0) >= 200 && (response.statusCode || 0) < 300,
        body: response,
        async json() {
          const chunks = [];
          for await (const chunk of response) chunks.push(chunk);
          return JSON.parse(Buffer.concat(chunks).toString('utf8'));
        },
      };
      resolve(result);
    });
    request.once('error', reject);
    if (body !== undefined && body !== null) request.write(body);
    request.end();
  });
}

// Handles network chunk boundaries, UTF-8, CRLF and multiline SSE data.
async function* decodeSSE(body) {
  const decoder = new TextDecoder();
  let buffer = '', data = [], name = 'message', id = '';
  for await (const chunk of body) {
    buffer += decoder.decode(chunk, { stream: true });
    if (buffer.length > 8 * 1024 * 1024) throw new Error('Gateway event exceeds client limit');
    let newline;
    while ((newline = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newline).replace(/\r$/, '');
      buffer = buffer.slice(newline + 1);
      if (!line) {
        if (data.length) yield { name, id, payload: JSON.parse(data.join('\n')) };
        data = []; name = 'message'; id = '';
      } else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      else if (line.startsWith('event:')) name = line.slice(6).trim();
      else if (line.startsWith('id:')) id = line.slice(3).trim();
    }
  }
  // An incomplete frame is not a terminal event. The caller checks the receipt.
}

class Gateway {
  constructor(url, options = {}) {
    this.url = localEndpoint(url);
    const custom = options.callerToken || '';
    this.token = typeof options.token === 'function' ? options.token : (caller => callerToken(caller, custom));
    this.nativeLoopback = options.nativeLoopback === true;
  }
  auth() {
    const token = this.token('ide');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  async json(path, body, method) {
    const requestOptions = {
      method: method || (body === undefined ? 'GET' : 'POST'), redirect: 'error',
      headers: { 'Content-Type': 'application/json', ...this.auth() },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    };
    const response = this.nativeLoopback
      ? await nativeRequest(this.url + path, requestOptions)
      : await fetch(this.url + path, requestOptions);
    const result = await response.json();
    if (!response.ok) throw new GatewayError(String(result.error || `Gateway HTTP ${response.status}`), response.status);
    return result;
  }
  tasks() { return this.json('/v1/tasks'); }
  rename(id, title) { return this.json(`/v1/sessions/${encodeURIComponent(id)}`, { title }, 'PATCH'); }
  archive(id, archived) { return this.json(`/v1/sessions/${encodeURIComponent(id)}`, { archived }, 'PATCH'); }
  branch(id, body = {}) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/branch`, body); }
  feedback(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/feedback`, body); }
  feedbacks(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/feedback`); }
  retry(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/retry`, {}); }
  ideResult(id, ideRequestId, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/ide/${encodeURIComponent(ideRequestId)}`, body); }
  autonomy() { return this.json('/v1/runtime/autonomy'); }
  setAutonomy(autonomy) { return this.json('/v1/runtime/autonomy', { autonomy }); }
  tier() { return this.json('/v1/runtime/tier'); }
  setTier(tier) { return this.json('/v1/runtime/tier', { tier }); }
  skills(query = '') { return this.json(`/v1/runtime/skills${query ? `?q=${encodeURIComponent(query)}` : ''}`); }
  cancelTask(id) { return this.json(`/v1/tasks/${encodeURIComponent(id)}/cancel`, {}); }
  sessions(query = '') { return this.json(`/v1/sessions${query ? `?q=${encodeURIComponent(query)}` : ''}`); }
  session(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}`); }
  activity(id, after = 0) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/activity?after=${after}`); }
  create(body) { return this.json('/v1/sessions', body); }
  send(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/turns`, body); }
  queue(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/queue`); }
  queueAdd(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/queue`, body); }
  queueReorder(id, order) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/queue/reorder`, { order }); }
  queueUpdate(id, rid, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/queue/${encodeURIComponent(rid)}`, body, 'PATCH'); }
  queueDelete(id, rid) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/queue/${encodeURIComponent(rid)}`, undefined, 'DELETE'); }
  receipt(id, rid) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/requests/${encodeURIComponent(rid)}`); }
  cancel(id, rid) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/cancel`, { request_id: rid }); }
  steer(id, rid, text) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/requests/${encodeURIComponent(rid)}/steer`, { text }); }
  approvals() { return this.json('/v1/approvals'); }
  approve(id, approved) { return this.json(`/v1/approvals/${encodeURIComponent(id)}`, { approved }); }
  attachments(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/attachments`); }
  addAttachment(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/attachments`, body); }
  // The Gateway's real provider/model catalog — never a hardcoded picker list.
  models() { return this.json('/v1/runtime/models'); }
  capabilities() { return this.json('/v1/runtime/capabilities'); }
  orchestrationWorkers() { return this.json('/v1/orchestration/workers'); }
  orchestrationSubmit(body) { return this.json('/v1/orchestration/tasks', body); }
  orchestrationTask(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}`); }
  orchestrationFollowUp(id, body) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}/follow-up`, body); }
  orchestrationCancel(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}/cancel`, {}); }

  async *events(id, cursor, signal) {
    const requestOptions = {
      headers: { Accept: 'text/event-stream', ...this.auth() }, signal, redirect: 'error',
    };
    const response = this.nativeLoopback
      ? await nativeRequest(`${this.url}/v1/sessions/${encodeURIComponent(id)}/stream?last_event_id=${cursor}`, requestOptions)
      : await fetch(`${this.url}/v1/sessions/${encodeURIComponent(id)}/stream?last_event_id=${cursor}`, requestOptions);
    if (!response.ok) {
      await response.body?.cancel();
      throw new GatewayError(`Event stream HTTP ${response.status}`, response.status);
    }
    for await (const frame of decodeSSE(response.body)) {
      const envelope = frame.payload;
      yield { ...envelope, event: envelope.event || frame.name,
        event_id: Number(envelope.event_id || frame.id || 0) };
    }
  }
}

// The default endpoint when `jaeger.gatewayUrl` is unset: the contract's current
// Gateway URL if it answers /health, else its legacy URL (contract.json is
// generated from jaeger_ai/contract/ports.py), else the current URL so errors
// name where the Gateway should be.
async function resolveDefaultEndpoint(contract, probe) {
  const current = contract && contract.gatewayUrl;
  const legacy = contract && contract.legacyGatewayUrl;
  if (!legacy || legacy === current) return current;
  const healthy = probe || (async url => {
    try {
      const response = await nativeRequest(`${url}/health`, { method: 'GET', signal: AbortSignal.timeout(1500) });
      return response.ok;
    } catch (_) { return false; }
  });
  for (const url of [current, legacy]) {
    if (await healthy(url)) return url;
  }
  return current;
}

module.exports = { Gateway, GatewayError, localEndpoint, isAllowedGatewayHost, decodeSSE, callerToken, nativeRequest, resolveDefaultEndpoint };
