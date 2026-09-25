'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { filterChats } = require('../media/presentation');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

test('filterChats matches a Gateway session projection case-insensitively', () => {
  const sessions = [
    { session_id: 'chat-one', title: 'Fix the IDE', workspace: '/repo/ide' },
    { session_id: 'chat-two', title: 'Plan the release', workspace: '/repo/web' },
  ];
  assert.deepEqual(filterChats(sessions, 'ide').map(row => row.session_id), ['chat-one']);
  assert.deepEqual(filterChats(sessions, 'WEB').map(row => row.session_id), ['chat-two']);
  assert.deepEqual(filterChats(sessions, 'nope'), []);
  assert.deepEqual(filterChats(sessions, ' '), sessions);
  assert.deepEqual(filterChats(undefined, 'fix'), []);
});

test('the chat list exposes a real search input and no-match state', () => {
  const html = read('media/index.html');
  const view = read('media/view.js');
  const css = read('media/view.css');
  assert.match(html, /id="chat-search"/);
  assert.match(view, /filterChats\(state\.sessions \|\| \[\], chatSearch\)/);
  assert.match(view, /No chats match this search\./);
  assert.match(css, /\.chat-search\{/);
  assert.match(css, /\.chat-empty\{/);
});
