'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const media = path.join(__dirname, '..', 'media');
const css = fs.readFileSync(path.join(media, 'motion.css'), 'utf8');
const html = fs.readFileSync(path.join(media, 'index.html'), 'utf8');
const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');

test('motion stylesheet is loaded by the panel and substituted by the extension', () => {
  assert.match(html, /href="\{\{MOTION\}\}"/);
  assert.match(extension, /MOTION: asset\('motion\.css'\)/);
  assert.match(extension, /\(CSP\|NONCE\|CSS\|MOTION\|/);
});

test('every animation the motion layer uses is defined', () => {
  const defined = new Set([...css.matchAll(/@keyframes\s+([\w-]+)/g)].map(m => m[1]));
  const used = [...css.matchAll(/animation:\s*([\w-]+)/g)].map(m => m[1]);
  assert.ok(used.length > 5);
  for (const name of used) assert.ok(defined.has(name), `undefined keyframes: ${name}`);
});

test('reduced-motion preference disables animation and the text shimmer', () => {
  const block = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(block, /animation-duration:\s*\.001ms\s*!important/);
  assert.match(block, /work-clock/);
  assert.match(block, /color:\s*inherit/);
});

test('motion layer targets only classes the panel actually renders', () => {
  const rendered = fs.readFileSync(path.join(media, 'view.js'), 'utf8') + html
    + fs.readFileSync(path.join(media, 'view.css'), 'utf8');
  for (const cls of ['work-clock', 'activity-label', 'work-body', 'approval', 'message-actions', 'send-button', 'background-task']) {
    assert.ok(rendered.includes(cls), `class no longer exists in the panel: ${cls}`);
  }
});
