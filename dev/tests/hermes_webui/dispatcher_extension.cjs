const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.open = false; this.style = {}; }
  prepend(...items) { this.children.unshift(...items); }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  before(item) { item.isConnected = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const listeners = {};
const elements = [];
const calls = [];
let profile = 'jaeger';
let denied = false;
const body = new Element('body');
const state = {activeProfile: profile};
const document = {
  head: new Element('head'), body, hidden: false, baseURI: 'http://webui/',
  createElement(tag) { const e = new Element(tag); elements.push(e); return e; },
  querySelectorAll() { return []; }, getElementById() { return new Element('list'); },
  addEventListener(name, callback) { listeners[name] = callback; }
};
const window = {
  hermesExt: {register() { return {events: {on() {}}}; }},
  addEventListener() {},
  async api(path, options) {
    calls.push({path, options});
    if (path === '/api/profile/active') return {name: profile};
    if (denied) throw new Error('Extension sidecar proxy consent required');
    if (path.endsWith('/memory')) return {facts: {preference: '<script>unsafe()</script>'}, board: {cards: [{title: 'Result', column: 'done', result: 'Read README'}]}};
    if (path === '/api/jaeger/conversation') return {dispatcher_session: 'primary', messages: [], revision: '0', run: null};
    throw new Error('Unexpected request: ' + path);
  }
};
let destination;
vm.runInNewContext(fs.readFileSync('jaeger_ai/assets/jaeger_dispatcher.js', 'utf8'), {
  document, window, S: state, URL, async loadSession(sid) { destination = sid; state.session = {session_id: sid}; }, location: {assign(value) { destination = String(value); }}, setInterval() {}
});
const settle = () => new Promise(resolve => setImmediate(resolve));
function click(panel) {
  let stopped = false;
  listeners.click({target: {closest() { return {dataset: {panel}}; }}, preventDefault() {}, stopImmediatePropagation() { stopped = true; }});
  return stopped;
}
(async () => {
  await settle();
  assert.equal(click('memory'), true);
  await settle();
  assert(calls.some(call => call.path.endsWith('/sidecar/memory')));
  assert(elements.some(e => e.textContent?.includes('<script>unsafe()</script>')));
  assert(!elements.some(e => Object.hasOwn(e, 'innerHTML')), 'Native text must not be interpreted as HTML');
  state.activeProfile = profile = 'default';
  const before = calls.length;
  assert.equal(click('memory'), false, 'A profile flip must immediately restore the original handler');
  await settle();
  assert.equal(calls.length, before);
  state.activeProfile = profile = 'jaeger';
  const primary = elements.find(e => e.tag === 'button' && e.textContent === '⚡ Dispatcher');
  await primary.onclick();
  assert.equal(destination, 'primary');
  assert(!calls.some(c => c.path === '/api/session/new'), 'Existing Dispatcher must not be recreated');
  denied = true;
  click('memory');
  await settle();
  assert(elements.some(e => e.textContent?.includes('enable WebUI login')));
  assert(calls.every(c => c.options.retries === 0), 'Mutation requests must not be replayed');
  console.log('PASS: native panel routing, safe text rendering, immediate profile switching, persistent Dispatcher navigation, and consent errors');
})().catch(error => { console.error(error); process.exitCode = 1; });
