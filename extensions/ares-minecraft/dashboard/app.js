// ARES Minecraft Companion & Server Manager Dashboard Client
const SIDECAR_URL = window.location.port === '8788' 
  ? '/api/extensions/ares-minecraft/sidecar' 
  : 'http://127.0.0.1:3847';

let currentTab = 'companion';
let pollTimer = null;
let serverPollTimer = null;

// ═══════════════════════════════════════════════════════════════
// Tab Switching
// ═══════════════════════════════════════════════════════════════

function switchTab(tabId) {
  currentTab = tabId;
  const compView = document.getElementById('viewCompanion');
  const srvView = document.getElementById('viewServer');
  const tabBtnComp = document.getElementById('tabBtnCompanion');
  const tabBtnSrv = document.getElementById('tabBtnServer');
  const vitals = document.getElementById('vitalsContainer');

  if (tabId === 'server') {
    compView.style.display = 'none';
    srvView.style.display = 'grid';
    tabBtnComp.classList.remove('active');
    tabBtnSrv.classList.add('active');
    vitals.style.opacity = '0.5';
    fetchServerStatus();
    fetchServerConfig();
    fetchServerLogs();
  } else {
    compView.style.display = 'grid';
    srvView.style.display = 'none';
    tabBtnComp.classList.add('active');
    tabBtnSrv.classList.remove('active');
    vitals.style.opacity = '1.0';
    fetchStatus();
  }
}

// ═══════════════════════════════════════════════════════════════
// Companion Bot Status
// ═══════════════════════════════════════════════════════════════

async function fetchStatus() {
  try {
    const res = await fetch(`${SIDECAR_URL}/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderStatus(data.data || data);
  } catch (err) {
    renderOffline();
  }
}

function renderStatus(data) {
  const statusBadge = document.getElementById('statusBadge');
  const statusDot = document.getElementById('statusDot');
  if (data.online || data.health !== undefined) {
    statusBadge.textContent = 'ONLINE';
    statusBadge.style.color = '#00FF88';
    statusBadge.style.borderColor = '#00FF88';
    statusDot.className = 'status-indicator-dot online';
  } else {
    statusBadge.textContent = 'DISCONNECTED';
    statusBadge.style.color = '#FF4444';
    statusBadge.style.borderColor = '#FF4444';
    statusDot.className = 'status-indicator-dot offline';
  }

  // Health & Food
  const health = data.health ?? 20;
  const food = data.food ?? 20;
  document.getElementById('healthVal').textContent = `${health.toFixed(1)} / 20`;
  document.getElementById('healthFill').style.width = `${Math.min(100, (health / 20) * 100)}%`;

  document.getElementById('foodVal').textContent = `${food.toFixed(1)} / 20`;
  document.getElementById('foodFill').style.width = `${Math.min(100, (food / 20) * 100)}%`;

  // Coordinates
  if (data.position) {
    document.getElementById('coordX').textContent = data.position.x?.toFixed(1) ?? '0.0';
    document.getElementById('coordY').textContent = data.position.y?.toFixed(1) ?? '64.0';
    document.getElementById('coordZ').textContent = data.position.z?.toFixed(1) ?? '0.0';
  }
  
  if (data.dimension) {
    document.getElementById('dimensionBadge').textContent = data.dimension;
  }
  if (data.biome) {
    document.getElementById('biomeVal').textContent = data.biome;
  }
  if (data.heading) {
    document.getElementById('headingVal').textContent = data.heading;
  }

  // Players Radar
  if (data.players && Array.isArray(data.players)) {
    renderPlayers(data.players);
  }

  // Inventory
  if (data.inventory && Array.isArray(data.inventory)) {
    renderInventory(data.inventory);
  }

  // Activity Status
  document.getElementById('botActivity').textContent = data.activity || 'IDLE';
}

function renderOffline() {
  const statusBadge = document.getElementById('statusBadge');
  const statusDot = document.getElementById('statusDot');
  statusBadge.textContent = 'OFFLINE';
  statusBadge.style.color = '#FF4444';
  statusBadge.style.borderColor = '#FF4444';
  statusDot.className = 'status-indicator-dot offline';
}

function renderPlayers(players) {
  const list = document.getElementById('playerRadarList');
  if (!players || players.length === 0) {
    list.innerHTML = '<div class="player-row" style="color: var(--text-muted); font-size: 12px;">No players in range.</div>';
    return;
  }

  list.innerHTML = players.map(p => {
    const isVip = p.name === 'Shu_Walker' || p.name === 'Blackstar3156';
    const label = p.name === 'Shu_Walker' ? ' (Matthew)' : (p.name === 'Blackstar3156' ? ' (Sean)' : '');
    const distText = p.distance ? `${p.distance.toFixed(1)} blocks away` : 'Nearby';
    
    return `
      <div class="player-row ${isVip ? 'vip-player' : ''}">
        <img src="https://mc-heads.net/avatar/${encodeURIComponent(p.name)}/24" class="player-head" alt="${p.name}" onerror="this.src='https://mc-heads.net/avatar/Steve/24'">
        <div class="player-info">
          <span class="player-name">${p.name}${label}</span>
          <span class="player-dist">${distText}</span>
        </div>
        <button class="mini-action-btn" onclick="followPlayer('${p.name}')">Follow</button>
      </div>
    `;
  }).join('');
}

function renderInventory(items) {
  const grid = document.getElementById('inventoryGrid');
  document.getElementById('invTotalCount').textContent = `${items.length} slots`;
  
  grid.innerHTML = items.slice(0, 18).map(item => `
    <div class="inv-slot" title="${item.name} (${item.count})">
      <span>${item.icon || '📦'}</span>
      <span class="inv-count-badge">${item.count > 1 ? item.count : ''}</span>
    </div>
  `).join('');
}

async function runCommand(action, params = {}) {
  try {
    const res = await fetch(`${SIDECAR_URL}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...params })
    });
    const result = await res.json();
    appendChatLog(`[Action] ${action}: ${result.result || result.message || 'Executed'}`);
  } catch (err) {
    appendChatLog(`[Error] Failed to execute ${action}: ${err.message}`);
  }
}

