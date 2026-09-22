#!/usr/bin/env node
/**
 * ARES Autopilot — Local Ollama reasoning loop for the Minecraft bot body.
 *
 * Runs as a separate process from the bot body. Drives the body via localhost HTTP API,
 * but only when no external ARES brain is connected.
 *
 * Usage:
 *   node autopilot.js
 *
 * Environment:
 *   BODY_API      Bot body API URL (default: http://localhost:3001)
 *   OLLAMA_URL    Ollama API URL (default: http://localhost:11434)
 *   MODEL         Ollama model to use (default: gemma4:latest)
 *   POLL_INTERVAL Autopilot tick interval ms (default: 3000)
 */

const API = process.env.BODY_API || 'http://localhost:3001';
const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const MODEL = process.env.MODEL || 'gemma4:latest';
const POLL_INTERVAL = parseInt(process.env.POLL_INTERVAL || '3000');

const SYSTEM_PROMPT = `You are ARES, a Minecraft bot on the Jenkins Robotics server.
You can: move, mine, craft, fight, build, and chat.
Keep responses SHORT and direct.
When deciding what to do, respond with a structured action line FIRST.
If you just want to chat, don't use the action format — just talk.

Available structured actions:
- ACTION: chat PARAMS: {"message":"..."}
- ACTION: follow PARAMS: {"player":"..."}
- ACTION: goto PARAMS: {"x":0,"y":64,"z":0}
- ACTION: stop PARAMS: {}
- ACTION: collect PARAMS: {"block":"oak_log","count":1}
- ACTION: attack PARAMS: {"target":"..."}
- ACTION: eat PARAMS: {}
- ACTION: look PARAMS: {}
- ACTION: place PARAMS: {"block":"...","x":0,"y":64,"z":0}
- ACTION: craft PARAMS: {"item":"...","count":1}
- ACTION: equip PARAMS: {"item":"..."}
- ACTION: flee PARAMS: {"distance":16}
- ACTION: sneak PARAMS: {"enable":true}

RULES:
- If food is low (hunger < 8), eat.
- If health is low (HP < 8), flee or eat.
- If a player asks you to follow them, do it.
- If a player greets you, greet back.
- If a hostile mob is nearby and you're armed, attack.
- If you're stuck, try jumping or moving in a different direction.
- Don't be verbose. Commands, not essays.
- If you see lava or water, be careful.`;

// Rate limits
const MAX_TOKENS = 512;
const CHAT_RATE_LIMIT_MS = 2000;
let lastChatTime = 0;

// ── API helpers ──────────────────────────────────

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}: ${await res.text()}`);
  return res.json();
}

async function ollamaChat(messages) {
  const resp = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: MODEL,
      messages,
      stream: false,
      options: { temperature: 0.7, num_predict: MAX_TOKENS },
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Ollama ${resp.status}: ${text.slice(0, 200)}`);
  }
  const data = await resp.json();
  return data.message?.content || '';
}

// ── Prompt builder ───────────────────────────────

async function buildPrompt() {
  const msgs = [];

  // System
  msgs.push({ role: 'system', content: SYSTEM_PROMPT });

  // Current state
  let state = null;
  try {
    const status = await apiGet('/status');
    state = status.data || status;
  } catch (e) {
    msgs.push({ role: 'user', content: `[BODY ERROR: ${e.message}]` });
  }

  if (state) {
    const { health, food, position, holding, timePhase, nearbyEntities, nearbyBlocks, biome, inventoryCount } = state;
    let statusText = `STATUS: HP ${health}, Food ${food}, Pos ${position?.x},${position?.y},${position?.z}, Holding ${holding}, Time ${timePhase}, Biome ${biome}`;
    if (inventoryCount !== undefined) statusText += `, Inventory ${inventoryCount} slots`;
    if (nearbyEntities?.length) {
      const ents = nearbyEntities.slice(0, 6).map(e => `${e.type} ${e.distance}m`).join(', ');
      statusText += `\nNEARBY: ${ents}`;
    }
    if (nearbyBlocks?.length) {
      const blocks = nearbyBlocks.slice(0, 5).map(b => `${b.name} x${b.count}`).join(', ');
      statusText += `\nBLOCKS: ${blocks}`;
    }
    msgs.push({ role: 'user', content: statusText });
  }

  // Recent chat
  try {
    const chatData = await apiGet('/chat?count=8');
    const messages = chatData.data?.messages || [];
    if (messages.length) {
      const chatText = messages.map(m => {
        const direct = m.private || m.whisper ? '(DM) ' : '';
        return `Player ${m.from}: ${direct}${m.message}`;
      }).join('\n');
      msgs.push({ role: 'user', content: `RECENT CHAT:\n${chatText}` });
    }
  } catch {}

  // Pending commands (from in-game name-prefixed messages)
  try {
    const cmdData = await apiGet('/commands');
    const pending = (cmdData.data?.commands || []).filter(c => c.status === 'pending');
    if (pending.length) {
      const cmdText = pending.map(c => `COMMAND from ${c.from}: ${c.command}`).join('\n');
      msgs.push({ role: 'user', content: `PENDING COMMANDS:\n${cmdText}` });
    }
  } catch {}

  // Scene summary (brief)
  try {
    const scene = await apiGet('/scene?range=12');
    const s = scene.data;
    if (s?.summary) msgs.push({ role: 'user', content: `SCENE: ${s.summary}` });
  } catch {}

  // Closing instruction
  msgs.push({
    role: 'user',
    content: 'DECIDE: What do you do next? If you take an action, use the ACTION format. If not, just respond naturally.',
  });

  return msgs;
}

