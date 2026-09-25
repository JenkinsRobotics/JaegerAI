'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parseWorktrees, worktreeLines } = require('../commands');
const { parse } = require('../media/slash-commands');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

test('parseWorktrees parses git worktree porcelain without fake entries', () => {
  const porcelain = [
    'worktree /repo/main',
    'HEAD 1234567890abcdef',
    'branch refs/heads/main',
    '',
    'worktree /repo/.worktrees/feature',
    'HEAD abcdef1234567890',
    'branch refs/heads/jaeger-subagent/feature',
    '',
    'worktree /repo/bare',
    'bare',
  ].join('\n');
  const rows = parseWorktrees(porcelain);
  assert.deepEqual(rows, [
    { path: '/repo/main', head: '1234567890abcdef', branch: 'main', bare: false, detached: false },
    { path: '/repo/.worktrees/feature', head: 'abcdef1234567890', branch: 'jaeger-subagent/feature', bare: false, detached: false },
  ]);
  assert.deepEqual(parseWorktrees(''), []);
  assert.deepEqual(parseWorktrees('\n \n'), []);
});

test('worktreeLines report the branch, worktree path, and empty state', () => {
  const rows = [
    { path: '/repo/main', head: '', branch: 'main', bare: false, detached: false },
    { path: '/repo/other', head: 'abcdef123456', branch: '', bare: false, detached: true },
  ];
  assert.deepEqual(worktreeLines(rows), [
    'main · /repo/main',
    'abcdef123456 · /repo/other',
  ]);
  assert.deepEqual(worktreeLines([]), ['No git worktrees found for the selected workspace.']);
});

test('/worktree is a real command and routes to the existing-worktree picker', () => {
  const parsed = parse('/worktree', {});
  assert.equal(parsed.command.name, 'worktree');
  const view = read('media/view.js');
  const extension = read('extension.js');
  assert.match(view, /post\('selectWorktree'\)/);
  assert.match(extension, /git.*worktree.*list.*porcelain|worktree.*list.*porcelain/);
  assert.match(extension, /selectedWorkspace = picked\.row\.path/);
});

test('the composer exposes a Worktree control backed by the picker route', () => {
  const html = read('media/index.html');
  const view = read('media/view.js');
  assert.match(html, /id="worktree"/);
  assert.match(view, /\$\('worktree'\)\.onclick = \(\) => post\('selectWorktree'\)/);
});
