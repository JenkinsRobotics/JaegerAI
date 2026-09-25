(function bootJaegerView() {
'use strict';
const { groupActivity, activityTitle, activitySummary, activityIcon, groupWorkRows, diffLines, toolName, failureCount, groupTurns, selectableModels,
  providerModelValue, filterChats }
  = window.JaegerPresentation;
const { renderMarkdownOnce } = window.JaegerMarkdown;
const { createFrameQueue } = window.JaegerFrameQueue;
const { KeyedRenderer } = window.JaegerKeyedRenderer;
const { match: matchSlash, parse: parseSlash } = window.JaegerSlash;

const api = acquireVsCodeApi();
const $ = id => document.getElementById(id);
let state = { connected: false, busy: false, staged: [], queue: [], activity: [], reasoning: '', models: null, configuredModel: '', ideContext: null, diagnostics: 0, selectedWorkspace: '' };
let revision = '', modelRevision = '', draftSession = '';
let submittedDraftSession = null;
let editingQueueId = null;
let showAllChats = false;
let chatSearch = api.getState()?.chatSearch || '';
const drafts = api.getState()?.drafts || {};
const post = (type, extra = {}) => api.postMessage({ type, ...extra });
window.JaegerPostMessage = post;

let ideContextOn = api.getState()?.ideContext !== false;
let planModeOn = api.getState()?.planMode === true;
const persistView = () => api.setState({ drafts, ideContext: ideContextOn, planMode: planModeOn, chatSearch });
function saveDraft() { drafts[draftSession] = $('prompt').value; persistView(); }
// While the agent is busy, Enter steers the live turn. “Queue next” writes a
// durable Gateway request instead; this client never owns a second queue.
function eligibility() { $('send').disabled = !state.connected || !$('prompt').value.trim(); }

function announceCopied() {
  const node = $('copied');
  node.textContent = ''; // force a change so screen readers re-announce a repeat copy
  requestAnimationFrame(() => { node.textContent = 'Copied to clipboard'; });
}

function icon(name) {
  const paths = { copy: 'M9 8V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-3M5 9h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z',
    edit: 'm15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z',
    read: 'M12 5v16M12 5C8 2 4 2 2 4v15c3-2 6-1 10 2 4-3 7-4 10-2V4c-2-2-6-2-10 1Z',
    integration: 'm9 9 4 12 3-5 5-3-12-4ZM4 3l2 2M2 10h3M10 2v3M16 4l-2 2M4 16l2-2',
    tool: 'M8 7l4 5-4 5m6 0h4M5 2h14a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3Z',
    file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 14h8m-4-4v8' };
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', width: '18', height: '18', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(key, value);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', paths[name]); svg.append(path);
  return svg;
}

function copyButton(text) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'copy'; button.append(icon('copy'));
  button.title = 'Copy message'; button.setAttribute('aria-label', 'Copy message');
  button.onclick = () => {
    post('copy', { text });
    announceCopied();
    button.textContent = 'Copied';
    setTimeout(() => { button.replaceChildren(icon('copy')); }, 1200);
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
  const avatar = document.createElement('div'); avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'U' : 'J';
  const name = document.createElement('span'); name.className = 'role-name'; name.textContent = role === 'user' ? 'You' : 'Jaeger';
  label.append(avatar, name);
  if (role === 'assistant' && text) label.append(copyButton(text));
  const content = document.createElement('div'); content.className = 'content';
  if (role === 'user') content.textContent = text;
  else renderMarkdownOnce(window.smd, content, text);
  node.append(label, content);
  if (role === 'user') {
    const actions = document.createElement('div'); actions.className = 'message-actions';
    const edit = document.createElement('button'); edit.type = 'button'; edit.append(icon('edit'));
    edit.title = 'Edit and resend'; edit.setAttribute('aria-label', 'Edit and resend message');
    edit.onclick = () => {
      if ($('prompt').value.trim() && $('prompt').value !== text) { post('editDraft', { text }); return; }
      $('prompt').value = text; saveDraft(); eligibility(); $('prompt').focus();
    };
    actions.append(copyButton(text), edit); node.append(actions);
  }
  return node;
}

// The compact "Using X" / "Used N tools" section, collapsed by default.
// Failures stay visible as a count on the (possibly closed) header — the
// one thing worth surfacing from a section the operator hasn't opened.
function activitySection(items, running) {
  const details = document.createElement('details'); details.className = 'activity' + (running ? ' running tool-card' : ' tool-card');
  const summary = document.createElement('summary');
  const title = document.createElement('span'); title.textContent = activitySummary(items, running);
  summary.title = title.textContent;
  const glyph = icon(activityIcon(items)); glyph.setAttribute('class', 'activity-icon');
  title.className = 'activity-label';
  summary.append(glyph, title);
  
  const statusBadge = document.createElement('span'); 
  statusBadge.className = 'status-badge ' + (running ? 'running' : 'completed');
  statusBadge.textContent = running ? 'running' : 'completed';
  
  const failed = failureCount(items);
  if (failed > 0) {
    statusBadge.className = 'status-badge failed';
    statusBadge.textContent = `${failed} failed`; 
  }
  summary.append(statusBadge);
  details.append(summary);
  
  for (const item of items) {
    const row = document.createElement('div'); row.className = 'activity-item' + (item.ok === false ? ' failed' : '');
    const tool = document.createElement('span'); tool.className = 'tool'; tool.textContent = toolName(item.name);
    row.append(tool);
    if (item.detail) { const detail = document.createElement('span'); detail.textContent = item.detail; row.append(detail); }
    details.append(row);
    // What ran and what it printed, as text (never HTML): IN then OUT, like an IDE terminal.
    for (const [label, text] of [['IN', item.input], ['OUT', item.output]]) {
      if (!text) continue;
      const block = document.createElement('div'); block.className = 'io-block';
      const tag = document.createElement('span'); tag.className = 'io-tag'; tag.textContent = label;
      const body = document.createElement('pre'); body.textContent = text;
      block.append(tag, body); details.append(block);
    }
  }
  return details;
}

// Reasoning is model deliberation, never part of the answer — its own
// disclosure, and only rendered when a real turn.reasoning event produced
// text. No placeholder section when the Gateway sent none.
function reasoningSection(text, live = false) {
  const details = document.createElement('details'); details.className = 'reasoning';
  const summary = document.createElement('summary'); summary.textContent = live ? 'Thinking…' : 'Reasoning'; details.append(summary);
  const content = document.createElement('div'); content.className = 'content'; content.textContent = text;
  details.append(content);
  return details;
}

// Gateway-owned queued work. These rows are editable before promotion, so
// the composer becomes the edit surface rather than a second state owner.
function queueButton(label, action, title = label) {
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = label; button.title = title;
  button.setAttribute('aria-label', title);
  button.onclick = action;
  return button;
}

function renderQueue() {
  const container = $('queue');
  const items = state.queue || [];
  container.replaceChildren(); container.hidden = !items.length;
  if (!items.length) return;
  const heading = document.createElement('div'); heading.className = 'queue-heading';
  const title = document.createElement('span'); title.textContent = 'Queued work';
  const count = document.createElement('span');
  count.textContent = `${items.filter(item => item.status === 'queued').length} ready · ${items.filter(item => item.status === 'paused').length} paused`;
  heading.append(title, count);
  const list = document.createElement('div'); list.className = 'queue-list';
  items.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'queue-row' + (editingQueueId === item.request_id ? ' editing' : '');
    const position = document.createElement('span'); position.className = 'queue-index'; position.textContent = String(index + 1);
    const text = document.createElement('span'); text.className = 'queue-text'; text.textContent = item.input_text || '';
    const status = document.createElement('span'); status.className = 'queue-status'; status.textContent = item.status || 'queued';
    const actions = document.createElement('div'); actions.className = 'queue-actions';
    const editing = editingQueueId === item.request_id;
    if (editing) {
      actions.append(queueButton('Cancel', () => {
        editingQueueId = null; $('prompt').value = drafts[draftSession] || ''; eligibility(); renderQueue(); renderComposerBar();
      }, 'Cancel editing queued request'));
    } else {
      actions.append(queueButton('Edit', () => {
        editingQueueId = item.request_id; $('prompt').value = item.input_text || ''; saveDraft(); eligibility(); renderQueue(); renderComposerBar(); $('prompt').focus();
      }, 'Edit queued request'));
    }
    actions.append(queueButton(item.status === 'paused' ? 'Resume' : 'Pause', () => {
      post('queueUpdate', { id: item.request_id, status: item.status === 'paused' ? 'queued' : 'paused' });
    }, item.status === 'paused' ? 'Resume queued request' : 'Pause queued request'));
    if (index > 0) actions.append(queueButton('↑', () => {
      const order = items.map(row => row.request_id); [order[index - 1], order[index]] = [order[index], order[index - 1]];
      post('queueReorder', { order });
    }, 'Move queued request up'));
    if (index < items.length - 1) actions.append(queueButton('↓', () => {
      const order = items.map(row => row.request_id); [order[index], order[index + 1]] = [order[index + 1], order[index]];
      post('queueReorder', { order });
    }, 'Move queued request down'));
    actions.append(queueButton('Delete', () => post('queueDelete', { id: item.request_id }), 'Delete queued request'));
    row.append(position, text, status, actions); list.append(row);
  });
  container.append(heading, list);
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
  const rows = [], placed = new Set();
  let userIndex = -1;
  const workRow = work => ({ ...work, key: `work:${work.requestId}`, kind: 'work',
    live: !work.finishedAt && state.busy,
    rows: (state.timeline || []).filter(row => row.requestId === work.requestId
      && (['reasoning', 'tool', 'progress', 'checkpoint', 'plan'].includes(row.kind) || (state.busy && row.kind === 'answer'))) });
  history.filter(item => item.role === 'user' || item.role === 'assistant').forEach((item, index) => {
    rows.push({
      key: `history:${item.message_id || item.id || index}:${item.role}`,
      kind: item.role, text: String(item.content || ''), live: false,
    });
    if (item.role === 'user') {
      userIndex++;
      for (const work of state.workTurns || []) if (work.userIndex === userIndex) {
        rows.push(workRow(work)); placed.add(work.requestId);
      }
    }
  });
  for (const work of state.workTurns || []) if (!placed.has(work.requestId) && !work.finishedAt) {
    rows.push(workRow(work)); placed.add(work.requestId);
  }
  const legacyActivity = (state.timeline || []).filter(row => !placed.has(row.requestId)
    && ['reasoning', 'tool', 'progress', 'checkpoint', 'plan'].includes(row.kind));
  if (legacyActivity.length) {
    const lastAnswer = rows.findLastIndex(row => row.kind === 'assistant');
    rows.splice(lastAnswer < 0 ? rows.length : lastAnswer, 0,
      { key: 'legacy-work', kind: 'work', status: 'completed', live: false, rows: legacyActivity });
  }
  for (const row of state.timeline || []) {
    if (placed.has(row.requestId) && (state.busy || row.kind !== 'answer')) continue;
    if (legacyActivity.includes(row) || row.kind === 'control' || row.kind === 'terminal') continue;
    rows.push({ ...row, key: `live:${row.key}` });
  }
  if (state.preview) rows.push({ key: `diff:${state.preview.requestId}:${state.preview.path}`, kind: 'diff', file: state.preview });
  if (!rows.length) rows.push({ key: 'empty', kind: 'empty', live: false });
  return rows;
}

