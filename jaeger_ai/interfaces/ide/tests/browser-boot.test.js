'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const media = path.join(__dirname, '..', 'media');
const scripts = [
  'frame-queue.js',
  'timeline.js',
  'keyed-renderer.js',
  'presentation.js',
  'markdown.js',
  'view.js',
];

function element() {
  return {
    value: '', disabled: false, hidden: false, textContent: '', title: '',
    children: [], dataset: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    replaceChildren(...items) { this.children = items; },
    add(item) { this.children.push(item); },
    querySelector() { return null; },
    matches() { return false; },
    setAttribute() {},
    requestSubmit() {},
  };
}

test('classic browser scripts share one context and boot the webview once', () => {
  const nodes = new Map();
  const messages = [];
  const listeners = [];
  const context = vm.createContext({
    console,
    URL,
    TextEncoder,
    TextDecoder,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: callback => setTimeout(callback, 0),
    cancelAnimationFrame: clearTimeout,
    Option: function Option(text, value) { this.text = text; this.value = value; },
    document: {
      visibilityState: 'visible',
      getElementById(id) {
        if (!nodes.has(id)) nodes.set(id, element());
        return nodes.get(id);
      },
      createElement() { return element(); },
    },
    acquireVsCodeApi() {
      return {
        getState: () => ({ drafts: {} }),
        setState() {},
        postMessage(message) { messages.push(message); },
      };
    },
  });
  context.window = context;
  context.window.addEventListener = (name, callback) => listeners.push({ name, callback });

  for (const filename of scripts) {
    const source = fs.readFileSync(path.join(media, filename), 'utf8');
    assert.doesNotThrow(
      () => vm.runInContext(source, context, { filename }),
      `${filename} must coexist with the earlier classic scripts`,
    );
  }

  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'ready');
  assert.deepEqual(Object.keys(messages[0]), ['type']);
  assert.equal(listeners.filter(item => item.name === 'message').length, 1);
  assert.equal(typeof context.window.JaegerPresentation.groupActivity, 'function');
  assert.equal(typeof context.window.JaegerMarkdown.renderMarkdownOnce, 'function');
});
