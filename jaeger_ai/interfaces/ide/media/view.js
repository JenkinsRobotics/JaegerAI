(function bootJaegerView() {
'use strict';
const { groupActivity, activityTitle, toolName, failureCount, groupTurns, selectableModels,
  providerModelValue }
  = window.JaegerPresentation;
const { renderMarkdownOnce } = window.JaegerMarkdown;
const { createFrameQueue } = window.JaegerFrameQueue;
const { KeyedRenderer } = window.JaegerKeyedRenderer;

const api = acquireVsCodeApi();
const $ = id => document.getElementById(id);
let state = { connected: false, busy: false, staged: [], activity: [], reasoning: '', models: null, configuredModel: '' };
let revision = '', modelRevision = '', draftSession = '';
const drafts = api.getState()?.drafts || {};
const post = (type, extra = {}) => api.postMessage({ type, ...extra });

function saveDraft() { drafts[draftSession] = $('prompt').value; api.setState({ drafts }); }
function eligibility() { $('send').disabled = !state.connected || state.busy || !state.session || !$('prompt').value.trim(); }

function announceCopied() {
  const node = $('copied');
  node.textContent = ''; // force a change so screen readers re-announce a repeat copy
  requestAnimationFrame(() => { node.textContent = 'Copied to clipboard'; });
}

function copyButton(text) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'copy'; button.textContent = 'Copy';
  button.setAttribute('aria-label', 'Copy reply to clipboard');
  button.onclick = () => {
    post('copy', { text });
    announceCopied();
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = 'Copy'; }, 1200);
  };
  return button;
}

// One message bubble. `content` is rendered as Markdown when it settles
// (an assistant message already in history); `liveText`/`streaming` render
// the in-flight reply, re-parsed on every call as more of it arrives (see
// markdown.js's renderMarkdownOnce doc comment for why that's the safe,
// simple choice here rather than an incremental parser).
function message(role, text) {
  const node = document.createElement('article'); node.className = role === 'user' ? 'user message' : 'assistant message';
  const label = document.createElement('div'); label.className = 'speaker';
  const name = document.createElement('span'); name.textContent = role === 'user' ? 'You' : 'Jaeger';
  label.append(name);
  if (role === 'assistant' && text) label.append(copyButton(text));
  const content = document.createElement('div'); content.className = 'content';
  renderMarkdownOnce(window.smd, content, text);
  node.append(label, content);
  return node;
}

// The compact "Using X" / "Used N tools" section, collapsed by default.
// Failures stay visible as a count on the (possibly closed) header — the
// one thing worth surfacing from a section the operator hasn't opened.
function activitySection(items, running) {
  const details = document.createElement('details'); details.className = 'activity';
  const summary = document.createElement('summary');
  const title = document.createElement('span'); title.textContent = activityTitle(items, running);
  summary.append(title);
  const failed = failureCount(items);
  if (failed > 0) {
    const badge = document.createElement('span'); badge.className = 'activity-fail';
    badge.textContent = `${failed} failed`; summary.append(badge);
  }
  details.append(summary);
  for (const item of items) {
    const row = document.createElement('div'); row.className = 'activity-item' + (item.ok === false ? ' failed' : '');
    const tool = document.createElement('span'); tool.className = 'tool'; tool.textContent = toolName(item.name);
    row.append(tool);
    if (item.detail) { const detail = document.createElement('span'); detail.textContent = item.detail; row.append(detail); }
    details.append(row);
  }
  return details;
}

// Reasoning is model deliberation, never part of the answer — its own
// disclosure, and only rendered when a real turn.reasoning event produced
// text. No placeholder section when the Gateway sent none.
function reasoningSection(text) {
  const details = document.createElement('details'); details.className = 'reasoning';
  const summary = document.createElement('summary'); summary.textContent = 'Reasoning'; details.append(summary);
  const content = document.createElement('div'); content.className = 'content'; content.textContent = text;
  details.append(content);
  return details;
}

function renderTurn(turn) {
  const node = document.createElement('div'); node.className = 'turn';
  if (turn.user) node.append(message('user', turn.user.content));
  for (const assistant of turn.assistants) node.append(message('assistant', assistant.content));
  return node;
}

function renderLiveTurn() {
  const node = document.createElement('div'); node.className = 'turn';
  if (state.reasoning) node.append(reasoningSection(state.reasoning));
  const groups = groupActivity(state.activity);
  for (const group of groups) node.append(activitySection(group, state.busy));
  if (state.text) node.append(message('assistant', state.text));
  return node.childNodes.length ? node : null;
}

function transcriptRows() {
  const history = state.session?.messages || [];
  const rows = history
    .filter(item => item.role === 'user' || item.role === 'assistant')
    .map((item, index) => ({
      key: `history:${item.message_id || item.id || index}:${item.role}`,
      kind: item.role, text: String(item.content || ''), live: false,
    }));
  for (const row of state.timeline || []) rows.push({ ...row, key: `live:${row.key}` });
  if (!rows.length && state.session) rows.push({
    key: 'session-ready', kind: 'assistant', text: 'Ready. What would you like to work on?', live: false,
  });
  if (!rows.length) rows.push({ key: 'empty', kind: 'empty', live: false });
  return rows;
}

function createTimelineRow() {
  const node = document.createElement('div');
  node.className = 'timeline-row';
  return node;
}

