'use strict';
/**
 * Copilot bridge (Jaeger IDE): lets Jaeger on this Mac use the Copilot models VS Code already has
 * through the Language Model API (vscode.lm) — no API keys. Matthew's Copilot sign-in stays in VS Code.
 *
 *  - Listens on 127.0.0.1 only, random port. Rejects non-loopback peers, foreign Host headers
 *    (DNS rebinding) and any request carrying an Origin (browsers).
 *  - A fresh 256-bit token each activation, required as `Authorization: Bearer`. It is written only to
 *    ~/.jaeger/run/vscode-bridge.json (dir 0700, file 0600) and never logged.
 *  - Rate limit: 20 requests/minute, 2 concurrent, 1 per model. Client disconnect cancels the request.
 *  - On/off: setting `jaeger.copilotBridge.enabled`. Off closes the server and removes the file.
 *  - Copilot access needs VS Code's one-time consent; command "Jaeger: Allow Copilot for Jaeger" asks for it.
 *
 * Routes: GET /health · GET /models · POST /chat {model, prompt} → NDJSON start/delta/done|error
 */
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const VENDOR = 'copilot';
const RATE_PER_MIN = 20;
const MAX_CONCURRENT = 2;
const MAX_PROMPT = 20000;

function bridgeFile(home = os.homedir()) { return path.join(home, '.jaeger', 'run', 'vscode-bridge.json'); }

function writePrivate(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  try { fs.chmodSync(path.dirname(file), 0o700); } catch (_) { /* best effort */ }
  const tmp = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(tmp, 'w', 0o600);
  try { fs.writeSync(fd, JSON.stringify(data, null, 2)); } finally { fs.closeSync(fd); }
  fs.chmodSync(tmp, 0o600);
  fs.renameSync(tmp, file);
}

const isLoopback = (addr) => addr === '127.0.0.1' || addr === '::1' || addr === '::ffff:127.0.0.1';

function classify(vscode, err) {
  const code = err && (err.code || err.name);
  const E = vscode.LanguageModelError;
  if (E && err instanceof E) {
    if (code === E.NoPermissions?.name || /NoPermissions/i.test(code)) return ['needs_consent', 'VS Code has not allowed Jaeger to use Copilot yet. Run "Jaeger: Allow Copilot for Jaeger" in VS Code and click Allow.'];
    if (code === E.Blocked?.name || /Blocked/i.test(code)) return ['quota', 'Copilot blocked the request (quota or rate limit).'];
    if (code === E.NotFound?.name || /NotFound/i.test(code)) return ['not_found', 'That Copilot model is not available.'];
  }
  if (/NoPermissions|consent/i.test(String(code) + String(err && err.message))) return ['needs_consent', 'VS Code has not allowed Jaeger to use Copilot yet. Run "Jaeger: Allow Copilot for Jaeger" in VS Code and click Allow.'];
  if (err && err.name === 'Canceled') return ['cancelled', 'Cancelled.'];
  return ['error', String((err && err.message) || err).slice(0, 300)];
}