async function followPlayer(username) {
  runCommand('follow', { target: username });
}

async function goToCoords() {
  const x = parseFloat(document.getElementById('targetX').value);
  const y = parseFloat(document.getElementById('targetY').value);
  const z = parseFloat(document.getElementById('targetZ').value);
  if (isNaN(x) || isNaN(y) || isNaN(z)) {
    alert('Please enter valid X, Y, Z coordinates.');
    return;
  }
  runCommand('goto', { x, y, z });
}

// ═══════════════════════════════════════════════════════════════
// Server Manager & PS5 Cross-Play
// ═══════════════════════════════════════════════════════════════

async function fetchServerStatus() {
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    const data = body.data || body;
    renderServerStatus(data);
  } catch (err) {
    renderServerOffline(err.message);
  }
}

function renderServerStatus(data) {
  const badge = document.getElementById('srvStatusBadge');
  const btnStart = document.getElementById('btnStartServer');
  const btnStop = document.getElementById('btnStopServer');
  const btnRestart = document.getElementById('btnRestartServer');

  if (data.running) {
    badge.textContent = 'ONLINE';
    badge.className = 'hud-badge status-badge online';
    badge.style.color = '#00FF88';
    badge.style.borderColor = '#00FF88';
    if (btnStart) btnStart.disabled = true;
    if (btnStop) btnStop.disabled = false;
    if (btnRestart) btnRestart.disabled = false;
  } else {
    badge.textContent = data.status === 'no_docker' ? 'DOCKER MISSING' : (data.status === 'rack_unreachable' ? 'RACK UNREACHABLE' : 'OFFLINE');
    badge.className = 'hud-badge status-badge offline';
    badge.style.color = '#FF4444';
    badge.style.borderColor = '#FF4444';
    if (btnStart) btnStart.disabled = false;
    if (btnStop) btnStop.disabled = true;
    if (btnRestart) btnRestart.disabled = true;
  }

  const hostName = (data.host && data.host.name) || (data.backend === 'rack' ? 'RackPC001 (Jenkins Rack)' : 'Local Host');
  const hostIp = (data.host && data.host.lanIp) || data.lanIp || '10.15.0.239';
  if (document.getElementById('srvHostName')) document.getElementById('srvHostName').textContent = hostName;
  if (document.getElementById('srvHostIp')) document.getElementById('srvHostIp').textContent = hostIp;
  if (document.getElementById('srvBackendType')) document.getElementById('srvBackendType').textContent = data.backend === 'rack' ? 'Rack PC (Live)' : 'Docker Fallback';
  if (document.getElementById('srvMemVal')) document.getElementById('srvMemVal').textContent = data.memory || '1.75 GB';
  if (document.getElementById('srvPlayersVal')) document.getElementById('srvPlayersVal').textContent = `${data.playerCount || 0} players`;
  if (document.getElementById('srvEngineVal')) document.getElementById('srvEngineVal').textContent = data.version || 'Paper 1.21.11';
  if (document.getElementById('srvJoinIosIp')) document.getElementById('srvJoinIosIp').textContent = hostIp;
  if (document.getElementById('srvJoinJavaIp')) document.getElementById('srvJoinJavaIp').textContent = `${hostIp}:${data.javaPort || 25565}`;
}

