import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pcm16k } from './attach.ts';

test('a sound clip becomes 16 kHz 16-bit mono for her hearing', () => {
  const second = new Float32Array(48000).fill(0.5);          // 1 s at 48 kHz
  const bytes = Buffer.from(pcm16k(second, 48000), 'base64');
  assert.equal(bytes.length, 16000 * 2);                       // 1 s at 16 kHz, 2 bytes a sample
  assert.equal(bytes.readInt16LE(100), Math.round(0.5 * 32767));
  assert.equal(Buffer.from(pcm16k(new Float32Array([2, -2]), 16000), 'base64').readInt16LE(2), -32767);   // clipped, not wrapped
});