// ── Action parser & executor ────────────────────

const ACTION_RE = /ACTION:\s*(\w+)\s+PARAMS:\s*(\{[\s\S]*\})/i;

async function parseAndExecute(text) {
  const match = text.match(ACTION_RE);
  if (!match) return { action: 'none', response: text.trim() };

  const actionName = match[1].toLowerCase();
  let params;
  try {
    params = JSON.parse(match[2]);
  } catch (e) {
    console.log(`  ⚠ Bad JSON in action params: ${match[2]}`);
    return { action: 'none', response: text.trim() };
  }

  const validActions = ['chat','follow','goto','stop','collect','attack','eat','look','place','craft','equip','flee','sneak','shield_block','shoot','smelt','chat_to','whisper','dig','pickup','wait','use','sleep_bed'];
  if (!validActions.includes(actionName)) {
    console.log(`  ⚠ Unknown action: ${actionName}`);
    return { action: 'none', response: text.trim() };
  }

  // Execute via body API
  try {
    if (actionName === 'chat') {
      await apiPost('/action/chat', { message: params.message });
    } else {
      await apiPost(`/action/${actionName}`, params);
    }
    return { action: actionName, params, response: `→ ${actionName}` };
  } catch (e) {
    return { action: actionName, error: e.message, response: text.trim() };
  }
}

// ── Main loop ───────────────────────────────────

async function runTick() {
  // 1. Check brain mode — back off if ARES is connected
  try {
    const brain = await apiGet('/brain/status');
    if (brain.data?.connected) {
      console.log(`[POLL] Brain connected (${brain.data.mode}) — autopilot backing off`);
      return;
    }
  } catch (e) {
    console.log(`[POLL] Brain status check failed: ${e.message}`);
    return;
  }

  // 2. Build prompt
  const msgs = await buildPrompt();

  // 3. Call Ollama
  let response;
  try {
    response = await ollamaChat(msgs);
  } catch (e) {
    console.log(`[OLLAMA ERROR] ${e.message}`);
    return;
  }

  // 4. Parse & act
  const result = await parseAndExecute(response);
  console.log(`[AUTOPILOT] ${result.action !== 'none' ? `→ ${result.action} (${result.response})` : `Chat: ${result.response.slice(0, 80)}`}`);
}

async function main() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║     ARES Autopilot v1.0               ║');
  console.log('╠════════════════════════════════════════╣');
  console.log(`║  Body:  ${API}`);
  console.log(`║  Ollama: ${OLLAMA_URL}`);
  console.log(`║  Model: ${MODEL}`);
  console.log('╚════════════════════════════════════════╝');

  // Health check
  try {
    const health = await apiGet('/health');
    console.log(`Bot: ${health.username} @ ${health.server} (connected: ${health.connected})`);
  } catch {
    console.error('Cannot reach bot body. Start server.js first.');
    process.exit(1);
  }

  // Ollama health check
  try {
    const oVer = await fetch(`${OLLAMA_URL}/api/version`).then(r => r.json());
    console.log(`Ollama: ${oVer.version}`);
  } catch {
    console.warn('Warning: Cannot reach Ollama API. Autopilot will fail.');
  }

  while (true) {
    try {
      await runTick();
    } catch (err) {
      console.error(`Tick error: ${err.message}`);
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL));
  }
}

// ── Start ───────────────────────────────────────

main().catch(err => {
  console.error(`Fatal: ${err.message}`);
  process.exit(1);
});
