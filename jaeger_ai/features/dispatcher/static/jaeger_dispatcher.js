/* Jaeger-owned extension. Native APIs remain behind Hermes' token-v1 proxy. */
(() => {
  'use strict';
  const extension = window.hermesExt?.register?.('jaeger-dispatcher');
  if (!extension) return;
  const conversation = '/api/jaeger/conversation';
  let revision = null;
  let refreshing = false;
  const status = document.createElement('div');
  status.id = 'jaeger-conversation-status';
  status.style.cssText = 'padding:8px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto';
  const root = '/api/extensions/jaeger-dispatcher/sidecar';
  let active = false;
  let busy = false;
  let primary = null;
  const style = document.createElement('style');
  style.textContent = `
    #jaeger-dispatcher-bar {padding:8px;display:flex;gap:6px;flex-wrap:wrap}
    #jaeger-dispatcher-bar[hidden] {display:none}
    body[data-jaeger-profile="true"] .session-title:not([data-jaeger-primary])::before {content:"🎯 Focus: "}
    #jaeger-native-dialog {background:var(--bg,#171725);color:var(--text,#eee);border:1px solid var(--border,#555);border-radius:12px;max-width:760px;width:85vw;max-height:80vh}
    #jaeger-native-dialog pre {white-space:pre-wrap;overflow-wrap:anywhere}
    #jaeger-native-dialog article {padding:8px;border-bottom:1px solid var(--border,#555)}
  `;
  document.head.appendChild(style);
  const bar = document.createElement('div');
  bar.id = 'jaeger-dispatcher-bar';
  bar.hidden = true;
  const dialog = document.createElement('dialog');
  dialog.id = 'jaeger-native-dialog';
  dialog.setAttribute('aria-label', 'Jaeger native information');
  const close = document.createElement('button');
  close.textContent = 'Close';
  close.onclick = () => dialog.close();
  const content = document.createElement('div');
  dialog.append(close, content);
  document.body.appendChild(dialog);

  async function request(path, body) {
    if (typeof window.api !== 'function') throw new Error('This WebUI version lacks its authenticated API helper');
    return window.api(path, {retries: 0, ...(body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    })});
  }
  function showError(error) {
    content.replaceChildren();
    const message = document.createElement('p');
    message.textContent = String(error.message || error) + '. If the proxy is disabled, enable WebUI login and approve Jaeger Dispatcher in Settings → Extensions.';
    content.appendChild(message);
    if (!dialog.open) dialog.showModal();
  }
  async function ensureJaeger() {
    const profile = await request('/api/profile/active');
    if (profile.name !== 'jaeger') throw new Error('Select the Jaeger profile first');
  }
  async function openDispatcher() {
    if (busy) return;
    busy = true;
    try {
      await ensureJaeger();
      const state = await request(conversation);
      primary = state.dispatcher_session;
      if (!primary) {
        const created = await request('/api/session/new', {profile: 'jaeger', worktree: false});
        const bound = await request(conversation + '/bind', {session_id: created.session.session_id});
        primary = bound.session_id;
        await request('/api/session/rename', {session_id: primary, title: '⚡ Dispatcher'});
        await request('/api/session/pin', {session_id: primary, pinned: true});
      }
      await ensureJaeger();
      await loadSession(primary, {force: true});
      revision = null;
    } catch (error) { showError(error); }
    finally { busy = false; }
  }
  async function panel(kind) {
    try {
      await ensureJaeger();
      const data = await request(root + '/' + kind);
      await ensureJaeger();
      content.replaceChildren();
      const title = document.createElement('h2');
      title.textContent = kind === 'skills' ? 'Jaeger Skills' : 'Jaeger Memory and Focus Reports';
      content.appendChild(title);
      if (kind === 'skills') {
        for (const skill of data.skills || []) {
          const item = document.createElement('article');
          const heading = document.createElement('strong');
          heading.textContent = skill.name + (skill.disabled ? ' (disabled)' : '');
          const text = document.createElement('p');
          text.textContent = skill.description || '';
          item.append(heading, text); content.appendChild(item);
        }
      } else {
        const facts = document.createElement('pre');
        facts.textContent = 'Operator facts\n' + JSON.stringify(data.facts || {}, null, 2);
        content.appendChild(facts);
        for (const card of data.board?.cards || []) {
          const item = document.createElement('article');
          const heading = document.createElement('strong');
          heading.textContent = card.title + ' — ' + card.column;
          const text = document.createElement('pre');
          text.textContent = card.result || card.description || '';
          item.append(heading, text); content.appendChild(item);
        }
      }
      if (!dialog.open) dialog.showModal();
    } catch (error) { showError(error); }
  }
  for (const [label, action] of [['⚡ Dispatcher', openDispatcher], ['Jaeger Skills', () => panel('skills')], ['Jaeger Memory', () => panel('memory')]]) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label; button.onclick = action;
    bar.appendChild(button);
  }
  // Capture the existing panel buttons only in Jaeger. Hermes/OpenClaw keep
  // their own handlers; no global fetch override or upstream route patch.
  document.addEventListener('click', event => {
    // The WebUI updates its active profile synchronously during a switch;
    // do not intercept another profile's click using the polling snapshot.
    const current = typeof S !== 'undefined' && typeof S.activeProfile === 'string'
      ? S.activeProfile === 'jaeger' : active;
    if (!current) return;
    const button = event.target.closest?.('[data-panel="skills"], [data-panel="memory"]');
    if (!button) return;
    event.preventDefault(); event.stopImmediatePropagation();
    panel(button.dataset.panel);
  }, true);
  async function refresh() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    try {
      const profile = await request('/api/profile/active');
      const next = profile.name === 'jaeger';
      if (active && !next && dialog.open) dialog.close();
      const entering = next && !active;
      active = next;
      document.body.dataset.jaegerProfile = String(active);
      bar.hidden = !active;
      const list = document.getElementById('sessionList');
      if (list && !bar.isConnected) list.before(bar);
      status.hidden = !active;
      const main = document.getElementById('mainChat');
      if (main && !status.isConnected) main.prepend(status);
      if (active) {
        try {
          const snapshot = await request(conversation);
          if (typeof S !== 'undefined' && S.activeProfile !== 'jaeger') return;
          primary = snapshot.dispatcher_session;
          if (entering && primary) await loadSession(primary, {force: true});
          else if (entering && !primary) await openDispatcher();
          const viewing = typeof S !== 'undefined' && S.session?.session_id === primary;
          status.hidden = !viewing;
          const run = snapshot.run;
          const streaming = typeof S !== 'undefined' && (S.busy || S.activeStreamId || S.session?.active_stream_id);
          if (viewing && !streaming && revision !== snapshot.revision) {
            await loadSession(primary, {force: true});
            revision = snapshot.revision;
          }
          status.replaceChildren();
          const line = document.createElement('div');
          line.textContent = run && run.status !== 'completed' ? 'Dispatcher — ' + run.status + (run.error ? ': ' + run.error : '') : 'Dispatcher · conversation synced with the Mac app';
          status.appendChild(line);
          if (snapshot.reports?.length) {
            const reports = document.createElement('button'); reports.textContent = 'Focus reports';
            reports.onclick = () => {
              content.replaceChildren();
              for (const report of snapshot.reports) {
                const item = document.createElement('article');
                item.textContent = report.status + ': ' + report.summary;
                content.appendChild(item);
              }
              if (!dialog.open) dialog.showModal();
            };
            status.appendChild(reports);
          }
          if (run?.active) {
            if (!streaming && run.output) {
              const partial = document.createElement('div'); partial.textContent = run.output; status.appendChild(partial);
            }
            const tool = run.tools?.at(-1);
            if (tool) { const label = document.createElement('div'); label.textContent = tool.event + ': ' + (tool.name || tool.tool || 'working'); status.appendChild(label); }
            const control = (label, action, body) => {
              const button = document.createElement('button'); button.textContent = label;
              button.onclick = async () => { button.disabled = true; try { await request(conversation + '/' + action, {run_id: run.run_id, ...body}); } catch (error) { line.textContent = error.message; } };
              status.appendChild(button);
            };
            control(run.needs_reconciliation ? 'Check execution status' : 'Stop', run.needs_reconciliation ? 'reconcile' : 'cancel', {});
            for (const approval of run.approvals || []) {
              const prompt = document.createElement('div'); prompt.textContent = approval.description; status.appendChild(prompt);
              for (const choice of approval.choices || []) control(choice, 'approval', {approval_id: approval.approval_id, choice});
            }
          }
        } catch (error) { status.hidden = false; status.textContent = 'Dispatcher connection unavailable: ' + error.message; }
      }
      document.querySelectorAll('.session-title').forEach(title => {
        if (title.textContent === '⚡ Dispatcher') title.dataset.jaegerPrimary = 'true';
        else delete title.dataset.jaegerPrimary;
      });
    } catch (_) { bar.hidden = true; active = false; delete document.body.dataset.jaegerProfile; }
    finally { refreshing = false; }
  }
  extension.events.on('turn:complete', refresh);
  window.addEventListener('pageshow', refresh);
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, 2000);
  refresh();
})();
