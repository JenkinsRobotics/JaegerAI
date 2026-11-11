'use strict';

/**
 * Host language-model bridge (subscription models, no API keys).
 *
 * Exposes the IDE host's signed-in chat models (Antigravity Google models,
 * VS Code Copilot, ChatGPT/Muse panels when the host surfaces them through
 * vscode.lm) on a loopback HTTP server so Jaeger Gateway can use the same
 * browser/subscription session the operator already logged into.
 *
 * Never reads, copies, or logs host credentials. Auth is the host's own
 * Language Model API + a per-start bearer token written only under
 * ~/.jaeger/run/ (mode 0600).
 */

const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

const BRIDGE_DIR = path.join(os.homedir(), '.jaeger', 'run');
const BRIDGE_FILE = path.join(BRIDGE_DIR, 'vscode-bridge.json');
const CONSENT_KEY = 'jaeger.hostLmBridge.consent';

function appLabel(vscode) {
  const name = String(vscode.env?.appName || 'IDE').trim() || 'IDE';
  return name;
}

function isAntigravity(vscode) {
  return /antigravity/i.test(String(vscode.env?.appName || ''));
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Cache-Control': 'no-store',
  });
  res.end(payload);
}

function readBody(req, limit = 512 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error('request too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function messageText(message) {
  if (typeof message === 'string') return message;
  const content = message?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map(part => {
      if (typeof part === 'string') return part;
      return typeof part?.value === 'string' ? part.value : (part?.text || '');
    }).join('');
  }
  return String(message?.text || '');
}

async function listHostModels(vscode) {
  if (typeof vscode.lm?.selectChatModels !== 'function') return [];
  const models = await vscode.lm.selectChatModels();
  return (models || []).map(model => ({
    id: String(model.id || model.name || '').trim(),
    name: String(model.name || model.id || '').trim(),
    family: String(model.family || model.vendor || '').trim(),
    vendor: String(model.vendor || '').trim(),
    max_input_tokens: Number(model.maxInputTokens || model.maxInputTokenCount || 0) || undefined,
    version: String(model.version || '1'),
  })).filter(row => row.id);
}

async function chatWithHostModel(vscode, { modelId, prompt, token }) {
  const models = await vscode.lm.selectChatModels();
  const match = (models || []).find(model => {
    const id = String(model.id || model.name || '');
    return id === modelId || String(model.name || '') === modelId;
  });
  if (!match) {
    throw new Error(`Host model not available: ${modelId || '(none)'}. Sign in to the IDE provider panel first.`);
  }
  const userRole = vscode.LanguageModelChatMessageRole?.User ?? 1;
  const messages = [
    vscode.LanguageModelChatMessage?.User
      ? vscode.LanguageModelChatMessage.User(String(prompt || ''))
      : { role: userRole, content: [{ value: String(prompt || '') }] },
  ];
  const response = await match.sendRequest(messages, {}, token);
  let text = '';
  if (response?.text) {
    for await (const chunk of response.text) {
      text += String(chunk || '');
    }
  } else if (response?.stream) {
    for await (const part of response.stream) {
      if (typeof part === 'string') text += part;
      else if (part?.value) text += String(part.value);
      else if (part?.text) text += String(part.text);
    }
  }
  return text;
}