// The model's step plan as a checklist. Text only (no innerHTML): steps are model output.
function planSection(row) {
  const section = document.createElement('section'); section.className = 'plan';
  const done = row.plan.filter(item => item.status === 'completed').length;
  const heading = document.createElement('div'); heading.className = 'plan-heading';
  heading.textContent = `Plan · ${done} of ${row.plan.length} done`;
  section.append(heading);
  if (row.explanation) {
    const note = document.createElement('div'); note.className = 'plan-note'; note.textContent = row.explanation;
    section.append(note);
  }
  const list = document.createElement('ol'); list.className = 'plan-steps';
  for (const item of row.plan) {
    const li = document.createElement('li'); li.className = `plan-step ${item.status}`;
    const mark = document.createElement('span'); mark.className = 'plan-mark'; mark.setAttribute('aria-hidden', 'true');
    mark.textContent = item.status === 'completed' ? '✓' : item.status === 'in_progress' ? '●' : '○';
    const text = document.createElement('span'); text.className = 'plan-text'; text.textContent = item.step;
    const state = document.createElement('span'); state.className = 'sr-only';
    state.textContent = item.status === 'completed' ? ' (done)' : item.status === 'in_progress' ? ' (in progress)' : ' (pending)';
    li.append(mark, text, state); list.append(li);
  }
  section.append(list);
  return section;
}

