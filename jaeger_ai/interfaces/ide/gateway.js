'use strict';

// Transport only. Never starts a runtime or opens an application database.
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
  constructor(url) { this.url = localEndpoint(url); }
  async json(path, body) {
    const response = await fetch(this.url + path, {
      method: body === undefined ? 'GET' : 'POST', redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const result = await response.json();
    if (!response.ok) throw new GatewayError(String(result.error || `Gateway HTTP ${response.status}`), response.status);
    return result;
  }
  sessions() { return this.json('/v1/sessions'); }
  session(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}`); }
  create(body) { return this.json('/v1/sessions', body); }
  send(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/turns`, body); }
  receipt(id, rid) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/requests/${encodeURIComponent(rid)}`); }
  cancel(id, rid) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/cancel`, { request_id: rid }); }
  approvals() { return this.json('/v1/approvals'); }
  approve(id, approved) { return this.json(`/v1/approvals/${encodeURIComponent(id)}`, { approved }); }
  attachments(id) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/attachments`); }
  addAttachment(id, body) { return this.json(`/v1/sessions/${encodeURIComponent(id)}/attachments`, body); }
  // The Gateway's real provider/model catalog — never a hardcoded picker list.
  models() { return this.json('/v1/runtime/models'); }
  orchestrationWorkers() { return this.json('/v1/orchestration/workers'); }
  orchestrationSubmit(body) { return this.json('/v1/orchestration/tasks', body); }
  orchestrationTask(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}`); }
  orchestrationCancel(id) { return this.json(`/v1/orchestration/tasks/${encodeURIComponent(id)}/cancel`, {}); }

  async *events(id, cursor, signal) {
    const response = await fetch(`${this.url}/v1/sessions/${encodeURIComponent(id)}/stream?last_event_id=${cursor}`, {
      headers: { Accept: 'text/event-stream' }, signal, redirect: 'error',
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

module.exports = { Gateway, GatewayError, localEndpoint, decodeSSE };