function writeBridgeFile(info) {
  fs.mkdirSync(BRIDGE_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${BRIDGE_FILE}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(info, null, 2), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(tmp, BRIDGE_FILE);
  try { fs.chmodSync(BRIDGE_FILE, 0o600); } catch (_) { /* best-effort */ }
}

function clearBridgeFile(expectedPid) {
  try {
    const raw = fs.readFileSync(BRIDGE_FILE, 'utf8');
    const info = JSON.parse(raw);
    if (expectedPid && info.pid && info.pid !== expectedPid) return;
    fs.unlinkSync(BRIDGE_FILE);
  } catch (_) { /* missing is fine */ }
}

function registerHostLmBridge(vscode, context, output) {
  if (typeof vscode.lm?.selectChatModels !== 'function') {
    output?.appendLine('[jaeger] Host LM bridge off: language-model API unavailable in this host.');
    return undefined;
  }

  const token = crypto.randomBytes(24).toString('hex');
  const state = context.globalState;
  let consent = state.get(CONSENT_KEY) === 'granted' ? 'granted' : 'needed';
  const hostName = appLabel(vscode);

  const server = http.createServer(async (req, res) => {
    try {
      const auth = String(req.headers.authorization || '');
      if (auth !== `Bearer ${token}`) {
        json(res, 401, { error: 'unauthorized' });
        return;
      }
      const url = new URL(req.url || '/', 'http://127.0.0.1');
      if (req.method === 'GET' && url.pathname === '/health') {
        json(res, 200, {
          ok: true,
          vscode: hostName,
          host: hostName,
          antigravity: isAntigravity(vscode),
          consent,
          pid: process.pid,
        });
        return;
      }
      if (req.method === 'GET' && url.pathname === '/models') {
        const models = await listHostModels(vscode);
        json(res, 200, { models, host: hostName, consent });
        return;
      }
      if (req.method === 'POST' && url.pathname === '/chat') {
        if (consent !== 'granted') {
          json(res, 403, {
            error: 'Host model access needs your OK. In the IDE run “Jaeger: Allow Host Models for Jaeger”.',
          });
          return;
        }
        const raw = await readBody(req);
        let body = {};
        try { body = JSON.parse(raw || '{}'); } catch (_) {
          json(res, 400, { error: 'invalid JSON body' });
          return;
        }
        const modelId = String(body.model || '').trim();
        const prompt = String(body.prompt || '').trim();
        if (!modelId || !prompt) {
          json(res, 400, { error: 'model and prompt are required' });
          return;
        }
        const started = Date.now();
        res.writeHead(200, {
          'Content-Type': 'application/x-ndjson; charset=utf-8',
          'Cache-Control': 'no-store',
          'Transfer-Encoding': 'chunked',
        });
        const write = (obj) => res.write(`${JSON.stringify(obj)}\n`);
        write({ type: 'start', model: modelId, host: hostName });
        try {
          const cts = new vscode.CancellationTokenSource();
          req.on('close', () => cts.cancel());
          const text = await chatWithHostModel(vscode, {
            modelId,
            prompt,
            token: cts.token,
          });
          if (text) write({ type: 'delta', text });
          write({
            type: 'done',
            model: modelId,
            elapsed_s: Number(((Date.now() - started) / 1000).toFixed(2)),
            source: hostName,
          });
        } catch (error) {
          write({ type: 'error', error: String(error?.message || error).slice(0, 300) });
        }
        res.end();
        return;
      }
      json(res, 404, { error: 'not found' });
    } catch (error) {
      json(res, 500, { error: String(error?.message || error).slice(0, 300) });
    }
  });

  server.listen(0, '127.0.0.1', () => {
    const address = server.address();
    const port = address && typeof address === 'object' ? address.port : 0;
    writeBridgeFile({
      port,
      token,
      pid: process.pid,
      host: hostName,
      antigravity: isAntigravity(vscode),
      started_at: new Date().toISOString(),
    });
    output?.appendLine(
      `[jaeger] Host LM bridge listening on 127.0.0.1:${port} (${hostName}; subscription models, no API keys).`,
    );
  });

  const allowCmd = vscode.commands.registerCommand('jaeger.allowHostModels', async () => {
    const pick = await vscode.window.showInformationMessage(
      `Allow Jaeger to use ${hostName}'s signed-in models (Google / Copilot / ChatGPT panels) through your existing subscription? Jaeger never sees your login cookies or API keys.`,
      { modal: true },
      'Allow',
      'Not now',
    );
    if (pick === 'Allow') {
      consent = 'granted';
      await state.update(CONSENT_KEY, 'granted');
      vscode.window.showInformationMessage('Jaeger may use this IDE’s signed-in models.');
      output?.appendLine('[jaeger] Host LM bridge consent granted.');
    }
  });

  // Back-compat alias used by older Settings copy.
  const legacyCmd = vscode.commands.registerCommand('jaeger.allowCopilotForJaeger', () =>
    vscode.commands.executeCommand('jaeger.allowHostModels'));

  context.subscriptions.push(
    allowCmd,
    legacyCmd,
    {
      dispose() {
        try { server.close(); } catch (_) { /* ignore */ }
        clearBridgeFile(process.pid);
      },
    },
  );

  return { server, token };
}

module.exports = {
  BRIDGE_FILE,
  registerHostLmBridge,
  listHostModels,
  appLabel,
  isAntigravity,
};