function createTimelineRow() {
  const node = document.createElement('div');
  node.className = 'timeline-row';
  return node;
}

function updateTimelineRow(node, row) {
  if (row.kind === 'work') {
    node.className = 'timeline-row work';
    let details = node.querySelector('details');
    if (!details) {
      details = document.createElement('details'); details.className = 'work-section';
      const summary = document.createElement('summary');
      const clock = document.createElement('span'); clock.className = 'work-clock';
      summary.append(clock); details.append(summary);
      const body = document.createElement('div'); body.className = 'work-body'; details.append(body);
      node.append(details);
      node.workRenderer = new KeyedRenderer(body, createTimelineRow, updateTimelineRow);
      details.ontoggle = () => { if (details.open && row.requestId && !state.busy) post('turnChanges', { requestId: row.requestId }); };
      details.open = row.live;
    }
    if (node.dataset.workLive === 'true' && !row.live) details.open = false;
    if (node.dataset.workLive !== 'true' && row.live) details.open = true;
    node.dataset.workLive = String(row.live);
    details.classList.toggle('running', row.live);
    const clock = details.querySelector('.work-clock');
    clock.dataset.startedAt = String(row.startedAt);
    clock.dataset.finishedAt = String(row.finishedAt || '');
    clock.dataset.live = String(row.live);
    clock.dataset.status = row.status;
    updateWorkClock(clock);
    const activity = row.rows.filter(item => item.kind !== 'control' || item.detail);
    node.workRenderer.reconcile(activity.length ? groupWorkRows(activity) : row.live
      ? [{ key: 'thinking', kind: 'control', detail: 'Thinking…' }] : []);
    return;
  }
  // Keyed nodes survive stream updates. Only the currently changing row is
  // rebuilt, so selection and disclosures in settled rows remain untouched.
  const wasOpen = node.querySelector('details')?.open || false;
  node.className = `timeline-row ${row.kind}`;
  let content;
  if (row.kind === 'user' || row.kind === 'assistant' || row.kind === 'answer' || row.kind === 'progress' || row.kind === 'checkpoint') {
    content = message(row.kind === 'user' ? 'user' : 'assistant', row.text || '');
  } else if (row.kind === 'reasoning') {
    content = reasoningSection(row.text || '', row.live);
  } else if (row.kind === 'plan') {
    content = planSection(row);
  } else if (row.kind === 'tool') {
    content = activitySection([{ name: row.name, ok: row.ok, detail: row.detail }], row.phase === 'running');
  } else if (row.kind === 'tool-group') {
    content = activitySection(row.items, row.live);
  } else if (row.kind === 'diff') {
    content = renderDiff(row.file);
  } else if (row.kind === 'empty') {
    content = document.createElement('section'); content.className = 'empty';
    const logo = document.createElement('img'); logo.src = $('logo-source').src || '';
    logo.alt = '';
    const name = document.createElement('span'); name.textContent = 'Jaeger';
    content.append(logo, name);
  } else {
    content = document.createElement('div'); content.className = 'subtle';
    content.textContent = row.detail || row.status || '';
  }
  const disclosure = content.matches?.('details') ? content : content.querySelector?.('details');
  if (disclosure) disclosure.open = row.kind === 'diff' ? true : wasOpen;
  node.replaceChildren(content);
}

