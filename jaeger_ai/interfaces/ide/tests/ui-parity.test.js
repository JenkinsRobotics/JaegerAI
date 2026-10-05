'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const media = path.join(__dirname, '..', 'media');
const read = name => fs.readFileSync(path.join(media, name), 'utf8');

test('the chat shell exposes the compact thread and composer controls', () => {
  const html = read('index.html');
  for (const id of ['back', 'chat-heading', 'refresh', 'settings', 'new', 'attach', 'mention',
    'mode-switch', 'autonomy-subswitch', 'model-trigger', 'ide-context', 'stop', 'send',
    'workspace', 'worktree']) {
    assert.match(html, new RegExp(`id="${id}"`), `missing chat control: ${id}`);
  }
  assert.match(html, /class="execution-row"/);
  assert.match(html, /Enter to send · Shift\+Enter for newline/);
});

test('the panel follows IDE theme tokens instead of forcing a branded dark theme', () => {
  const css = read('view.css');
  assert.match(css, /--surface:var\(--vscode-input-background/);
  assert.match(css, /background:var\(--vscode-sideBar-background/);
  assert.doesNotMatch(css, /WEB UI PREMIUM TOKENS/);
  assert.doesNotMatch(css, /--vscode-sideBar-background:.*!important/);
  assert.doesNotMatch(css, /backdrop-filter/);
});

test('the composer auto-grows while preserving Enter and Shift+Enter behavior', () => {
  const view = read('view.js');
  assert.match(view, /function resizePrompt\(\)/);
  assert.match(view, /Math\.min\(prompt\.scrollHeight/);
  assert.match(view, /event\.key === 'Enter' && !event\.shiftKey/);
});

test('advanced composer controls collapse behind one compact control', () => {
  const html = read('index.html');
  const view = read('view.js');
  assert.match(html, /id="composer-controls-toggle"/);
  assert.match(html, /id="composer-options"/);
  assert.match(view, /function setComposerExpanded\(open\)/);
  assert.match(view, /aria-expanded/);
  assert.match(view, /model-trigger.*ide-context.*queue-next/);
});

test('message actions expose copy, feedback, and fork operations', () => {
  const view = read('view.js');
  assert.match(view, /title = 'Copy message'/);
  assert.match(view, /title = 'Edit and resend'/);
  assert.match(view, /post\('editMessage'/);
  assert.match(view, /Good response/);
  assert.match(view, /Needs improvement/);
  assert.match(view, /meta\.feedback/);
  assert.match(view, /data\.feedback/);
  assert.match(view, /Retry response/);
  assert.match(view, /Fork conversation here/);
});

test('composer groups attachments, execution controls, send, and location metadata', () => {
  const html = read('index.html');
  assert.match(html, /class="composer-bar"[\s\S]*id="attach"[\s\S]*id="send"/);
  assert.match(html, /class="execution-row"[\s\S]*id="workspace"[\s\S]*id="worktree"/);
  assert.match(html, /id="prompt"[^>]*aria-controls="slash-menu"/);
});

test('chat search is wired to Gateway transcript search', () => {
  const gateway = fs.readFileSync(path.join(__dirname, '..', 'gateway.js'), 'utf8');
  const conversation = fs.readFileSync(path.join(__dirname, '..', 'conversation.js'), 'utf8');
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  assert.match(gateway, /sessions\(query = ''\)/);
  assert.match(conversation, /searchSessions\(query = ''\)/);
  assert.match(extension, /message\.type === 'searchChats'/);
});

test('transcript matches survive the client-side chat projection', () => {
  const presentation = fs.readFileSync(path.join(media, 'presentation.js'), 'utf8');
  assert.match(presentation, /if \(session\?\.search_match\) return true/);
});

test('editing a message creates a Gateway branch before resending', () => {
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  assert.match(extension, /message\.type === 'editMessage'/);
  assert.match(extension, /gateway\.branch\(id, \{ message_id: message\.messageId \}\)/);
  assert.match(extension, /controller\.send\(text\)/);
});
