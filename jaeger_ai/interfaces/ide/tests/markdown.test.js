'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { isSafeMarkdownUrl, splitFencedText, safeRenderer, renderMarkdownOnce } = require('../media/markdown');

test('isSafeMarkdownUrl: links allow http/https/mailto, block everything else', () => {
  for (const url of ['http://example.org', 'https://example.org', 'mailto:a@example.org']) {
    assert.equal(isSafeMarkdownUrl(url), true, url);
  }
  for (const url of ['javascript:alert(1)', 'data:text/html,<script>1</script>', 'vscode-webview://x', '', 'not a url']) {
    assert.equal(isSafeMarkdownUrl(url), false, url);
  }
});

test('isSafeMarkdownUrl: images require https, mailto/http/data are rejected', () => {
  assert.equal(isSafeMarkdownUrl('https://example.org/pic.png', { image: true }), true);
  for (const url of ['http://example.org/pic.png', 'mailto:a@example.org', 'data:image/png;base64,AA==']) {
    assert.equal(isSafeMarkdownUrl(url, { image: true }), false, url);
  }
});

test('splitFencedText: alternates prose/code, prose that never fences stays whole', () => {
  assert.deepEqual(splitFencedText('hello'), [{ type: 'text', value: 'hello' }]);
  const parts = splitFencedText('before\n```js\nconst x = 1;\n```\nafter');
  assert.deepEqual(parts.map(p => p.type), ['text', 'code', 'text']);
  assert.equal(parts[1].value, 'const x = 1;\n');
});

test('safeRenderer: blocks a javascript: href but keeps a safe one, blocks any non-https image src', () => {
  const calls = [];
  const fakeSmd = {
    HREF: 'href', SRC: 'src',
    default_renderer: () => ({ set_attr: (data, attr, value) => calls.push([attr, value]) }),
  };
  const renderer = safeRenderer(fakeSmd, {});
  renderer.set_attr({}, 'href', 'javascript:alert(1)');
  renderer.set_attr({}, 'href', 'https://example.org');
  renderer.set_attr({}, 'src', 'http://example.org/pic.png');
  renderer.set_attr({}, 'src', 'https://example.org/pic.png');
  renderer.set_attr({}, 'class', 'whatever'); // untouched attrs always pass through
  assert.deepEqual(calls, [
    ['href', 'https://example.org'],
    ['src', 'https://example.org/pic.png'],
    ['class', 'whatever'],
  ]);
});

// A minimal fake DOM — just enough for renderMarkdownOnce's no-smd fallback
// (document.createElement + el.append/replaceChildren), so the safety-net
// path is verified without pulling in a browser or jsdom dependency.
function fakeDocument() {
  function makeElement(tag) {
    const el = {
      tagName: tag, className: '', children: [], _text: '',
      get textContent() { return this._text + this.children.map(child => child.textContent).join(''); },
      set textContent(value) { this._text = String(value); this.children = []; },
      append(...nodes) { this.children.push(...nodes); },
      replaceChildren() { this.children = []; },
    };
    return el;
  }
  return { createElement: makeElement };
}

test('renderMarkdownOnce: with no smd, renders literal text and fenced code as separate nodes', () => {
  global.document = fakeDocument();
  try {
    const el = { children: [], append(...n) { this.children.push(...n); }, replaceChildren() { this.children = []; } };
    renderMarkdownOnce(null, el, 'before\n```\ncode here\n```\nafter');
    assert.equal(el.children.length, 3);
    assert.equal(el.children[0].tagName, 'div'); assert.equal(el.children[0].textContent, 'before\n');
    assert.equal(el.children[1].tagName, 'pre'); assert.equal(el.children[1].textContent, 'code here\n');
    assert.equal(el.children[2].tagName, 'div'); assert.equal(el.children[2].textContent, 'after');
  } finally { delete global.document; }
});

test('renderMarkdownOnce: with smd, delegates to parser/parser_write/parser_end and clears first', () => {
  const calls = [];
  const fakeSmd = {
    HREF: 'href', SRC: 'src',
    default_renderer: () => ({ set_attr() {} }),
    parser: renderer => ({ renderer }),
    parser_write: (parser, chunk) => calls.push(['write', chunk]),
    parser_end: () => calls.push(['end']),
  };
  let cleared = false;
  const el = { replaceChildren() { cleared = true; } };
  renderMarkdownOnce(fakeSmd, el, 'hello **world**');
  assert.equal(cleared, true);
  assert.deepEqual(calls, [['write', 'hello **world**'], ['end']]);
});