const timelineRenderer = new KeyedRenderer($('timeline'), createTimelineRow, updateTimelineRow);

// Same elapsed-duration formatter and one-second clock as the Web UI's
// transparent turn / worked-for chip. Update labels without rebuilding text.
function updateWorkClock(clock) {
  if (!Number(clock.dataset.startedAt)) { clock.textContent = 'Work history'; return; }
  const live = clock.dataset.live === 'true';
  const end = Number(clock.dataset.finishedAt) || Date.now();
  const duration = window.JaegerTurnDuration.formatTurnDuration((end - Number(clock.dataset.startedAt)) / 1000);
  const status = clock.dataset.status;
  clock.textContent = `${live ? 'Working for' : status === 'completed' ? 'Worked for'
    : status === 'cancelled' ? 'Stopped after' : 'Interrupted after'} ${duration}`;
}
setInterval(() => {
  for (const clock of document.querySelectorAll('.work-clock[data-live="true"]')) updateWorkClock(clock);
}, 1000);

function renderModels() {
  const select = $('model');
  const rows = selectableModels(state.models);
  const signature = JSON.stringify(rows) + (state.modelsError || '') + (state.configuredModel || '') + (state.session?.model || '');
  if (signature === modelRevision) return;
  modelRevision = signature;
  const previous = select.value;
  select.replaceChildren(new Option(state.session?.model || 'Default model', ''));
  if (state.configuredModel) select.add(new Option(`From settings · ${state.configuredModel}`, 'config'));
  for (const row of rows) select.add(new Option(`${row.provider} · ${row.id}`, providerModelValue(row.provider, row.id)));
  // Restore an explicit prior selection when it is still valid; otherwise default
  // to the configured-model option so the display matches what will actually be sent.
  const valid = new Set(['', ...(state.configuredModel ? ['config'] : []), ...rows.map(r => providerModelValue(r.provider, r.id))]);
  select.value = valid.has(previous) ? previous : (state.configuredModel ? 'config' : '');
  select.title = state.modelsError ? `Couldn't load the model list: ${state.modelsError}` : 'Model';
  select.disabled = rows.length === 0 && !state.configuredModel;
}

function renderSessionTabs() {
  const container = $('session-tabs');
  const openIds = state.openSessionIds || [];
  container.replaceChildren(); container.hidden = !openIds.length;
  for (const id of openIds) {
    const session = (state.sessions || []).find(item => item.session_id === id);
    const title = session?.title || 'Untitled';
    const row = document.createElement('div');
    row.className = 'session-tab' + (state.session?.session_id === id ? ' active' : '');
    row.setAttribute('role', 'tab');
    row.setAttribute('aria-selected', String(state.session?.session_id === id));
    const select = document.createElement('button');
    select.type = 'button'; select.className = 'session-tab-select';
    select.title = title; select.textContent = title;
    select.onclick = () => post('select', { id });
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'session-tab-close';
    close.title = 'Close tab'; close.setAttribute('aria-label', `Close ${title}`);
    close.textContent = '×';
    close.onclick = () => post('closeSession', { id });
    row.append(select, close); container.append(row);
  }
}

