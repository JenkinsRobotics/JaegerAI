// The chat's record of a conversation, built from the agent's events. Run: npm test (node --test).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { empty, onEvent, sent, type Chat } from './chat.ts';

const play = (chat: Chat, ...events: object[]) => events.reduce<Chat>((c, e) => onEvent(c, e), chat);

test('a typed message, its spoken sentences and the whole reply make one finished reply', () => {
  const c = play(sent(empty, 'Hi'),
    { event: 'audio', text: 'Hello there.' }, { event: 'audio', text: 'How are you?' },
    { event: 'assistant', text: 'Hello there. How are you?' }, { event: 'done' });
  assert.deepEqual(c.messages.map(m => [m.role, m.text, m.open]), [['user', 'Hi', false], ['assistant', 'Hello there. How are you?', false]]);
  assert.equal(c.busy, false);
});

test('sentences show as they are spoken, before the whole reply arrives', () => {
  const c = play(sent(empty, 'Hi'), { event: 'audio', text: 'Hello there.' }, { event: 'audio', text: 'How are you?' });
  assert.equal(c.messages[1].text, 'Hello there. How are you?');
  assert.equal(c.messages[1].open, true);
  assert.equal(c.busy, true);
});

test('Omni sends the whole reply before its spoken sentences: the reply is not doubled', () => {
  const c = play(sent(empty, 'Hi'), { event: 'assistant', text: 'Hello there. How are you?' },
    { event: 'audio', text: 'Hello there. How are you?' }, { event: 'done' });
  assert.deepEqual(c.messages.map(m => m.text), ['Hi', 'Hello there. How are you?']);
});

test('tool calls and feelings are kept under the reply they belong to', () => {
  const c = play(sent(empty, 'Hi'), { event: 'tool', text: 'avatar emotion', data: { value: 'joy' } },
    { event: 'feeling', text: 'joy' }, { event: 'assistant', text: 'Yay!' }, { event: 'done' });
  assert.equal(c.messages.length, 2);
  assert.deepEqual(c.messages[1].tools.map(t => t.name), ['avatar emotion', 'feeling']);
  assert.equal(c.messages[1].tools[1].detail, 'joy');
});

test('what the microphone heard is shown as the person speaking, and a typed line is not shown twice', () => {
  const heard = play(empty, { event: 'user', text: 'What time is it?' });
  assert.deepEqual(heard.messages.map(m => [m.role, m.text]), [['user', 'What time is it?']]);
  assert.equal(heard.busy, true);
  assert.equal(play(sent(empty, 'Hi'), { event: 'user', text: 'Hi' }).messages.length, 1);
});

test('a turn that ends with no words leaves no empty reply behind', () => {
  const c = play(sent(empty, 'Hi'), { event: 'state', text: 'thinking' }, { event: 'done' });
  assert.deepEqual(c.messages.map(m => m.role), ['user']);
});

test('an error from the agent is shown as a note, and the state line is the status', () => {
  const c = play(sent(empty, 'Hi'), { event: 'state', text: 'thinking' });
  assert.equal(c.status, 'thinking');
  const e = play(c, { event: 'status', text: 'error: model failed' }, { event: 'done' });
  assert.deepEqual(e.messages.map(m => [m.role, m.text]), [['user', 'Hi'], ['note', 'error: model failed']]);
});

test('pictures sent with a message stay with it', () => {
  const c = sent(empty, 'What is this?', ['data:image/jpeg;base64,AA']);
  assert.deepEqual(c.messages[0].pics, ['data:image/jpeg;base64,AA']);
  assert.equal(sent(empty, 'Hi').messages[0].pics, undefined);
});

test('the Gateway\'s streamed deltas build the reply, and its whole reply replaces them', () => {
  const c = play(empty, { event: 'user', text: 'Hi' }, { event: 'delta', text: 'Hel' }, { event: 'delta', text: 'lo, there' });
  assert.equal(c.messages[1].text, 'Hello, there');
  const d = play(c, { event: 'assistant', text: 'Hello, there.' }, { event: 'done' });
  assert.deepEqual(d.messages.map(m => [m.role, m.text, m.open]), [['user', 'Hi', false], ['assistant', 'Hello, there.', false]]);
  assert.equal(play(d, { event: 'reset' }).messages.length, 0);
});
