import { test } from 'node:test';
import assert from 'node:assert/strict';
import { moodFor } from './mood.ts';

test('the face shows the feeling, then what the agent is doing', () => {
  assert.equal(moodFor({ event: 'feeling', text: 'joy' }, 'neutral'), 'joy');
  assert.equal(moodFor({ event: 'state', text: 'thinking' }, 'joy'), 'thinking');
  assert.equal(moodFor({ event: 'state', text: 'hearing you' }, 'joy'), 'listening');
  assert.equal(moodFor({ event: 'state', text: 'speaking' }, 'joy'), 'joy');
  assert.equal(moodFor({ event: 'state', text: 'idle' }, 'joy'), 'neutral');
  assert.equal(moodFor({ event: 'assistant', text: 'Hi' }, 'joy'), null);
});