function renderContextChips() {
  const container = $('context-chips');
  const context = state.ideContext || {};
  const diagnostics = Number(state.diagnostics || 0);
  const chips = [];
  const chip = (label, title, severity = '') => {
    const node = document.createElement('span');
    node.className = 'context-chip';
    if (severity) node.dataset.severity = severity;
    node.title = title; node.textContent = label;
    return node;
  };
  if (context.active_file) chips.push(chip(context.active_file, `Active file: ${context.active_file}`));
  if (context.selection) {
    const start = context.selection.start_line || context.selection.end_line || 1;
    const end = context.selection.end_line || start;
    chips.push(chip(start === end ? `Line ${start}` : `Lines ${start}–${end}`, 'Selection included in IDE context'));
  }
  if (context.open_files?.length) chips.push(chip(`${context.open_files.length} open files`, context.open_files.join(', ')));
  if (diagnostics) {
    const problems = document.createElement('button');
    problems.type = 'button';
    problems.className = 'context-chip';
    problems.dataset.severity = diagnostics >= 10 ? 'error' : 'warning';
    problems.title = 'Show workspace problems';
    problems.setAttribute('aria-label', 'Show workspace problems');
    problems.textContent = `${diagnostics} problem${diagnostics === 1 ? '' : 's'}`;
    problems.onclick = () => post('info', { what: 'diagnostics' });
    chips.push(problems);
  }
  container.replaceChildren(...chips);
  container.hidden = !chips.length;
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

function chatAge(session) {
  const raw = session.updated_at || session.created_at;
  if (!raw) return '';
  const stamp = typeof raw === 'number' ? raw * (raw < 100000000000 ? 1000 : 1) : Date.parse(raw);
  if (!Number.isFinite(stamp)) return '';
  const hours = Math.max(0, Math.floor((Date.now() - stamp) / 3600000));
  if (hours < 1) return 'now';
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function chatRow(session, selected) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `chat-row${session.session_id === selected ? ' active' : ''}`;
  button.setAttribute('aria-label', `Open chat ${session.title || 'Untitled'}`);
  const title = document.createElement('span'); title.className = 'chat-title';
  title.textContent = session.title || 'Untitled';
  const time = document.createElement('span'); time.className = 'chat-time';
  time.textContent = chatAge(session);
  button.append(title, time);
  button.onclick = () => post('select', { id: session.session_id });
  return button;
}

function archiveHeading() {
  const heading = document.createElement('div');
  heading.className = 'chat-archive-label';
  heading.textContent = 'Archived';
  return heading;
}

function renderChats() {
  const container = $('chat-list');
  const searching = Boolean(chatSearch.trim());
  const sessions = filterChats(state.sessions || [], chatSearch);
  const selected = state.session?.session_id || '';
  const active = sessions.filter(session => !session.metadata?.archived);
  const archived = sessions.filter(session => Boolean(session.metadata?.archived));
  const visibleActive = searching ? active : showAllChats ? active : active.slice(0, 3);
  const nodes = visibleActive.map(session => chatRow(session, selected));
  if (!searching && active.length > 3) {
    const more = document.createElement('button'); more.type = 'button'; more.className = 'chat-more';
    more.textContent = showAllChats ? 'Show less' : `View all (${active.length})`;
    more.onclick = () => { showAllChats = !showAllChats; renderChats(); };
    nodes.push(more);
  }
  if (searching && !nodes.length) {
    const empty = document.createElement('div');
    empty.className = 'chat-empty';
    empty.textContent = 'No chats match this search.';
    nodes.push(empty);
  }
  if (archived.length) {
    nodes.push(archiveHeading());
    nodes.push(...archived.map(session => chatRow(session, selected)));
  }
  container.replaceChildren(...nodes);
  const hasConversation = Boolean((state.session?.messages || []).length || state.busy);
  $('chat-home').className = `chat-home${hasConversation ? ' in-conversation' : ''}`;
}

function renderBackgroundTasks() {
  const container = $('background-tasks');
  container.replaceChildren(); container.hidden = !(state.backgroundTasks || []).length;
  for (const task of state.backgroundTasks || []) {
    const row = document.createElement('div'); row.className = 'background-task';
    const open = document.createElement('button'); open.append(icon('integration'));
    const label = document.createElement('span'); label.textContent = `${task.state} · ${task.goal}`;
    open.append(label); open.title = task.error || task.goal;
    open.onclick = () => post('select', { id: `task:${task.task_id}` });
    row.append(open);
    if (!['failed', 'cancelled', 'completed'].includes(task.state)) {
      const cancel = document.createElement('button'); cancel.textContent = 'Stop';
      cancel.setAttribute('aria-label', `Stop background task: ${task.goal}`);
      cancel.onclick = () => post('cancelBackgroundTask', { id: task.task_id }); row.append(cancel);
    }
    container.append(row);
  }
}

function render() {
  $('status').textContent = state.error || !state.connected || /Cancellation|approval|Submitting/.test(state.status || '') ? (state.status || '') : '';
  const inChat = Boolean(state.session);
  $('chat-heading').textContent = inChat ? state.session.title || 'New chat' : 'Chats';
  $('back').hidden = !inChat;
  $('prompt').placeholder = inChat ? 'Ask for follow-up changes' : 'Ask Jaeger anything';
  $('error').hidden = !state.error; $('error').textContent = state.error || '';
  const sid = state.session?.session_id || '';
  if (draftSession !== sid) { saveDraft(); draftSession = sid; $('prompt').value = drafts[sid] || ''; state.preview = null; state.changes = null; }
  const sessionOptions = JSON.stringify(state.sessions || []) + sid
    + Boolean((state.session?.messages || []).length || state.busy);
  if (revision !== sessionOptions) { revision = sessionOptions; renderChats(); }
  $('context').textContent = state.session?.workspace ? state.session.workspace.split('/').filter(Boolean).at(-1) : 'Work locally';
  $('stop').hidden = !state.busy || !state.canCancel; eligibility(); renderComposerBar();
  $('attach').disabled = !state.connected || state.busy;
  renderSessionTabs(); renderModels(); renderStaged(); renderContextChips();

  timelineRenderer.reconcile(transcriptRows());
  renderChanges();
  renderBackgroundTasks();
  renderQueue();

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

let changesRevision = '';
function renderChanges() {
  const files = state.changes?.files || [];
  const signature = JSON.stringify(state.changes) + state.busy;
  if (signature === changesRevision) return;
  changesRevision = signature;
  const container = $('changes'); container.replaceChildren(); container.hidden = !files.length;
  if (!files.length) return;
  const heading = document.createElement('div'); heading.className = 'changes-heading';
  const badge = document.createElement('span'); badge.className = 'changes-icon'; badge.append(icon('file'));
  const title = document.createElement('div'); title.className = 'changes-title';
  const name = document.createElement('div'); name.textContent = `${state.changes.undone ? 'Undid edits to' : 'Edited'} ${files.length} ${files.length === 1 ? 'file' : 'files'}`;
  const note = document.createElement('small'); note.textContent = state.changes.undone ? 'Original contents restored' : 'Selected turn · recorded file-tool edits';
  title.append(name, note, changeCounts(files));
  const undo = document.createElement('button'); undo.textContent = 'Undo ↶'; undo.disabled = state.busy || !state.changes.canUndo;
  undo.title = undo.disabled ? 'Undo unavailable while running, after undo, or when files have newer changes.' : 'Undo this turn’s recorded edits';
  undo.onclick = () => post('undoChanges');
  const review = document.createElement('button'); review.textContent = 'Review'; review.className = 'review';
  review.onclick = () => post('reviewChanges'); heading.append(badge, title, undo, review); container.append(heading);
  const list = document.createElement('div'); list.className = 'changes-files'; container.append(list);
  function addFile(file) {
    const row = document.createElement('button'); row.className = 'changed-file'; row.title = file.path;
    const path = document.createElement('span'); path.textContent = file.path;
    row.append(path, changeCounts([file])); row.onclick = () => post('previewChange', { path: file.path }); list.append(row);
  }
  files.slice(0, 3).forEach(addFile);
  if (files.length > 3) {
    const more = document.createElement('button'); more.className = 'changes-more'; more.textContent = `Show ${files.length - 3} more files ⌄`;
    more.setAttribute('aria-expanded', 'false');
    more.onclick = () => {
      const expanded = more.getAttribute('aria-expanded') === 'true';
      list.replaceChildren(); (expanded ? files.slice(0, 3) : files).forEach(addFile);
      more.setAttribute('aria-expanded', String(!expanded)); more.textContent = expanded ? `Show ${files.length - 3} more files ⌄` : 'Show fewer files ⌃';
    };
    container.append(more);
  }
}
function changeCounts(files) {
  const counts = document.createElement('span'); counts.className = 'change-counts';
  if (files.length === 1 && files[0].added === null) { counts.textContent = 'Binary'; return counts; }
  const plus = document.createElement('span'); plus.className = 'added'; plus.textContent = '+' + files.reduce((n, f) => n + (f.added || 0), 0);
  const minus = document.createElement('span'); minus.className = 'removed'; minus.textContent = '−' + files.reduce((n, f) => n + (f.removed || 0), 0);
  counts.append(plus, minus); return counts;
}

function renderDiff(file) {
  const details = document.createElement('details'); details.className = 'inline-diff';
  const summary = document.createElement('summary'); summary.append(icon('edit'));
  const label = document.createElement('span'); label.textContent = 'Edited file'; summary.append(label); details.append(summary);
  const card = document.createElement('section'); card.className = 'diff-card';
  const header = document.createElement('div'); header.className = 'diff-header';
  const name = document.createElement('span'); name.textContent = file.path.split('/').at(-1); name.title = file.path;
  const review = document.createElement('button'); review.textContent = 'Open diff'; review.onclick = () => post('reviewChanges', { path: file.path });
  header.append(name, changeCounts([file]), review, copyButton(file.diff || ''));
  const lines = document.createElement('div'); lines.className = 'diff-lines'; lines.tabIndex = 0; lines.setAttribute('aria-label', `Changes to ${file.path}`);
  for (const line of diffLines(file.diff)) {
    const row = document.createElement('div'); row.className = `diff-line ${line.kind}`;
    for (const number of [line.oldLine, line.newLine]) { const gutter = document.createElement('span'); gutter.className = 'line-number'; gutter.textContent = number ?? ''; row.append(gutter); }
    const code = document.createElement('code'); code.textContent = line.text; row.append(code); lines.append(row);
  }
  card.append(header, lines); details.append(card); return details;
}

const stateQueue = createFrameQueue(batch => {
  const data = batch.at(-1);
  if (data.editDraft !== undefined) { $('prompt').value = data.editDraft; saveDraft(); eligibility(); $('prompt').focus(); return; }
  if (data.steerRejected !== undefined) { $('prompt').value = data.steerRejected; saveDraft(); eligibility(); $('prompt').focus(); return; }
  if (data.mention !== undefined) {
    const prompt = $('prompt');
    prompt.value = `${prompt.value}${prompt.value ? ' ' : ''}${data.mention} `;
    saveDraft(); eligibility(); prompt.focus();
    return;
  }
  if (data.accepted) {
    if (submittedDraftSession !== null && String(drafts[submittedDraftSession] || '').trim() === data.submittedText) {
      drafts[submittedDraftSession] = '';
    }
    submittedDraftSession = null;
    if ($('prompt').value.trim() === data.submittedText) $('prompt').value = '';
    saveDraft(); eligibility(); return;
  }
  if (data.changes && data.changes.requestId !== state.preview?.requestId) state.preview = null;
  state = { ...state, ...data }; render();
  if (data.preview) $('timeline').querySelector('.inline-diff')?.scrollIntoView({ block: 'end' });
}, data => data.updateKind === 'stream');

// A command result is a local card, not a conversation message: it is never
// sent to the Gateway or stored in the session, and closes with one click.
function showInfo(info) {
  const box = $('info');
  const heading = document.createElement('div'); heading.className = 'info-heading';
  const title = document.createElement('span'); title.textContent = String(info.title || 'Result');
  const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-button';
  close.setAttribute('aria-label', 'Close'); close.textContent = '×'; close.onclick = () => { box.hidden = true; box.replaceChildren(); };
  heading.append(title, close);
  const body = document.createElement('div'); body.className = 'info-lines';
  for (const line of info.lines || []) { const row = document.createElement('div'); row.textContent = String(line); body.append(row); }
  box.replaceChildren(heading, body); box.hidden = false;
}

window.addEventListener('message', ({ data }) => { if (data?.info) showInfo(data.info); else stateQueue.push(data); });

// ── composer bar: permission pill + IDE-context toggle ─────────────────────
const ACCESS = {
  auto: { label: 'Full access', hint: 'No approval prompts. Catastrophic commands are still blocked.' },
  scoped: { label: 'Ask once', hint: 'Ask the first time for each kind of action.' },
  ask: { label: 'Ask each time', hint: 'Ask before every action that changes something.' },
};

function renderComposerBar() {
  $('queue-next').hidden = !state.busy || !state.session || Boolean(editingQueueId);
  $('send').title = editingQueueId ? 'Save queued request'
    : state.busy ? 'Steer current turn' : 'Send message';
  $('send').setAttribute('aria-label', $('send').title);
  const workspaceLabel = state.selectedWorkspace ? state.selectedWorkspace.split('/').filter(Boolean).at(-1) : 'Workspace';
  $('workspace-label').textContent = workspaceLabel;
  $('workspace').title = state.selectedWorkspace || 'Choose the workspace Jaeger should use';
  const mode = state.autonomy?.mode;
  const pill = $('access');
  pill.hidden = !ACCESS[mode];
  if (ACCESS[mode]) {
    $('access-label').textContent = ACCESS[mode].label;
    pill.classList.toggle('full', mode === 'auto');
  }
  $('ide-context').setAttribute('aria-pressed', String(ideContextOn));
  $('plan-mode').setAttribute('aria-pressed', String(planModeOn));
}

function closeAccessMenu() {
  $('access-menu').hidden = true; $('access').setAttribute('aria-expanded', 'false');
}

function openAccessMenu() {
  const menu = $('access-menu');
  menu.replaceChildren(...Object.keys(ACCESS).filter(name => (state.autonomy?.options || []).includes(name)).map(name => {
    const row = document.createElement('div');
    row.className = 'slash-item'; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(name === state.autonomy.mode));
    const label = document.createElement('span'); label.className = 'access-name'; label.textContent = ACCESS[name].label;
    const hint = document.createElement('span'); hint.className = 'slash-description'; hint.textContent = ACCESS[name].hint;
    row.append(label, hint);
    row.onmousedown = event => { event.preventDefault(); closeAccessMenu(); if (name !== state.autonomy.mode) post('setAutonomy', { mode: name }); };
    return row;
  }));
  menu.hidden = false; $('access').setAttribute('aria-expanded', 'true');
}

$('access').onclick = () => ($('access-menu').hidden ? openAccessMenu() : closeAccessMenu());
$('access').onblur = () => closeAccessMenu();
$('ide-context').onclick = () => { ideContextOn = !ideContextOn; persistView(); renderComposerBar(); };
$('workspace').onclick = () => post('selectWorkspace');
$('worktree').onclick = () => post('selectWorktree');
$('plan-mode').onclick = () => { planModeOn = !planModeOn; persistView(); renderComposerBar(); };
$('queue-next').onclick = () => {
  const text = $('prompt').value;
  if (!text.trim() || $('queue-next').hidden) return;
  post('queue', { text, model: $('model').value, ideContext: ideContextOn, planOnly: planModeOn });
  $('prompt').value = ''; saveDraft(); eligibility(); slashDismissed = false; renderSlashMenu();
};

// ── slash commands ─────────────────────────────────────────────────────────
let slashItems = [], slashIndex = 0, slashDismissed = false;

function slashContext() {
  const answer = [...(state.session?.messages || [])].reverse()
    .find(item => item.role === 'assistant' && String(item.content || '').trim());
  return { session: Boolean(state.session), busy: Boolean(state.busy),
    changes: Boolean(state.changes?.files?.length), answer: Boolean(answer), lastAnswer: answer?.content || '' };
}

function renderSlashMenu() {
  const menu = $('slash-menu'), prompt = $('prompt');
  slashItems = slashDismissed ? [] : matchSlash(prompt.value, slashContext());
  if (!slashItems.length) {
    menu.hidden = true; menu.replaceChildren(); prompt.removeAttribute('aria-activedescendant'); return;
  }
  slashIndex = Math.min(slashIndex, slashItems.length - 1);
  menu.replaceChildren(...slashItems.map((command, index) => {
    const row = document.createElement('div');
    row.id = `slash-${command.name}`; row.className = 'slash-item'; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(index === slashIndex));
    const name = document.createElement('span'); name.className = 'slash-name';
    name.textContent = `/${command.name}${command.args ? ` ${command.args}` : ''}`;
    const text = document.createElement('span'); text.className = 'slash-description'; text.textContent = command.description;
    row.append(name, text);
    row.onmousedown = event => { event.preventDefault(); acceptSlash(index); };
    return row;
  }));
  menu.hidden = false;
  prompt.setAttribute('aria-activedescendant', `slash-${slashItems[slashIndex].name}`);
  menu.children[slashIndex]?.scrollIntoView?.({ block: 'nearest' });
}