function createBridge({ vscode, log = () => {}, home = os.homedir(), now = () => Date.now(), randomBytes = crypto.randomBytes }) {
  let server = null; let token = null; let port = null;
  let consent = 'unknown';
  const stamps = []; const busyModels = new Set(); let active = 0;
  const file = bridgeFile(home);

  const listModels = async () => (await vscode.lm.selectChatModels({ vendor: VENDOR })).map((m) => ({
    id: m.id, name: m.name, family: m.family, vendor: m.vendor, version: m.version, max_input_tokens: m.maxInputTokens ?? null,
  }));

  function authorized(req) {
    const h = String(req.headers.authorization || '');
    const given = Buffer.from(h.startsWith('Bearer ') ? h.slice(7) : '');
    const want = Buffer.from(token || '');
    return given.length === want.length && want.length > 0 && crypto.timingSafeEqual(given, want);
  }

  function send(res, status, body) {
    const data = JSON.stringify(body);
    res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Content-Length': Buffer.byteLength(data) });
    res.end(data);
  }

  function readJson(req, limit = 256 * 1024) {
    return new Promise((resolve, reject) => {
      let n = 0; const chunks = [];
      req.on('data', (c) => { n += c.length; if (n > limit) { reject(new Error('body too large')); req.destroy(); } else chunks.push(c); });
      req.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')); } catch (e) { reject(e); } });
      req.on('error', reject);
    });
  }

  function rateOk() {
    const t = now();
    while (stamps.length && t - stamps[0] > 60000) stamps.shift();
    if (stamps.length >= RATE_PER_MIN) return false;
    stamps.push(t); return true;
  }

  async function chat(req, res) {
    let body;
    try { body = await readJson(req); } catch { return send(res, 400, { error: 'JSON body required' }); }
    const prompt = typeof body.prompt === 'string' ? body.prompt : '';
    const modelId = typeof body.model === 'string' ? body.model : '';
    if (!prompt.trim() || prompt.length > MAX_PROMPT || !modelId) return send(res, 400, { error: `need a model and a prompt (≤${MAX_PROMPT} chars)` });
    if (!rateOk()) return send(res, 429, { error: `Rate limit: ${RATE_PER_MIN} requests per minute` });
    if (active >= MAX_CONCURRENT || busyModels.has(modelId)) return send(res, 429, { error: 'Busy: one request per model, two at a time' });
    const [model] = await vscode.lm.selectChatModels({ vendor: VENDOR, id: modelId });
    if (!model) return send(res, 404, { error: `Copilot model ${modelId} is not available in VS Code` });
    active += 1; busyModels.add(modelId);
    const cts = new vscode.CancellationTokenSource();
    let finished = false;
    res.on('close', () => { if (!finished) cts.cancel(); });
    res.writeHead(200, { 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-store' });
    const emit = (ev) => { if (!res.writableEnded) res.write(JSON.stringify(ev) + '\n'); };
    const t0 = now(); let ttft = null; let text = '';
    emit({ type: 'start', model: modelId });
    try {
      const response = await model.sendRequest([vscode.LanguageModelChatMessage.User(prompt)],
        { justification: 'Jaeger on this Mac is comparing answers from your Copilot models.' }, cts.token);
      consent = 'granted';
      for await (const chunk of response.text) {
        if (cts.token.isCancellationRequested) break;
        if (ttft === null && chunk) ttft = now() - t0;
        text += chunk; emit({ type: 'delta', text: chunk });
      }
      if (cts.token.isCancellationRequested) { emit({ type: 'error', code: 'cancelled', error: 'Cancelled.' }); }
      else {
        let out = null; let inp = null;
        try { out = await model.countTokens(text); inp = await model.countTokens(prompt); } catch (_) { /* optional */ }
        const elapsed = (now() - t0) / 1000; const gen = elapsed - (ttft ?? 0) / 1000;
        emit({ type: 'done', model: modelId, elapsed_s: +elapsed.toFixed(2), ttft_s: ttft === null ? null : +(ttft / 1000).toFixed(2),
          eval_count: out, prompt_eval_count: inp, tokens_per_s: out && gen > 0.05 ? +(out / gen).toFixed(1) : null, cost_usd: null, source: 'VS Code Copilot' });
      }
    } catch (err) {
      const [code, msg] = classify(vscode, err);
      if (code === 'needs_consent') consent = 'needed';
      emit({ type: 'error', code, error: msg });
    } finally {
      finished = true; active -= 1; busyModels.delete(modelId); cts.dispose?.();
      if (!res.writableEnded) res.end();
    }
  }

  async function handle(req, res) {
    if (!isLoopback(req.socket.remoteAddress)) { req.socket.destroy(); return; }
    const host = String(req.headers.host || '');
    if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) return send(res, 403, { error: 'bad host' });
    if (req.headers.origin) return send(res, 403, { error: 'browser requests are not allowed' });
    if (!authorized(req)) return send(res, 401, { error: 'unauthorized' });
    try {
      if (req.method === 'GET' && req.url === '/health') return send(res, 200, { ok: true, vscode: vscode.version, consent, vendor: VENDOR, pid: process.pid });
      if (req.method === 'GET' && req.url === '/models') return send(res, 200, { models: await listModels(), consent });
      if (req.method === 'POST' && req.url === '/chat') return await chat(req, res);
      return send(res, 404, { error: 'not found' });
    } catch (err) {
      const [code, msg] = classify(vscode, err);
      if (!res.headersSent) send(res, 500, { error: msg, code });
    }
  }

  function start() {
    if (server) return Promise.resolve(port);
    token = randomBytes(32).toString('hex');
    server = http.createServer((req, res) => { void handle(req, res); });
    return new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        port = server.address().port;
        writePrivate(file, { version: 1, port, token, pid: process.pid, vscode: vscode.version, started_at: new Date(now()).toISOString(), vendor: VENDOR });
        log(`[jaeger] Copilot bridge listening on 127.0.0.1:${port}`);
        resolve(port);
      });
    });
  }

  function stop() {
    if (!server) return;
    try { const cur = JSON.parse(fs.readFileSync(file, 'utf8')); if (cur.token === token) fs.unlinkSync(file); } catch (_) { /* gone */ }
    server.close(); server = null; token = null; port = null;
    log('[jaeger] Copilot bridge stopped');
  }

  /** User-initiated: VS Code shows its consent dialog for Copilot models on the first request. */
  async function requestConsent() {
    const [model] = await vscode.lm.selectChatModels({ vendor: VENDOR });
    if (!model) { vscode.window.showWarningMessage('No Copilot models are available in VS Code. Sign in to GitHub Copilot first.'); return false; }
    const cts = new vscode.CancellationTokenSource();
    try {
      const r = await model.sendRequest([vscode.LanguageModelChatMessage.User('Reply with: ok')], { justification: 'Allow Jaeger on this Mac to use your Copilot models.' }, cts.token);
      for await (const _ of r.text) { /* drain */ }
      consent = 'granted';
      vscode.window.showInformationMessage('Jaeger can now use your Copilot models.');
      return true;
    } catch (err) {
      const [code, msg] = classify(vscode, err);
      if (code === 'needs_consent') consent = 'needed';
      vscode.window.showWarningMessage(`Copilot: ${msg}`);
      return false;
    } finally { cts.dispose?.(); }
  }

  return { start, stop, requestConsent, get port() { return port; }, get running() { return !!server; }, file };
}

/** Wire into the extension: honours `jaeger.copilotBridge.enabled`, registers the consent command. */
function activateBridge(vscode, context, log) {
  if (!vscode.lm || typeof vscode.lm.selectChatModels !== 'function') { log('[jaeger] Copilot bridge: this VS Code has no Language Model API'); return null; }
  const bridge = createBridge({ vscode, log });
  const enabled = () => vscode.workspace.getConfiguration('jaeger').get('copilotBridge.enabled', true) !== false;
  const sync = () => { if (enabled()) bridge.start().catch((e) => log(`[jaeger] Copilot bridge failed to start: ${e.message}`)); else bridge.stop(); };
  sync();
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration('jaeger.copilotBridge')) sync(); }),
    vscode.commands.registerCommand('jaeger.copilotBridge.allow', () => bridge.requestConsent()),
    vscode.commands.registerCommand('jaeger.copilotBridge.toggle', async () => {
      await vscode.workspace.getConfiguration('jaeger').update('copilotBridge.enabled', !enabled(), vscode.ConfigurationTarget.Global);
    }),
    { dispose: () => bridge.stop() },
  );
  return bridge;
}

module.exports = { createBridge, activateBridge, bridgeFile, classify, isLoopback, RATE_PER_MIN };
