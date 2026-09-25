'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parse } = require('../media/slash-commands');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

test('the IDE exposes a real workspace picker control', () => {
  const html = read('media/index.html');
  const view = read('media/view.js');
  const extension = read('extension.js');
  assert.match(html, /id="workspace"/);
  assert.match(view, /post\('selectWorkspace'\)/);
  assert.match(view, /selectedWorkspace/);
  assert.match(extension, /showWorkspaceFolderPick/);
  assert.match(extension, /selectedWorkspace, message\.ideContext === false/);
});

test('/workspace opens the real workspace picker', () => {
  const parsed = parse('/workspace', {});
  assert.equal(parsed.command.name, 'workspace');
  const view = read('media/view.js');
  assert.match(view, /case 'workspace': return post\('selectWorkspace'\)/);
});

test('workspace selection is persisted per Gateway endpoint and used for queued work', () => {
  const extension = read('extension.js');
  assert.match(extension, /workspaceStorageKey = \(\) => `workspace:\$\{endpoint\(\)\}`/);
  assert.match(extension, /context\.workspaceState\.update\(workspaceStorageKey\(\), selectedWorkspace\)/);
  assert.match(extension, /controller\.queue\(message\.text, model, provider, selectedWorkspace/);
});
