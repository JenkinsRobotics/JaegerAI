'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const slash = require('../media/slash-commands');
const commands = require('../commands');

const idle = { session: true, answer: true, changes: false, busy: false };
const names = list => list.map(command => command.name);

test('typing "/" offers only commands usable right now', () => {
  assert.deepEqual(names(slash.match('/', idle)).sort(),
    ['agent', 'archive', 'copy', 'diagnostics', 'export', 'model', 'new', 'plan', 'rename', 'resume', 'skills', 'status', 'unarchive', 'workers', 'workspace', 'worktree'].sort());
  assert.ok(!names(slash.match('/', idle)).includes('stop'), 'stop needs a running turn');
  assert.ok(!names(slash.match('/', idle)).includes('diff'), 'diff needs recorded changes');
  const busy = slash.match('/', { ...idle, busy: true, changes: true });
  assert.ok(names(busy).includes('stop') && names(busy).includes('diff'));
});

test('a fresh window with no conversation hides commands that need one', () => {
  const none = names(slash.match('/', { session: false, answer: false, changes: false, busy: false }));
  for (const hidden of ['rename', 'copy', 'export', 'stop', 'diff']) assert.ok(!none.includes(hidden), hidden);
  assert.ok(none.includes('new') && none.includes('status'));
});

test('prefix matches rank before substring matches; aliases match', () => {
  assert.deepEqual(names(slash.match('/re', idle)).slice(0, 2).sort(), ['rename', 'resume']);
  assert.equal(names(slash.match('/ps', idle))[0], 'agent');
  assert.deepEqual(slash.match('/zzz', idle), []);
});

test('the menu closes once a space or newline follows the command word, and for plain text', () => {
  assert.deepEqual(slash.match('/rename my chat', idle), []);
  assert.deepEqual(slash.match('hello /new', idle), []);
  assert.deepEqual(slash.match('', idle), []);
});

test('parse recognises exact commands and extracts arguments', () => {
  assert.deepEqual(slash.parse('/new', idle).command.name, 'new');
  const rename = slash.parse('  /rename  Fix the login loop ', idle);
  assert.equal(rename.command.name, 'rename');
  assert.equal(rename.args, 'Fix the login loop');
  assert.equal(slash.parse('/PS', idle).command.name, 'agent');
  assert.equal(slash.parse('/skills pdf', idle).args, 'pdf');
});

test('anything that is not exactly a usable command is an ordinary message', () => {
  assert.equal(slash.parse('/usr/local/bin is on my PATH', idle), null);
  assert.equal(slash.parse('/new please', idle), null, 'no-argument command with trailing text');
  assert.equal(slash.parse('/nosuch', idle), null);
  assert.equal(slash.parse('/stop', idle), null, 'not usable while idle');
  assert.equal(slash.parse('hello', idle), null);
  assert.equal(slash.parse('/rename', { ...idle, session: false }), null);
});

test('every command names a group and a description, and names are unique', () => {
  const seen = new Set();
  for (const command of slash.COMMANDS) {
    assert.ok(command.group && command.description.length > 5, command.name);
    for (const name of [command.name, ...(command.aliases || [])]) { assert.ok(!seen.has(name), name); seen.add(name); }
  }
});

test('status lines describe the gateway, model and conversation', () => {
  const lines = commands.statusLines({
    version: { component: 'jaeger-gateway', version: '0.11.0' }, endpoint: 'http://127.0.0.1:8810',
    model: 'kimi-k2.7-code:cloud',
    session: { title: 'Fix loop', messages: [{}, {}, {}], workspace: '/w', status: 'idle' },
  });
  assert.deepEqual(lines, ['Gateway: jaeger-gateway 0.11.0', 'Endpoint: http://127.0.0.1:8810',
    'Model: kimi-k2.7-code:cloud', 'Conversation: Fix loop', 'Messages: 3', 'Workspace: /w', 'State: idle']);
  assert.ok(commands.statusLines({ version: {} }).includes('Conversation: none open'));
});