function clearComposer() {
  $('prompt').value = ''; saveDraft(); eligibility(); slashDismissed = false; renderSlashMenu();
}

function runSlash(command, args) {
  const context = slashContext();
  clearComposer();
  switch (command.name) {
    case 'new': return post('new');
    case 'resume': return post('home');
    case 'rename': return post('rename', { title: args });
    case 'stop': return post('cancel');
    case 'copy': announceCopied(); return post('copy', { text: context.lastAnswer });
    case 'export': return post('exportChat');
    case 'archive': return post('archive');
    case 'unarchive': return post('unarchive');
    case 'model': return $('model').focus();
    case 'workspace': return post('selectWorkspace');
    case 'worktree': return post('selectWorktree');
    case 'plan': return args.trim() ? post('send', { text: args, model: $('model').value, ideContext: ideContextOn, planOnly: true }) : undefined;
    case 'diagnostics': return post('info', { what: 'diagnostics' });
    case 'diff': return post('reviewChanges');
    case 'status': return post('info', { what: 'status' });
    case 'skills': return post('info', { what: 'skills', query: args });
    case 'agent': return post('info', { what: 'agent' });
    case 'workers': return post('info', { what: 'workers' });
    default: return undefined;
  }
}

// A command that takes text completes to "/name " and waits; the rest run at once.
function acceptSlash(index) {
  const command = slashItems[index];
  if (!command) return;
  if (command.takesArgs) {
    $('prompt').value = `/${command.name} `; saveDraft(); eligibility(); renderSlashMenu(); $('prompt').focus();
  } else runSlash(command, '');
}
$('composer').onsubmit = event => {
  event.preventDefault();
  const invocation = parseSlash($('prompt').value, slashContext());
  if (invocation) return runSlash(invocation.command, invocation.args);
  // Always send the picker's current value. The extension interprets '' as
  // keep-session, 'config' as the static setting, and 'provider::model' as
  // an explicit catalog choice — the display matches the behaviour.
  if (!$('send').disabled) {
    const text = $('prompt').value;
    if (editingQueueId) {
      const id = editingQueueId; editingQueueId = null;
      post('queueUpdate', { id, text });
      $('prompt').value = ''; saveDraft(); eligibility(); renderQueue(); renderComposerBar();
      return;
    }
    if (state.busy) { post('steer', { text }); $('prompt').value = ''; saveDraft(); eligibility(); return; }
    submittedDraftSession = draftSession;
    post('send', { text, model: $('model').value, ideContext: ideContextOn, planOnly: planModeOn });
  }
};
$('prompt').oninput = () => { saveDraft(); eligibility(); slashDismissed = false; slashIndex = 0; renderSlashMenu(); };
$('prompt').onkeydown = event => {
  if (!$('slash-menu').hidden) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      slashIndex = (slashIndex + (event.key === 'ArrowDown' ? 1 : -1) + slashItems.length) % slashItems.length;
      return renderSlashMenu();
    }
    if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey && !event.isComposing)) {
      event.preventDefault(); return acceptSlash(slashIndex);
    }
    if (event.key === 'Escape') { event.preventDefault(); slashDismissed = true; return renderSlashMenu(); }
  }
  if (event.key === 'Escape' && editingQueueId) {
    event.preventDefault(); editingQueueId = null;
    $('prompt').value = drafts[draftSession] || ''; saveDraft(); eligibility(); renderQueue(); renderComposerBar();
    return;
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); }
};
$('prompt').onblur = () => { slashDismissed = true; renderSlashMenu(); };
$('attach').onclick = () => post('attach');
$('mention').onclick = () => post('mentionFile');
for (const [id, type] of [['new', 'new'], ['refresh', 'refresh'], ['settings', 'settings'], ['stop', 'cancel']]) $(id).onclick = () => post(type);
$('chat-search').oninput = event => {
  chatSearch = event.target.value;
  persistView();
  renderChats();
};
$('chat-search').value = chatSearch;
$('back').onclick = () => post('home');
post('ready');
})();