function renderServerOffline(errMsg) {
  const badge = document.getElementById('srvStatusBadge');
  if (badge) {
    badge.textContent = 'UNREACHABLE';
    badge.style.color = '#FF4444';
    badge.style.borderColor = '#FF4444';
  }
}

async function sendQuickCommand(cmd) {
  const input = document.getElementById('consoleInput');
  if (input) input.value = cmd;
  await sendConsoleCommand();
}

async function startServer() {
  appendConsoleLog('[Action] Launching Minecraft Cross-Play server container...');
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        difficulty: document.getElementById('cfgDifficulty').value,
        gamemode: document.getElementById('cfgGamemode').value,
        motd: document.getElementById('cfgMotd').value,
        maxPlayers: parseInt(document.getElementById('cfgMaxPlayers').value, 10),
        seed: document.getElementById('cfgSeed').value,
        pvp: document.getElementById('cfgPvp').checked,
      })
    });
    const data = await res.json();
    if (data.ok) {
      appendConsoleLog(`[Server] ${data.message || 'Server started successfully!'}`);
      fetchServerStatus();
    } else {
      appendConsoleLog(`[Error] Failed to start server: ${data.error}`);
    }
  } catch (err) {
    appendConsoleLog(`[Error] Network error starting server: ${err.message}`);
  }
}

async function stopServer() {
  if (!confirm('Are you sure you want to stop the Minecraft server?')) return;
  appendConsoleLog('[Action] Stopping Minecraft server gracefully...');
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/stop`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      appendConsoleLog(`[Server] ${data.message || 'Server stopped.'}`);
      fetchServerStatus();
    } else {
      appendConsoleLog(`[Error] Failed to stop server: ${data.error}`);
    }
  } catch (err) {
    appendConsoleLog(`[Error] Network error stopping server: ${err.message}`);
  }
}

async function restartServer() {
  appendConsoleLog('[Action] Restarting Minecraft server...');
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/restart`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      appendConsoleLog(`[Server] ${data.message || 'Server restarted.'}`);
      fetchServerStatus();
    } else {
      appendConsoleLog(`[Error] Failed to restart: ${data.error}`);
    }
  } catch (err) {
    appendConsoleLog(`[Error] Network error restarting server: ${err.message}`);
  }
}

async function fetchServerConfig() {
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/config`);
    if (!res.ok) return;
    const body = await res.json();
    const cfg = body.data || body;
    if (cfg.motd) document.getElementById('cfgMotd').value = cfg.motd;
    if (cfg.difficulty) document.getElementById('cfgDifficulty').value = cfg.difficulty;
    if (cfg.gamemode) document.getElementById('cfgGamemode').value = cfg.gamemode;
    if (cfg.maxPlayers) document.getElementById('cfgMaxPlayers').value = cfg.maxPlayers;
    if (cfg.seed) document.getElementById('cfgSeed').value = cfg.seed;
    if (cfg.pvp !== undefined) document.getElementById('cfgPvp').checked = cfg.pvp;
  } catch (_) {}
}

async function saveServerConfig() {
  const payload = {
    motd: document.getElementById('cfgMotd').value,
    difficulty: document.getElementById('cfgDifficulty').value,
    gamemode: document.getElementById('cfgGamemode').value,
    maxPlayers: parseInt(document.getElementById('cfgMaxPlayers').value, 10),
    seed: document.getElementById('cfgSeed').value,
    pvp: document.getElementById('cfgPvp').checked,
  };
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
      appendConsoleLog(`[Settings] ${data.message || 'Settings saved successfully.'}`);
      alert('Server settings saved! Restart the server to apply changes.');
    } else {
      alert(`Failed to save settings: ${data.error}`);
    }
  } catch (err) {
    alert(`Network error saving settings: ${err.message}`);
  }
}

async function fetchServerLogs() {
  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/logs?limit=80`);
    if (!res.ok) return;
    const body = await res.json();
    const logs = (body.data && body.data.logs) || body.logs || [];
    renderConsoleLogs(logs);
  } catch (_) {}
}

