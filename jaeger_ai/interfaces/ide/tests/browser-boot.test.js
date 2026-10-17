'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const media = path.join(__dirname, '..', 'media');
const scripts = [
  'frame-queue.js',
  'timeline.js',
  'keyed-renderer.js',
  'presentation.js',
  'turn-duration.js',
  'slash-commands.js',
  'markdown.js',
  'view.js',
];

function element() {
  return {
    value: '', disabled: false, hidden: false, textContent: '', title: '',
    children: [], dataset: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    replaceChildren(...items) { this.children = items; },
    querySelector(sel) {
      const cls = sel.startsWith('.') ? sel.slice(1) : '';
      const tag = !cls ? sel.toLowerCase() : '';
      const search = el => {
        for (const child of el.children || []) {
          if (cls && child.className?.split(' ').includes(cls)) return child;
          if (tag && child.tagName?.toLowerCase() === tag) return child;
          const found = search(child);
          if (found) return found;
        }
        return null;
      };
      return search(this);
    },
    querySelectorAll() { return this.children.filter(item => item.dataset?.value !== undefined); },
    classList: { add() {}, remove() {}, toggle() {} },
    insertBefore(item, before) { const index = this.children.indexOf(before); this.children.splice(index < 0 ? this.children.length : index, 0, item); },
    removeChild(item) { this.children.splice(this.children.indexOf(item), 1); },
    close() {},
    matches() { return false; },
    setAttribute() {},
    requestSubmit() {},
  };
}

