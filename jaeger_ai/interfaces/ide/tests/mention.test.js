'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

test('the IDE exposes a real @ file-mention control', () => {
  const html = read('media/index.html');
  const view = read('media/view.js');
  const extension = read('extension.js');
  assert.match(html, /id="mention"/);
  assert.match(view, /post\('mentionFile'\)/);
  assert.match(view, /data\.mention/);
  assert.match(extension, /vscode\.workspace\.findFiles/);
  assert.match(extension, /controller\.addAttachment/);
  assert.match(extension, /mention: `@\$\{picked\.description\}`/);
});

test('@ mentions stage the picked file through the existing Gateway attachment contract', () => {
  const extension = read('extension.js');
  assert.match(extension, /if \(!controller\.state\.session\) await controller\.newSession/);
  assert.match(extension, /await controller\.addAttachment\(\{/);
  assert.match(extension, /view\?\.webview\.postMessage\(\{ mention:/);
});