function renderConsoleLogs(lines) {
  const consoleEl = document.getElementById('consoleOutput');
  if (!lines || lines.length === 0) return;
  consoleEl.innerHTML = lines.map(line => `<div class="console-line">${escapeHtml(line)}</div>`).join('');
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

async function sendConsoleCommand() {
  const input = document.getElementById('consoleInput');
  const cmd = input.value.trim();
  if (!cmd) return;
  input.value = '';
  appendConsoleLog(`> ${cmd}`);

  try {
    const res = await fetch(`${SIDECAR_URL}/api/server/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    if (data.ok) {
      appendConsoleLog(data.response || '[Command Executed]');
    } else {
      appendConsoleLog(`[Error] ${data.error}`);
    }
  } catch (err) {
    appendConsoleLog(`[Error] Command failed: ${err.message}`);
  }
}

function appendConsoleLog(text) {
  const consoleEl = document.getElementById('consoleOutput');
  const div = document.createElement('div');
  div.className = 'console-line';
  div.textContent = text;
  consoleEl.appendChild(div);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════
// Chat & Utilities
// ═══════════════════════════════════════════════════════════════

async function sendChatMsg() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  try {
    await fetch(`${SIDECAR_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg })
    });
    appendChatLog(`[You]: ${msg}`);
  } catch (err) {
    appendChatLog(`[Error]: Failed to send message: ${err.message}`);
  }
}

