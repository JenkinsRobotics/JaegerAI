(function exposeMarkdown(root) {
'use strict';
// Pure text-shaping helpers for the transcript, plus the smd.min.js binding.
// The DOM-touching half only runs in the webview; the pure half is imported
// directly by the Node test suite, so the safety rules are unit-tested
// without a browser.
//
// smd (streaming-markdown, MIT — see ../THIRD_PARTY_NOTICES.md) is optional:
// it is staged into media/vendor/ by package_extension.py, not committed to
// this source tree. When it is absent — an unpackaged dev checkout, or a
// load failure — every path below still renders literal, safely-escaped
// text with fenced code kept in its own scroll region. Markdown is always
// an enhancement over that baseline, never a precondition for it.

// Only these URL schemes render as a real link/image; everything else
// (javascript:, data:, vscode-webview: internals, …) stays inert. mailto is
// allowed for links only, never as an image source.
const SAFE_LINK_SCHEMES = new Set(['http:', 'https:', 'mailto:']);
// https only for images: the webview's CSP (index.html) matches this exactly,
// and there is no local-file image path — a picked attachment renders as a
// named chip, never a preview, since showing one would mean widening
// localResourceRoots beyond media/ to an arbitrary picked directory.
const SAFE_IMAGE_SCHEMES = new Set(['https:']);

function parseUrl(value) {
  try { return new URL(String(value || '')); } catch { return null; }
}

function isSafeMarkdownUrl(value, { image = false } = {}) {
  const url = parseUrl(value);
  if (!url) return false;
  return (image ? SAFE_IMAGE_SCHEMES : SAFE_LINK_SCHEMES).has(url.protocol);
}

// Splits raw text on fenced code blocks (```lang\n…\n```), same contract the
// original inline implementation had: even indices are prose, odd indices
// are fenced bodies. Used by the no-Markdown fallback so it stays exactly as
// safe as before — textContent only, never innerHTML.
function splitFencedText(raw) {
  const parts = String(raw || '').split(/```[^\n]*\n|```/g);
  return parts.map((value, index) => ({ type: index % 2 ? 'code' : 'text', value }));
}

// Builds a smd renderer that only differs from smd.default_renderer in one
// way: href/src attributes go through isSafeMarkdownUrl first. An unsafe
// value is dropped (the element loses that attribute, so a plain <a>/<img>
// with no destination) rather than substituted or thrown — a malformed reply
// degrades to inert markup, not a rendering error.
function safeRenderer(smd, el) {
  const renderer = smd.default_renderer(el);
  const setAttr = renderer.set_attr;
  renderer.set_attr = (data, attr, value) => {
    const isHref = attr === smd.HREF;
    const isSrc = attr === smd.SRC;
    if ((isHref || isSrc) && !isSafeMarkdownUrl(value, { image: isSrc })) return;
    setAttr(data, attr, value);
  };
  return renderer;
}

// Fully replaces `el`'s content with `text` rendered fresh. Used for both
// settled history messages AND the live streaming bubble — called again
// with the whole accumulated text on every batch of deltas, rather than fed
// incrementally, because the transcript rebuilds its DOM from `state` on
// every render() (see view.js): an incremental parser instance tied to a
// DOM node that render() may replace on the next call would desync from
// its element. Re-parsing the whole reply each batch (the Gateway batches
// deltas to a few times a second) is cheap at chat-reply sizes and keeps
// there being exactly one code path, tested exactly once.
// Falls back to literal text + fenced <pre> blocks when smd is unavailable.
function enhanceCodeBlocks(el) {
  const blocks = el.querySelectorAll('pre');
  blocks.forEach(pre => {
    if (pre.parentElement && pre.parentElement.classList.contains('code-card')) return;
    const code = pre.querySelector('code');
    if (!code) return;
    
    const card = document.createElement('div');
    card.className = 'code-card';
    
    const langMatch = code.className.match(/language-(\w+)/);
    const lang = langMatch ? langMatch[1] : 'code';
    
    const header = document.createElement('div');
    header.className = 'code-header';
    
    const chip = document.createElement('span');
    chip.className = 'code-lang-chip';
    chip.textContent = lang;
    
    const actions = document.createElement('div');
    actions.className = 'code-actions';
    
    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-code-btn';
    copyBtn.title = 'Copy code';
    copyBtn.setAttribute('aria-label', 'Copy code');
    const svgIcon = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 8V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-3M5 9h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z"/></svg>';
    copyBtn.innerHTML = svgIcon + ' Copy';
    
    copyBtn.onclick = () => {
      const text = code.textContent;
      if (typeof window !== 'undefined' && window.JaegerPostMessage) {
          window.JaegerPostMessage('copy', { text });
      } else if (navigator.clipboard) {
          navigator.clipboard.writeText(text);
      }
      copyBtn.textContent = 'Copied';
      setTimeout(() => { copyBtn.innerHTML = svgIcon + ' Copy'; }, 1200);
    };
    
    actions.append(copyBtn);
    header.append(chip, actions);
    
    pre.parentNode.insertBefore(card, pre);
    card.append(header, pre);
  });
}

function renderMarkdownOnce(smd, el, text) {
  el.replaceChildren();
  if (smd) {
    const parser = smd.parser(safeRenderer(smd, el));
    smd.parser_write(parser, String(text || ''));
    smd.parser_end(parser);
    enhanceCodeBlocks(el);
    return;
  }
  for (const part of splitFencedText(text)) {
    const node = document.createElement(part.type === 'code' ? 'pre' : 'div');
    node.className = 'content';
    if (part.type === 'code') {
      const codeNode = document.createElement('code');
      codeNode.textContent = part.value;
      node.append(codeNode);
    } else {
      node.textContent = part.value;
    }
    el.append(node);
  }
  enhanceCodeBlocks(el);
}

const exportsObject = { isSafeMarkdownUrl, splitFencedText, safeRenderer, renderMarkdownOnce };
if (typeof module !== 'undefined') module.exports = exportsObject;
if (root) root.JaegerMarkdown = exportsObject;
})(typeof window !== 'undefined' ? window : null);
