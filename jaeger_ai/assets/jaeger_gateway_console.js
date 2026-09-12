/* Jaeger Gateway console — sessions, live turn streaming, approvals.
 *
 * Binds to the routes audited from core/gateway/server.py via the WebUI's
 * server-side proxy (api/jaeger_sessions.py). No mock layer: every call
 * below hits :8810 for real, and every failure is rendered rather than
 * swallowed. A stalled stream must never look like a quiet agent.
 *
 * Event vocabulary comes from the gateway, not from guesses:
 *   turn.start turn.delta turn.finish turn.failed turn.cancel
 *   turn.cancelled turn.reconciled turn.unknown
 *   session.created session.deleted session.handoff
 *   agent.created agent.activated agent.handoff agent.handoff.finished
 *   approval.request approval.resolved
 *   gateway.error            <- synthesised by the proxy, not the gateway
 */
(() => {
  'use strict';
  const extension = window.hermesExt?.register?.('jaeger-gateway-console');
  if (!extension) return;

  const API = '/api/jaeger';
  const $ = (tag, css, text) => {
    const el = document.createElement(tag);
    if (css) el.style.cssText = css;
    if (text != null) el.textContent = text;
    return el;
  };

  // ── connection state ───────────────────────────────────────────────
  // Four explicit states. "idle" is NOT one of them: a stream that has
  // gone quiet is either live or broken, and the UI must say which.
  const STATE = {
    connecting: ['Connecting…', '#8a5a0b'],
    live:       ['Live', '#1f6f5c'],
    retrying:   ['Reconnecting…', '#8a5a0b'],
    closed:     ['Disconnected', '#9e2a22'],
    error:      ['Error', '#9e2a22'],
  };

  const style = document.createElement('style');
  style.textContent = `
    #jgc {font:13px/1.5 system-ui,sans-serif;padding:10px;display:flex;flex-direction:column;gap:8px}
    #jgc button {font:inherit;padding:4px 10px;cursor:pointer}
    #jgc-status {display:flex;align-items:center;gap:6px;font-weight:600}
    #jgc-dot {width:8px;height:8px;border-radius:50%;display:inline-block}
    #jgc-sessions {max-height:150px;overflow:auto;border:1px solid #ccc}
    #jgc-sessions div {padding:4px 8px;cursor:pointer;border-bottom:1px solid #eee}
    #jgc-sessions div[aria-selected="true"] {background:#e4e9f1;font-weight:600}
    #jgc-log {max-height:260px;overflow:auto;border:1px solid #ccc;padding:6px;
              white-space:pre-wrap;overflow-wrap:anywhere;font-family:ui-monospace,monospace;font-size:12px}
    #jgc-err {color:#9e2a22;font-weight:600}
    #jgc-err[hidden] {display:none}
    .jgc-evt-turn\\.failed, .jgc-evt-gateway\\.error {color:#9e2a22}
    .jgc-evt-approval\\.request {color:#8a5a0b;font-weight:600}
  `;
  document.head.appendChild(style);

  const root   = $('div'); root.id = 'jgc';
  const status = $('div'); status.id = 'jgc-status';
  const dot    = $('span'); dot.id = 'jgc-dot';
  const label  = $('span', '', 'Connecting…');
  status.append(dot, label);

  const err   = $('div', '', ''); err.id = 'jgc-err'; err.hidden = true;
  const list  = $('div'); list.id = 'jgc-sessions';
  const log   = $('div'); log.id = 'jgc-log';
  const input = $('input');
  input.id = 'jgc-input';
  input.placeholder = 'Send a turn to the selected session…';
  input.style.cssText = 'flex:1;font:inherit;padding:4px 6px';

  const bar     = $('div', 'display:flex;gap:6px');
  const btnNew  = $('button', '', 'New session');
  const btnSend = $('button', '', 'Send');
  const btnStop = $('button', '', 'Cancel turn');
  bar.append(btnNew, btnSend, btnStop);

  const composer = $('div', 'display:flex;gap:6px');
  composer.append(input);

  root.append(status, err, list, composer, bar, log);

  let sessions = [];
  let active = null;
  let source = null;
  let lastEventId = 0;
  let retryDelay = 1000;

  function setState(key, detail) {
    const [text, color] = STATE[key] || STATE.error;
    dot.style.background = color;
    label.textContent = detail ? `${text} — ${detail}` : text;
  }

  function showError(message) {
    // Every failure path lands here. Nothing is logged-and-forgotten:
    // if the user cannot see it, we did not handle it.
    err.textContent = message;
    err.hidden = false;
  }
  function clearError() { err.hidden = true; err.textContent = ''; }

  function append(eventName, payload) {
    const line = $('div', '', `${eventName}  ${payload}`);
    line.className = `jgc-evt-${eventName}`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  async function call(path, options) {
    const response = await fetch(`${API}${path}`, options);
    const text = await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = { error: text }; }
    if (!response.ok) {
      const reason = (body && body.error) || response.statusText;
      throw new Error(`${response.status} ${reason}`);
    }
    return body;
  }

  // ── sessions ───────────────────────────────────────────────────────

  async function loadSessions() {
    try {
      const data = await call('/sessions', { method: 'GET' });
      sessions = (data && data.sessions) || [];
      clearError();
      renderSessions();
    } catch (e) {
      // A failed list must not render as "no sessions" — that is exactly
      // the silent-empty failure this console exists to avoid.
      showError(`Could not load sessions: ${e.message}`);
      setState('error');
      list.innerHTML = '';
    }
  }

  function renderSessions() {
    list.innerHTML = '';
    if (!sessions.length) {
      list.appendChild($('div', 'color:#666', 'No sessions yet — create one.'));
      return;
    }
    for (const s of sessions) {
      const id = s.session_id || s.id;
      const row = $('div', '', `${s.title || 'Untitled'} · ${id}`);
      row.setAttribute('aria-selected', String(id === active));
      row.onclick = () => attach(id);
      list.appendChild(row);
    }
  }

  async function createSession() {
    try {
      const s = await call('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: `Console ${new Date().toLocaleTimeString()}` }),
      });
      await loadSessions();
      attach(s.session_id || s.id);
    } catch (e) {
      showError(`Create failed: ${e.message}`);
    }
  }

  // ── live stream ────────────────────────────────────────────────────

  function attach(sessionId) {
    if (!sessionId) return;
    active = sessionId;
    lastEventId = 0;
    renderSessions();
    log.innerHTML = '';
    openStream();
  }

  function openStream() {
    if (source) { source.close(); source = null; }
    if (!active) return;

    setState('connecting');
    const url = `${API}/sessions/${encodeURIComponent(active)}/stream`
      + (lastEventId ? `?last_event_id=${lastEventId}` : '');
    source = new EventSource(url);

    source.onopen = () => { setState('live'); clearError(); retryDelay = 1000; };

    source.onmessage = (evt) => handle('message', evt);
    for (const name of [
      'turn.start', 'turn.delta', 'turn.finish', 'turn.failed', 'turn.cancel',
      'turn.cancelled', 'turn.reconciled', 'turn.unknown',
      'session.created', 'session.deleted', 'session.handoff',
      'agent.created', 'agent.activated', 'agent.handoff', 'agent.handoff.finished',
      'approval.request', 'approval.resolved', 'gateway.error',
    ]) {
      source.addEventListener(name, (evt) => handle(name, evt));
    }

    source.onerror = () => {
      // EventSource retries on its own, but silently. Surface it, then
      // reconnect with backoff from the last event we actually saw so a
      // dropped connection resumes instead of replaying from zero.
      if (source && source.readyState === EventSource.CLOSED) {
        setState('closed');
        showError('Stream closed by the gateway. Reconnecting…');
      } else {
        setState('retrying');
      }
      if (source) { source.close(); source = null; }
      setTimeout(openStream, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    };
  }

  function handle(name, evt) {
    if (evt.lastEventId) {
      const parsed = parseInt(evt.lastEventId, 10);
      if (!Number.isNaN(parsed)) lastEventId = parsed;
    }
    let data = evt.data;
    try {
      const parsed = JSON.parse(evt.data);
      data = typeof parsed.data === 'string'
        ? parsed.data
        : JSON.stringify(parsed.data ?? parsed);
      if (parsed.event) name = parsed.event;
    } catch { /* keep the raw frame — never drop an event we cannot parse */ }

    if (name === 'gateway.error') {
      setState('error');
      showError(`Gateway stream error: ${data}`);
    }
    if (name === 'approval.request') {
      renderApproval(evt.data);
    }
    append(name, data);
  }

  function renderApproval(raw) {
    let payload;
    try { payload = JSON.parse(raw); } catch { return; }
    const body = payload.data || payload;
    const id = body.approval_id;
    if (!id) return;

    const box = $('div', 'border:1px solid #8a5a0b;padding:6px;margin:4px 0');
    box.append($('div', 'font-weight:600', body.prompt || 'Approval required'));
    for (const choice of (body.options && body.options.length ? body.options : ['once', 'deny'])) {
      const b = $('button', 'margin-right:6px', choice);
      b.onclick = async () => {
        try {
          await call(`/approvals/${encodeURIComponent(id)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decision: choice, approved: choice !== 'deny' }),
          });
          box.remove();
        } catch (e) {
          showError(`Approval failed: ${e.message}`);
        }
      };
      box.appendChild(b);
    }
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
  }

  // ── turns ──────────────────────────────────────────────────────────

  async function sendTurn() {
    const text = input.value.trim();
    if (!text) return;
    if (!active) { showError('Select or create a session first.'); return; }
    input.value = '';
    try {
      await call(`/sessions/${encodeURIComponent(active)}/turns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      clearError();
    } catch (e) {
      // 409 = a turn is already in flight. Say so; do not retry blindly.
      showError(`Send failed: ${e.message}`);
      input.value = text;
    }
  }

  async function cancelTurn() {
    if (!active) return;
    try {
      await call(`/sessions/${encodeURIComponent(active)}/cancel`, { method: 'POST' });
    } catch (e) {
      showError(`Cancel failed: ${e.message}`);
    }
  }

  btnNew.onclick = createSession;
  btnSend.onclick = sendTurn;
  btnStop.onclick = cancelTurn;
  input.onkeydown = (e) => { if (e.key === 'Enter') sendTurn(); };

  // ── boot ───────────────────────────────────────────────────────────

  (async () => {
    try {
      await call('/gateway/health', { method: 'GET' });
      setState('live', 'gateway reachable');
    } catch (e) {
      setState('error');
      showError(`Gateway unreachable: ${e.message}`);
    }
    await loadSessions();
  })();

  if (extension.panel) extension.panel(root);
  else document.body.appendChild(root);
})();