function appendChatLog(text) {
  const feed = document.getElementById('chatFeed');
  if (!feed) return;
  const div = document.createElement('div');
  div.className = 'chat-msg';
  div.textContent = text;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function clearChatLog() {
  const feed = document.getElementById('chatFeed');
  if (feed) feed.innerHTML = '';
}

async function buildStructure(structure) {
  appendChatLog(`[Civil Engine] Commencing build order: ${structure}...`);
  try {
    const res = await fetch(`${SIDECAR_URL}/village/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ structure })
    });
    const data = await res.json();
    if (data.ok) {
      appendChatLog(`[Civil Engine] ${structure} construction initiated!`);
    } else {
      appendChatLog(`[Error] Failed to build ${structure}: ${data.error}`);
    }
  } catch (err) {
    appendChatLog(`[Error] Construction request failed: ${err.message}`);
  }
}

// ═══════════════════════════════════════════════════════════════
// Dual-Tab & Neural Stream Engine
// ═══════════════════════════════════════════════════════════════

let activeCommTab = 'chat';

function switchCommTab(tab) {
  activeCommTab = tab;
  const btnChat = document.getElementById('tabBtnChat');
  const btnBrain = document.getElementById('tabBtnBrain');
  const pnlChat = document.getElementById('panelChatTab');
  const pnlBrain = document.getElementById('panelBrainTab');

  if (tab === 'chat') {
    btnChat?.classList.add('active');
    btnBrain?.classList.remove('active');
    if (pnlChat) pnlChat.style.display = 'flex';
    if (pnlBrain) pnlBrain.style.display = 'none';
  } else {
    btnChat?.classList.remove('active');
    btnBrain?.classList.add('active');
    if (pnlChat) pnlChat.style.display = 'none';
    if (pnlBrain) pnlBrain.style.display = 'flex';
    fetchBrainStream();
  }
}

function clearActiveTabLog() {
  if (activeCommTab === 'chat') {
    clearChatLog();
  } else {
    const feed = document.getElementById('neuralThoughtsFeed');
    if (feed) feed.innerHTML = '';
  }
}

async function fetchBrainStream() {
  try {
    const res = await fetch(`${SIDECAR_URL}/brain/thoughts`);
    if (!res.ok) return;
    const json = await res.json();
    const data = json.data || {};

    const goalEl = document.getElementById('brainActiveGoal');
    if (goalEl && data.activeMission?.title) {
      goalEl.textContent = data.activeMission.title;
    }

    const modelEl = document.getElementById('brainModelName');
    if (modelEl && data.model) {
      modelEl.textContent = `${data.model} (Local MLX GPU • ~38ms)`;
    }

    const posEl = document.getElementById('brainPerceptionState');
    if (posEl && data.perception?.position) {
      const p = data.perception.position;
      posEl.textContent = `Pos (${p.x}, ${p.y}, ${p.z}) • HP ${data.perception.health}/20 • Food ${data.perception.food}/20`;
    }

    const badgeEl = document.getElementById('thoughtCountBadge');
    if (badgeEl && data.thoughts) {
      badgeEl.textContent = `${data.thoughts.length} thoughts recorded`;
    }

    renderNeuralThoughts(data.thoughts || []);
  } catch (_) {}
}

function renderNeuralThoughts(thoughts) {
  const feed = document.getElementById('neuralThoughtsFeed');
  if (!feed) return;

  feed.innerHTML = thoughts.map(t => {
    let color = '#08EBF1';
    let bg = 'rgba(8,235,241,0.1)';
    if (t.type === 'mission') { color = '#FFCC00'; bg = 'rgba(255,204,0,0.15)'; }
    if (t.type === 'action') { color = '#00FF88'; bg = 'rgba(0,255,136,0.15)'; }
    if (t.type === 'combat') { color = '#FF4444'; bg = 'rgba(255,68,68,0.15)'; }
    if (t.type === 'plan') { color = '#c084fc'; bg = 'rgba(192,132,252,0.15)'; }
    if (t.type === 'success') { color = '#22c55e'; bg = 'rgba(34,197,94,0.15)'; }

    return `
      <div style="background:#0c1017;border:1px solid #1a2333;border-left:3px solid ${color};border-radius:4px;padding:6px 10px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
          <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:9px;background:${bg};color:${color};padding:1px 5px;border-radius:2px;font-weight:800;text-transform:uppercase;">${t.type || 'THOUGHT'}</span>
            <strong style="color:#fff;font-size:11px;">${escapeHtml(t.title || 'Reasoning')}</strong>
          </div>
          <span style="font-size:10px;color:#64748b;">${t.time || ''}</span>
        </div>
        <div style="color:#94a3b8;line-height:1.4;font-size:11px;">${escapeHtml(t.detail || '')}</div>
      </div>
    `;
  }).join('');

  feed.scrollTop = feed.scrollHeight;
}

async function dispatchQuickMission(task) {
  appendChatLog(`[Commander]: ${task}`);
  switchCommTab('brain');
  try {
    const res = await fetch(`${SIDECAR_URL}/brain/mission`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task, commander: 'Shu_Walker' })
    });
    const data = await res.json();
    if (data.ok) {
      fetchBrainStream();
    }
  } catch (err) {
    appendChatLog(`[Error] Failed to dispatch mission: ${err.message}`);
  }
}

async function dispatchDirectTask() {
  const input = document.getElementById('directTaskInput');
  const task = input?.value?.trim();
  if (!task) return;
  input.value = '';
  await dispatchQuickMission(task);
}

function clearThoughtsLog() {
  const feed = document.getElementById('neuralThoughtsFeed');
  if (feed) feed.innerHTML = '';
}

async function dispatchCustomMission() {
  const input = document.getElementById('chatInput');
  const task = input?.value?.trim();
  if (!task) return;
  input.value = '';
  dispatchQuickMission(task);
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ═══════════════════════════════════════════════════════════════
// Initialization
// ═══════════════════════════════════════════════════════════════

function initApp() {
  if (document.getElementById('viewCompanion')) {
    fetchStatus();
    fetchBrainStream();
    if (!pollTimer) {
      pollTimer = setInterval(() => {
        if (currentTab === 'companion') {
          fetchStatus();
        } else {
          fetchServerStatus();
          fetchServerLogs();
        }
        if (activeCommTab === 'brain') {
          fetchBrainStream();
        }
      }, 2000);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