function bootView() {
  const nodes = new Map();
  const messages = [];
  const listeners = [];
  const context = vm.createContext({
    console,
    URL,
    TextEncoder,
    TextDecoder,
    setTimeout,
    clearTimeout,
    setInterval: () => 1,
    requestAnimationFrame: callback => setTimeout(callback, 0),
    cancelAnimationFrame: clearTimeout,
    Option: function Option(text, value) { this.text = text; this.value = value; },
    document: {
      visibilityState: 'visible',
      getElementById(id) {
        if (!nodes.has(id)) nodes.set(id, element());
        return nodes.get(id);
      },
      createElement() { return element(); },
      createElementNS() { return element(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
    },
    acquireVsCodeApi() {
      return {
        getState: () => ({ drafts: {} }),
        setState() {},
        postMessage(message) { messages.push(message); },
      };
    },
  });
  context.window = context;
  context.window.addEventListener = (name, callback) => listeners.push({ name, callback });

  for (const filename of scripts) {
    const source = fs.readFileSync(path.join(media, filename), 'utf8');
    assert.doesNotThrow(
      () => vm.runInContext(source, context, { filename }),
      `${filename} must coexist with the earlier classic scripts`,
    );
  }
  return { nodes, messages, listeners, context };
}

test('classic browser scripts share one context and boot the webview once', () => {
  const { nodes, messages, listeners, context } = bootView();

  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'ready');
  assert.deepEqual(Object.keys(messages[0]), ['type']);
  assert.equal(listeners.filter(item => item.name === 'message').length, 1);
  assert.equal(typeof context.window.JaegerPresentation.groupActivity, 'function');
  assert.equal(typeof context.window.JaegerMarkdown.renderMarkdownOnce, 'function');
});

test('webview applies replayed connection state and renders a real transport error', () => {
  const { nodes, listeners } = bootView();
  const receive = data => listeners.find(item => item.name === 'message').callback({ data });
  receive({ connected: false, status: 'Connecting…', error: '' });
  assert.equal(nodes.get('status').textContent, 'Connecting…');
  receive({ connected: true, status: 'Connected', error: '', sessions: [], models: { providers: [] }, updateKind: 'stream' });
  assert.equal(nodes.get('status').textContent, '', 'healthy connection state should clear the pending status');
  receive({ connected: false, status: 'Unavailable · reconnecting', error: 'fetch failed' });
  assert.equal(nodes.get('status').textContent, 'Unavailable · reconnecting');
  assert.equal(nodes.get('error').textContent, 'fetch failed');
});

test('composer uses the saved default and preserves an unavailable explicit choice across catalog changes', () => {
  const { nodes, messages, listeners } = bootView();
  const receive = data => listeners.find(item => item.name === 'message').callback({ data });
  const catalog = { providers: [{ id: 'ollama-cloud', reachable: true,
    models: [{ id: 'fixture-default:cloud', available: true }, { id: 'fixture-override:cloud', available: true }] }] };
  receive({ connected: true, configuredModel: 'ollama-cloud::fixture-default:cloud', models: catalog });
  const submit = () => {
    nodes.get('prompt').value = 'synthetic turn';
    nodes.get('send').disabled = false;
    nodes.get('composer').onsubmit({ preventDefault() {} });
    return messages.at(-1);
  };
  assert.equal(submit().model, 'config', 'the saved default must be used without opening the picker');
  const override = nodes.get('model-list').children.find(item => item.dataset.value === 'ollama-cloud::fixture-override:cloud');
  override.onclick();
  receive({ models: { providers: [] }, endpoint: 'http://fixture-new-owner.local:8810' });
  assert.equal(submit().model, 'ollama-cloud::fixture-override:cloud', 'a catalog change must never silently select a fallback');
  assert.match(nodes.get('model-display').textContent, /fixture-override:cloud.*Unavailable/);
});

test('transcriptRows projects live streaming answers directly in the transcript and transitions cleanly to history without dropping content', () => {
  const { nodes, listeners, context } = bootView();
  const receive = data => listeners.find(item => item.name === 'message').callback({ data });
  const transcriptRows = context.window.JaegerTranscriptRows;
  assert.equal(typeof transcriptRows, 'function');

  // 1. Initial connected state with one user message and live streaming turn
  receive({
    connected: true,
    busy: true,
    session: {
      session_id: 's-1',
      messages: [{ role: 'user', content: 'What is the answer?' }],
    },
    workTurns: [{ requestId: 'req-1', userIndex: 0, startedAt: Date.now() }],
    timeline: [
      { requestId: 'req-1', kind: 'tool', name: 'search', ok: true },
      { requestId: 'req-1', kind: 'answer', text: 'Live streaming answer chunk' },
    ],
  });

  const liveRows = transcriptRows();
  // Live streaming answer should be projected as top-level assistant row, NOT hidden in workRow
  const liveAssistant = liveRows.find(r => r.kind === 'assistant');
  assert.ok(liveAssistant, 'live streaming answer must be present as kind: assistant');
  assert.equal(liveAssistant.live, true);
  assert.equal(liveAssistant.text, 'Live streaming answer chunk');
  assert.equal(liveAssistant.key, 'live:answer:req-1');

  // Work row should only contain tool/activity rows, NOT answer rows
  const workRow = liveRows.find(r => r.kind === 'work');
  assert.ok(workRow, 'work row must be present');
  assert.ok(workRow.rows.every(r => r.kind !== 'answer'), 'work row must not swallow answer rows');

  // 2. Settled turn with authoritative history
  receive({
    connected: true,
    busy: false,
    session: {
      session_id: 's-1',
      messages: [
        { role: 'user', content: 'What is the answer?' },
        { role: 'assistant', content: 'Live streaming answer chunk', id: 'msg-1' },
      ],
    },
    workTurns: [{ requestId: 'req-1', userIndex: 0, startedAt: Date.now(), finishedAt: Date.now() }],
    timeline: [
      { requestId: 'req-1', kind: 'tool', name: 'search', ok: true },
    ],
  });

  const settledRows = transcriptRows();
  const assistantRows = settledRows.filter(r => r.kind === 'assistant');
  assert.equal(assistantRows.length, 1, 'must have exactly one assistant message without duplication');
  assert.equal(assistantRows[0].live, false);
  assert.equal(assistantRows[0].text, 'Live streaming answer chunk');
  assert.match(assistantRows[0].key, /history:/);
});

test('renderChats populates chat-list from state.sessions', () => {
  const { nodes, listeners } = bootView();
  const receive = data => listeners.find(item => item.name === 'message').callback({ data });

  receive({
    connected: true,
    sessions: [
      { session_id: 's-1', title: 'First Conversation', updated_at: Date.now() },
      { session_id: 's-2', title: 'Second Conversation', updated_at: Date.now() - 3600000 },
    ],
  });

  const chatList = nodes.get('chat-list');
  assert.ok(chatList.children.length >= 2, 'chat-list should have child nodes for active sessions');
  const titles = chatList.children.map(c => c.children?.find(sub => sub.className === 'chat-title')?.textContent).filter(Boolean);
  assert.deepEqual(titles, ['First Conversation', 'Second Conversation']);
});