test('skill lines group by category and explain how to filter', () => {
  const skills = Array.from({ length: 30 }, (_, i) => ({ name: `s${i}`, category: `cat${i % 15}` }));
  const lines = commands.skillLines(skills);
  assert.equal(lines[0], '30 skills');
  assert.ok(lines.length <= 14 && lines.at(-1).includes('/skills pdf'));
  assert.deepEqual(commands.skillLines([], 'zzz'), ['No skills match “zzz”.']);
  assert.equal(commands.skillLines([{ name: 'a', category: 'x' }], 'a')[0], '1 skill matching “a”');
});

test('task lines are bounded and tolerate either payload shape', () => {
  assert.deepEqual(commands.taskLines({ tasks: [] }), ['No background agents or tasks.']);
  const lines = commands.taskLines(Array.from({ length: 40 }, (_, i) =>
    ({ task_id: `task_${i}abcdefghijklmnop`, status: 'running', objective: 'x'.repeat(500) })));
  assert.equal(lines.length, 15);
  assert.ok(lines[0].length < 140);
});

test('worker lines summarize orchestration worker availability and capabilities', () => {
  assert.deepEqual(commands.workerLines([]), ['No orchestration workers are registered.']);
  const lines = commands.workerLines({ workers: [
    { worker_id: 'codex', available: true, capabilities: ['code', 'filesystem'] },
    { worker_id: 'claude', available: false, detail: 'executable not found: claude' },
  ]});
  assert.equal(lines[0], '2 orchestration workers');
  assert.equal(lines[1], 'codex · available · code, filesystem');
  assert.equal(lines[2], 'claude · unavailable · executable not found: claude');
  assert.equal(slash.parse('/workers', idle).command.name, 'workers');
});

test('export writes a Markdown transcript of user and assistant turns only', () => {
  const md = commands.exportMarkdown({ title: 'Plan', messages: [
    { role: 'user', content: 'hi' }, { role: 'tool', content: 'SECRET' }, { role: 'assistant', content: 'hello\n' },
  ] });
  assert.equal(md, '# Plan\n\n## You\n\nhi\n\n## Jaeger\n\nhello\n');
  assert.equal(commands.slug('Fix: the Login!! loop'), 'fix-the-login-loop');
  assert.equal(commands.slug('***'), 'conversation');
});

test('IDE context: active file and selection are relative to the workspace and bounded', () => {
  const ctx = commands.buildIdeContext({
    folders: ['/w/proj'],
    active: { path: '/w/proj/src/app.py', language: 'python', cursorLine: 12,
      selectionText: 'def f():\n  return 1', startLine: 10, endLine: 11 },
    openPaths: ['/w/proj/src/app.py', '/w/proj/README.md', '/w/proj/README.md', '/elsewhere/notes.txt'],
  });
  assert.equal(ctx.active_file, 'src/app.py');
  assert.deepEqual(ctx.selection, { text: 'def f():\n  return 1', truncated: false, start_line: 10, end_line: 11 });
  assert.deepEqual(ctx.open_files, ['README.md', '/elsewhere/notes.txt']);
  assert.equal(ctx.cursor_line, 12);
  assert.deepEqual(ctx.workspace_folders, ['/w/proj']);
});

test('IDE context: a long selection and many tabs are truncated; nothing open gives null', () => {
  const ctx = commands.buildIdeContext({
    folders: ['/w'], active: { path: '/w/a.py', selectionText: 'x'.repeat(9000) },
    openPaths: Array.from({ length: 50 }, (_, i) => `/w/f${i}.py`),
  });
  assert.equal(ctx.selection.text.length, commands.IDE_LIMITS.selection);
  assert.equal(ctx.selection.truncated, true);
  assert.equal(ctx.open_files.length, commands.IDE_LIMITS.openFiles);
  assert.equal(commands.buildIdeContext({}), null);
  assert.equal(commands.buildIdeContext({ active: { path: '/x/y.py', selectionText: '   ' } }).selection, undefined);
});
