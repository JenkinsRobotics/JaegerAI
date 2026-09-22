#!/usr/bin/env node
/**
 * ARES In-Game Command Responder
 *
 * Polls the bot API for pending chat commands from players,
 * interprets natural language, and executes bot actions.
 * Responds in-game in real-time.
 *
 * Usage: node ares-responder.js
 */

const API = process.env.MC_API_URL || 'http://localhost:3001';
const POLL_INTERVAL = 2000; // 2s

// ── API helpers ──────────────────────────────────────────

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// ── Command parser ───────────────────────────────────────

const COMMANDS = {
  // Movement
  goto: { pattern: /^(?:go to|goto|walk to|navigate to|head to|move to)\s+(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)/i, action: 'goto', extract: m => ({ x: +m[1], y: +m[2], z: +m[3] }) },
  follow: { pattern: /^follow\s+(.+)/i, action: 'follow', extract: m => ({ player: m[1].replace(/^\.?/, '.') }) },
  stop: { pattern: /^(?:stop|halt|wait here|stay|freeze)/i, action: 'stop', extract: () => ({}) },
  
  // Observation
  status: { pattern: /^(?:status|how are you|hp|health|where are you|where am i|position|pos)/i, action: 'status', extract: () => ({}) },
  inventory: { pattern: /^(?:inventory|inv|what do you have|what are you carrying|items)/i, action: 'inventory', extract: () => ({}) },
  look: { pattern: /^(?:look|look around|what do you see|what's around|what is around|survey|describe)/i, action: 'look', extract: () => ({}) },
  nearby: { pattern: /^(?:nearby|who's nearby|who is nearby|who's around|entities)/i, action: 'nearby', extract: () => ({}) },
  map: { pattern: /^(?:map|minimap)/i, action: 'map', extract: () => ({}) },
  
  // Mining
  collect: { pattern: /^(?:collect|mine|gather|get|dig)\s+(\w+)(?:\s+(\d+))?/i, action: 'collect', extract: m => ({ block: m[1], count: +(m[2] || 1) }) },
  find_blocks: { pattern: /^(?:find|find block|locate|search for)\s+(\w+)/i, action: 'find_blocks', extract: m => ({ block: m[1] }) },
  pickup: { pattern: /^(?:pickup|pick up|grab items|collect drops)/i, action: 'pickup', extract: () => ({}) },
  
  // Crafting
  craft: { pattern: /^(?:craft|make|create|build item)\s+(\w+)(?:\s+(\d+))?/i, action: 'craft', extract: m => ({ item: m[1], count: +(m[2] || 1) }) },
  recipes: { pattern: /^(?:recipe|recipes|how to (?:craft|make))\s+(\w+)/i, action: 'recipes', extract: m => ({ item: m[1] }) },
  
  // Combat
  attack: { pattern: /^(?:attack|kill|hit|fight)\s+(\w+)/i, action: 'attack', extract: m => ({ target: m[1] }) },
  flee: { pattern: /^(?:flee|run away|retreat|run)(?:\s+(\d+))?/i, action: 'flee', extract: m => ({ distance: +(m[1] || 16) }) },
  eat: { pattern: /^(?:eat|feed|food|hungry)/i, action: 'eat', extract: () => ({}) },
  equip: { pattern: /^(?:equip|hold|wield)\s+(\w+)/i, action: 'equip', extract: m => ({ item: m[1] }) },
  
  // Building
  place: { pattern: /^place\s+(\w+)\s+(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)/i, action: 'place', extract: m => ({ block: m[1], x: +m[2], y: +m[3], z: +m[4] }) },
  
  // Social
  chat_to: { pattern: /^(?:tell|whisper|msg|message|dm)\s+(\S+)\s+(.+)/i, action: 'chat_to', extract: m => ({ player: m[1], message: m[2] }) },
  
  // Locations
  mark: { pattern: /^mark\s+(\w+)(?:\s+(.+))?/i, action: 'mark', extract: m => ({ name: m[1], note: m[2] || '' }) },
  marks: { pattern: /^(?:marks|locations|waypoints|saved locations)/i, action: 'marks', extract: () => ({}) },
  go_mark: { pattern: /^go (?:to |mark )?(\w+)/i, action: 'go_mark', extract: m => ({ name: m[1] }) },
  
  // Combat advanced
  sneak: { pattern: /^sneak\s*(on|off|true|false)?/i, action: 'sneak', extract: m => ({ enable: !['off','false','0'].includes((m[1]||'').toLowerCase()) }) },
  shoot: { pattern: /^shoot\s+(\w+)/i, action: 'shoot', extract: m => ({ target: m[1] }) },
  shield: { pattern: /^(?:shield|block|block with shield)(?:\s+(\d+))?/i, action: 'shield_block', extract: m => ({ duration: +(m[1] || 3) }) },
  
  // Smelting
  smelt: { pattern: /^smelt\s+(\w+)(?:\s+(\w+))?(?:\s+(\d+))?/i, action: 'smelt', extract: m => ({ input: m[1], fuel: m[2] || undefined, count: +(m[3] || 1) }) },
};

// ── Execute & respond ────────────────────────────────────

async function executeCommand(from, text) {
  const trimmed = text.trim();
  console.log(`[CMD] <${from}> ${trimmed}`);
  
  // Try matching against command patterns
  for (const [name, cmd] of Object.entries(COMMANDS)) {
    const match = trimmed.match(cmd.pattern);
    if (match) {
      const params = cmd.extract(match);
      console.log(`  → Action: ${cmd.action}`, params);
      
      try {
        let result;
        
        if (cmd.action === 'status' || cmd.action === 'inventory' || cmd.action === 'look' || cmd.action === 'nearby' || cmd.action === 'map') {
          // GET endpoints
          const path = cmd.action === 'look' ? '/look' : 
                       cmd.action === 'map' ? '/map' :
                       cmd.action === 'nearby' ? '/nearby?radius=16' :
                       cmd.action === 'inventory' ? '/inventory' : '/status';
          const resp = await apiGet(path);
          const data = resp.data || resp;
          
          // Format response
          if (cmd.action === 'status') {
            const p = data.position || {};
            result = `HP: ${data.health}/20 | Food: ${data.food}/20 | Pos: ${p.x},${p.y},${p.z} | Holding: ${data.holding || 'nothing'}`;
          } else if (cmd.action === 'inventory') {
            const items = data.categories ? Object.values(data.categories).flat() : [];
            result = items.length > 0 ? items.map(i => `${i.name}x${i.count}`).join(', ') : 'Empty inventory';
          } else if (cmd.action === 'look') {
            result = data.description || JSON.stringify(data).slice(0, 200);
          } else if (cmd.action === 'nearby') {
            const ents = (data.entities || []).slice(0, 5);
            result = ents.length > 0 ? ents.map(e => `${e.type}(${e.distance}m)`).join(', ') : 'Nobody nearby';
          } else if (cmd.action === 'map') {
            result = 'Map generated (check console)';
          }
        } else {
          // POST action endpoints
          const resp = await apiPost(`/action/${cmd.action}`, params);
          result = resp.result || resp.error || 'Done';
        }
        
        // Respond in-game
        const responseText = result.length > 200 ? result.slice(0, 197) + '...' : result;
        await apiPost('/action/chat', { message: `${from}: ${responseText}` });
        console.log(`  ← ${responseText}`);
        
        // Mark command as completed
        await apiPost('/action/complete_command', {});
        
        return;
      } catch (err) {
        await apiPost('/action/chat', { message: `${from}: Error - ${err.message}` });
        console.log(`  ✗ ${err.message}`);
        await apiPost('/action/complete_command', {});
        return;
      }
    }
  }
  
  // No command matched — conversational response
  const greetings = /^(?:hi|hey|hello|sup|yo|what's up|howdy|greetings)/i;
  const thanks = /^(?:thanks|ty|thank you|thx)/i;
  const helpCmd = /^(?:help|commands|what can you do|capabilities)/i;
  
  if (greetings.test(trimmed)) {
    await apiPost('/action/chat', { message: `Hey ${from}! What do you need?` });
  } else if (thanks.test(trimmed)) {
    await apiPost('/action/chat', { message: `No problem, ${from}!` });
  } else if (helpCmd.test(trimmed)) {
    await apiPost('/action/chat', { message: `${from}: I can follow, goto X Y Z, mine/collect blocks, craft, attack, look around, check inventory, mark locations, and more! Say what you need.` });
  } else {
    await apiPost('/action/chat', { message: `${from}: Not sure what that means. Try: follow me, collect oak_log 5, goto 100 64 -200, look, status, or help` });
  }
  
  await apiPost('/action/complete_command', {});
}

// ── Main poll loop ────────────────────────────────────────

async function main() {
  console.log('ARES Command Responder starting...');
  console.log(`Polling ${API}/commands every ${POLL_INTERVAL/1000}s`);
  
  // Check bot health first
  try {
    const health = await apiGet('/health');
    console.log(`Bot: ${health.username} @ ${health.server} (connected: ${health.connected})`);
  } catch {
    console.error('Cannot reach bot API. Is the bot server running?');
    process.exit(1);
  }
  
  while (true) {
    try {
      const resp = await apiGet('/commands');
      const pending = (resp.data?.commands || []).filter(c => c.status === 'pending');
      
      for (const cmd of pending) {
        await executeCommand(cmd.from, cmd.command);
      }
    } catch (err) {
      console.error(`Poll error: ${err.message}`);
    }
    
    await new Promise(r => setTimeout(r, POLL_INTERVAL));
  }
}

main().catch(err => {
  console.error(`Fatal: ${err.message}`);
  process.exit(1);
});