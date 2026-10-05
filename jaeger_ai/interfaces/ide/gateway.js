'use strict';

// Transport only. Never starts a runtime or opens an application database.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// The IDE is the Gateway's `ide` caller. Its token lives in the macOS Keychain
// (service ai.jaeger.gateway.caller, account ide) and is read with the system
// `security` tool, so it never sits in settings or the extension bundle.
// JAEGER_CALLER_TOKEN_DIR (0600 files) is the test / throwaway-instance store.
const KEYCHAIN_SERVICE = 'ai.jaeger.gateway.caller';
let cachedToken = null;
function callerToken(caller = 'ide') {
  if (cachedToken && Date.now() - cachedToken.at < 30000) return cachedToken.value;
  let value = '';
  try {
    const dir = process.env.JAEGER_CALLER_TOKEN_DIR;
    value = dir
      ? fs.readFileSync(path.join(dir, `${caller}.token`), 'utf8').trim()
      : execFileSync('/usr/bin/security', ['find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', caller, '-w'],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 }).trim();
  } catch (_) { value = ''; }
  cachedToken = value ? { value, at: Date.now() } : null;
  return value;
}

class GatewayError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

function localEndpoint(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Use a local HTTP Gateway URL without credentials or a path. Remote access is not configured.');
  }
  return url.origin;
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
  constructor(url, options = {}) { this.url = localEndpoint(url); this.token = options.token || callerToken; }
  auth() {
    const token = this.token('ide');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  async json(path, body, method) {
    const response = await fetch(this.url + path, {
      method: method || (body === undefined ? 'GET' : 'POST'), redirect: 'error',
      headers: { 'Content-Type': 'application/json', ...this.auth() },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
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
  orchestrationWorkers() { return this.json('/v1/orchestration/workers'); }
  orchestrationSubmit(body) { return this.json('/v1/orchestration/tasks', body); }
  orchestrationTask(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}`); }
  orchestrationFollowUp(id, body) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}/follow-up`, body); }
  orchestrationCancel(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}/cancel`, {}); }

  async *events(id, cursor, signal) {
    const response = await fetch(`${this.url}/v1/sessions/${encodeURIComponent(id)}/stream?last_event_id=${cursor}`, {
      headers: { Accept: 'text/event-stream', ...this.auth() }, signal, redirect: 'error',
    });
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

module.exports = { Gateway, GatewayError, localEndpoint, decodeSSE, callerToken };