function updateTimelineRow(node, row) {
  // Keyed nodes survive stream updates. Only the currently changing row is
  // rebuilt, so selection and disclosures in settled rows remain untouched.
  const wasOpen = node.querySelector('details')?.open || false;
  node.className = `timeline-row ${row.kind}`;
  let content;
  if (row.kind === 'user' || row.kind === 'assistant' || row.kind === 'answer') {
    content = message(row.kind === 'user' ? 'user' : 'assistant', row.text || '');
  } else if (row.kind === 'reasoning') {
    content = reasoningSection(row.text || '');
  } else if (row.kind === 'tool') {
    content = activitySection([{ name: row.name, ok: row.ok, detail: row.detail }], row.phase === 'running');
  } else if (row.kind === 'empty') {
    content = document.createElement('section'); content.className = 'empty';
    const title = document.createElement('h1'); title.textContent = 'What are we working on?';
    const description = document.createElement('p');
    description.textContent = 'Create a conversation or reopen an existing one. Your Gateway owns the work.';
    content.append(title, description);
  } else {
    content = document.createElement('div'); content.className = 'subtle';
    content.textContent = row.detail || row.status || '';
  }
  const disclosure = content.matches?.('details') ? content : content.querySelector?.('details');
  if (disclosure) disclosure.open = wasOpen;
  node.replaceChildren(content);
}

const timelineRenderer = new KeyedRenderer($('timeline'), createTimelineRow, updateTimelineRow);

function renderModels() {
  const select = $('model');
  const rows = selectableModels(state.models);
  const signature = JSON.stringify(rows) + (state.modelsError || '') + (state.configuredModel || '');
  if (signature === modelRevision) return;
  modelRevision = signature;
  const previous = select.value;
  select.replaceChildren(new Option('Keep session selection', ''));
  if (state.configuredModel) select.add(new Option(`From settings · ${state.configuredModel}`, 'config'));
  for (const row of rows) select.add(new Option(`${row.provider} · ${row.id}`, providerModelValue(row.provider, row.id)));
  // Restore an explicit prior selection when it is still valid; otherwise default
  // to the configured-model option so the display matches what will actually be sent.
  const valid = new Set(['', ...(state.configuredModel ? ['config'] : []), ...rows.map(r => providerModelValue(r.provider, r.id))]);
  select.value = valid.has(previous) ? previous : (state.configuredModel ? 'config' : '');
  select.title = state.modelsError ? `Couldn't load the model list: ${state.modelsError}` : 'Model';
  select.disabled = rows.length === 0 && !state.configuredModel;
}

function renderStaged() {
  const container = $('staged');
  container.replaceChildren();
  for (const attachment of state.staged || []) {
    const chip = document.createElement('span'); chip.className = 'chip';
    const name = document.createElement('span'); name.className = 'name';
    name.textContent = attachment.original_filename || attachment.stored_filename || attachment.attachment_id;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '✕';
    remove.setAttribute('aria-label', `Remove attachment ${name.textContent}`);
    remove.onclick = () => post('removeAttachment', { id: attachment.attachment_id });
    chip.append(name, remove);
    container.append(chip);
  }
}

function render() {
  $('status').textContent = state.status || '';
  $('error').hidden = !state.error; $('error').textContent = state.error || '';
  const sid = state.session?.session_id || '';
  if (draftSession !== sid) { saveDraft(); draftSession = sid; $('prompt').value = drafts[sid] || ''; }
  const sessionOptions = JSON.stringify(state.sessions || []);
  if (revision !== sessionOptions) {
    revision = sessionOptions; $('sessions').replaceChildren(new Option('Select a conversation', ''));
    for (const session of state.sessions || []) $('sessions').add(new Option(session.title || session.session_id, session.session_id));
  }
  $('sessions').value = sid;
  $('context').textContent = state.session ? `${state.session.profile || 'Jaeger'} · ${state.session.title}` : 'Gateway-owned conversation';
  $('stop').hidden = !state.busy || !state.canCancel; eligibility();
  $('attach').disabled = !state.connected || !state.session;
  renderModels(); renderStaged();

  timelineRenderer.reconcile(transcriptRows());

  $('approvals').replaceChildren();
  for (const approval of state.approvals || []) {
    const card = document.createElement('section'); card.className = 'approval';
    const text = document.createElement('p'); text.textContent = approval.prompt || approval.tool || 'Approval requested'; card.append(text);
    for (const [title, approved] of [['Allow once', true], ['Deny', false]]) {
      const button = document.createElement('button'); button.textContent = title;
      button.onclick = () => post('approve', { id: approval.approval_id || approval.id, approved }); card.append(button);
    }
    $('approvals').append(card);
  }
}

const stateQueue = createFrameQueue(batch => {
  const data = batch.at(-1);
  if (data.accepted) {
    if ($('prompt').value.trim() === data.submittedText) $('prompt').value = '';
    saveDraft(); eligibility(); return;
  }
  state = { ...state, ...data }; render();
}, data => data.updateKind === 'stream');

window.addEventListener('message', ({ data }) => stateQueue.push(data));
$('composer').onsubmit = event => {
  event.preventDefault();
  // Always send the picker's current value. The extension interprets '' as
  // keep-session, 'config' as the static setting, and 'provider::model' as
  // an explicit catalog choice — the display matches the behaviour.
  if (!$('send').disabled) post('send', { text: $('prompt').value, model: $('model').value });
};
$('prompt').oninput = () => { saveDraft(); eligibility(); };
$('prompt').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } };
$('sessions').onchange = () => post('select', { id: $('sessions').value });
$('attach').onclick = () => post('attach');
for (const [id, type] of [['new', 'new'], ['refresh', 'refresh'], ['settings', 'settings'], ['stop', 'cancel']]) $(id).onclick = () => post(type);
post('ready');
})();
