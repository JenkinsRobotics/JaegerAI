'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  modelLabel, toolName, activityTitle, groupActivity, failureCount,
  statusLabel, groupTurns, selectableModels, providerModelValue, parseProviderModel,
} = require('../media/presentation');

test('modelLabel falls back to a prompt, never blank', () => {
  assert.equal(modelLabel('gpt-5'), 'gpt-5');
  assert.equal(modelLabel('  '), 'Choose model');
  assert.equal(modelLabel(undefined), 'Choose model');
});

test('toolName strips the mcp__server__ prefix and underscores', () => {
  assert.equal(toolName('mcp__filesystem__read_file'), 'read file');
  assert.equal(toolName('terminal_run'), 'terminal run');
});

test('activityTitle: singular tool, plural count, running vs settled wording', () => {
  assert.equal(activityTitle([], true), 'Working');
  assert.equal(activityTitle([], false), 'Activity');
  assert.equal(activityTitle([{ name: 'read_file' }], true), 'Using read file');
  assert.equal(activityTitle([{ name: 'read_file' }], false), 'Used read file');
  assert.equal(activityTitle([{ name: 'a' }, { name: 'b' }], true), 'Using 2 tools');
});

test('groupActivity: one group per uninterrupted run, split by non-tool events', () => {
  const events = [
    { name: 'tool.a' }, { name: 'tool.b' },
    {}, // a non-tool marker splits the run
    { name: 'tool.c' },
  ];
  const groups = groupActivity(events);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].map(e => e.name), ['tool.a', 'tool.b']);
  assert.deepEqual(groups[1].map(e => e.name), ['tool.c']);
});

test('groupActivity: empty input produces no groups, never a placeholder', () => {
  assert.deepEqual(groupActivity([]), []);
  assert.deepEqual(groupActivity(undefined), []);
});

test('failureCount ignores ok items and items still streaming', () => {
  const items = [{ ok: true }, { ok: false }, { ok: false, isStreaming: true }];
  assert.equal(failureCount(items), 1);
});

test('statusLabel: precedence is connection, approval, busy, then last outcome', () => {
  assert.equal(statusLabel({ connected: false, busy: true }), 'Not connected');
  assert.equal(statusLabel({ connected: true, busy: true, pendingApprovalCount: 1 }), 'Waiting for your approval');
  assert.equal(statusLabel({ connected: true, busy: true }), 'Working');
  assert.equal(statusLabel({ connected: true, busy: false, lastStatus: 'cancelled' }), 'Cancelled');
  assert.equal(statusLabel({ connected: true, busy: false, lastStatus: 'failed' }), 'Failed');
  assert.equal(statusLabel({ connected: true, busy: false, lastStatus: 'completed' }), 'Completed');
  assert.equal(statusLabel({ connected: true, busy: false }), 'Connected');
});

test('groupTurns: chronological, a user message opens a new turn', () => {
  const messages = [
    { role: 'user', content: 'first' },
    { role: 'assistant', content: 'reply one' },
    { role: 'user', content: 'second' },
    { role: 'assistant', content: 'reply two' },
  ];
  const turns = groupTurns(messages);
  assert.equal(turns.length, 2);
  assert.equal(turns[0].user.content, 'first');
  assert.deepEqual(turns[0].assistants.map(m => m.content), ['reply one']);
  assert.equal(turns[1].user.content, 'second');
  assert.deepEqual(turns[1].assistants.map(m => m.content), ['reply two']);
});

test('groupTurns: a leading assistant message (welcome line) is its own turn, not dropped', () => {
  const turns = groupTurns([{ role: 'assistant', content: 'hi' }, { role: 'user', content: 'hello' }]);
  assert.equal(turns.length, 2);
  assert.equal(turns[0].user, null);
  assert.deepEqual(turns[0].assistants.map(m => m.content), ['hi']);
  assert.equal(turns[1].user.content, 'hello');
});

test('groupTurns: multiple assistant messages after one user turn stay together', () => {
  const turns = groupTurns([
    { role: 'user', content: 'q' },
    { role: 'assistant', content: 'a1' },
    { role: 'assistant', content: 'a2' },
  ]);
  assert.equal(turns.length, 1);
  assert.deepEqual(turns[0].assistants.map(m => m.content), ['a1', 'a2']);
});

test('groupTurns: non user/assistant rows (unknown roles) are skipped, not crashed on', () => {
  const turns = groupTurns([{ role: 'system', content: 'x' }, { role: 'user', content: 'q' }]);
  assert.equal(turns.length, 1);
  assert.equal(turns[0].user.content, 'q');
});

test('selectableModels: only reachable providers and available models are offered', () => {
  const catalog = {
    providers: [
      { id: 'ok', reachable: true, models: [{ id: 'good', available: true }, { id: 'bad', available: false }] },
      { id: 'down', reachable: false, models: [{ id: 'unreachable', available: true }] },
    ],
  };
  assert.deepEqual(selectableModels(catalog), [{ provider: 'ok', id: 'good' }]);
});

test('selectableModels: missing/empty catalog yields no rows, not a crash', () => {
  assert.deepEqual(selectableModels(null), []);
  assert.deepEqual(selectableModels({}), []);
});

test('providerModelValue / parseProviderModel: round-trip preserves both parts', () => {
  const val = providerModelValue('openai', 'gpt-4');
  assert.equal(val, 'openai::gpt-4');
  assert.deepEqual(parseProviderModel(val), { provider: 'openai', model: 'gpt-4' });
});

test('parseProviderModel: empty/Gateway-default sentinel returns empty strings', () => {
  assert.deepEqual(parseProviderModel(''), { provider: '', model: '' });
  assert.deepEqual(parseProviderModel(undefined), { provider: '', model: '' });
  assert.deepEqual(parseProviderModel(null), { provider: '', model: '' });
});

test('providerModelValue: same model-id from different providers yields distinct values', () => {
  assert.notEqual(providerModelValue('openai', 'claude-3'), providerModelValue('anthropic', 'claude-3'));
});
