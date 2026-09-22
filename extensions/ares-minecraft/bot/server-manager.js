/**
 * ARES Minecraft Server Manager
 *
 * Two backends, same API:
 *   rack   — native Paper + Geyser on the Jenkins rack PC (default)
 *   docker — itzg/minecraft-server on the sidecar host (dev fallback)
 *
 * GitHub 2026 stack this matches:
 *   Paper (or Purpur) + Geyser + Floodgate + ViaVersion  — cross-play
 *   spark                                               — already on the rack
 *   Pterodactyl/AMP-style controls                      — start / stop / restart,
 *                                                         live status, RCON, logs,
 *                                                         player list, join cards
 *   BedrockConnect                                      — documented for PS5
 *
 * Copyright (c) 2026 Jenkins Robotics. MIT License.
 */

import { exec, spawn } from 'child_process';
import fs from 'fs';
import net from 'net';
import os from 'os';
import path from 'path';

const CONTAINER_NAME = process.env.MC_CONTAINER_NAME || 'ares-minecraft-server';
const SERVER_DATA_DIR = process.env.MC_SERVER_DIR || path.join(os.homedir(), '.ares', 'minecraft-server');
const DEFAULT_JAVA_PORT = parseInt(process.env.MC_PORT || '25565', 10);
const DEFAULT_BEDROCK_PORT = parseInt(process.env.MC_BEDROCK_PORT || '19132', 10);

const RACK_LAN_IP = process.env.MC_RACK_LAN || '10.15.0.239';
const RACK_TS_IP = process.env.MC_RACK_TS || '100.78.245.49';
const RACK_SSH = process.env.MC_RACK_SSH || 'rackpc-lan';
const RACK_NAME = process.env.MC_RACK_NAME || 'RackPC001';
const RACK_TASK = process.env.MC_RACK_TASK || 'MCServer';
const RACK_LOG = process.env.MC_RACK_LOG || 'C:\\MinecraftServer\\logs\\latest.log';
const RACK_PROPS = process.env.MC_RACK_PROPS || 'C:\\MinecraftServer\\server.properties';
const RCON_PORT = parseInt(process.env.MC_RCON_PORT || '25575', 10);
const RCON_PASSWORD = process.env.MC_RCON_PASSWORD || 'jrserver';

export class MinecraftServerManager {
  constructor() {
    this.containerName = CONTAINER_NAME;
    this.dataDir = SERVER_DATA_DIR;
    this.javaPort = DEFAULT_JAVA_PORT;
    this.bedrockPort = DEFAULT_BEDROCK_PORT;
    this.recentLogs = [];
    this.maxLogBuffer = 250;
    this.statusCache = null;
    this.lastStatusCheck = 0;
    this.logProcess = null;
    this.backendOverride = (process.env.MC_SERVER_BACKEND || 'auto').toLowerCase();

    this.ensureDataDir();
    this.startLogStreaming();
  }

  ensureDataDir() {
    try {
      if (!fs.existsSync(this.dataDir)) {
        fs.mkdirSync(this.dataDir, { recursive: true });
      }
    } catch (err) {
      console.warn('[ServerManager] Could not create data dir:', err.message);
    }
  }

  getLanIp() {
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
      for (const iface of interfaces[name] || []) {
        if (iface.family === 'IPv4' && !iface.internal) {
          return iface.address;
        }
      }
    }
    return '127.0.0.1';
  }

  joinGuide(lanIp, tsIp) {
    const javaLan = `${lanIp}:${this.javaPort}`;
    const javaTs = `${tsIp}:${this.javaPort}`;
    return {
      java: {
        title: 'Java / PC / Mac / ARES bot',
        address: javaLan,
        tailscale: javaTs,
        steps: [
          `Multiplayer → Direct Connect → ${javaLan}`,
          `Away from home (Tailscale on): ${javaTs}`,
        ],
      },
      ios: {
        title: 'iPhone / iPad (Bedrock)',
        address: lanIp,
        port: this.bedrockPort,
        steps: [
          'Open Minecraft → Play → Servers → Add Server',
          `Server Address: ${lanIp}`,
          `Port: ${this.bedrockPort}`,
          'Name it “ARES / Jenkins” and Join',
          'Same Wi-Fi as the rack, or join Tailscale then use the Tailscale IP',
        ],
      },
      ps5: {
        title: 'PS5 (Bedrock)',
        address: lanIp,
        port: this.bedrockPort,
        steps: [
          'Same Wi-Fi as the rack (10.15.0.x)',
          'Play → Friends → look under LAN Games for “ARES Server”',
          'If LAN does not list it, use BedrockConnect:',
          'PS5 Settings → Network → Set Up Internet → Custom → DNS Manual',
          'Primary DNS 45.55.68.52  ·  Secondary 8.8.8.8',
          'Open Minecraft → Servers → join any featured server → Connect to a Server',
          `IP ${lanIp}  Port ${this.bedrockPort}`,
          'Set DNS back to Automatic when you are done (PlayStation Network needs it)',
        ],
      },
    };
  }

  execAsync(command, timeout = 15000) {
    return new Promise((resolve) => {
      exec(command, { timeout }, (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, error: error.message, stderr, stdout });
        } else {
          resolve({ ok: true, stdout: (stdout || '').trim(), stderr: (stderr || '').trim() });
        }
      });
    });
  }

  spawnAsync(bin, args, timeout = 20000) {
    return new Promise((resolve) => {
      const child = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
      let stdout = '';
      let stderr = '';
      const timer = setTimeout(() => {
        try { child.kill(); } catch (_) {}
        resolve({ ok: false, error: 'timeout', stdout, stderr });
      }, timeout);
      child.stdout.on('data', (d) => { stdout += d.toString(); });
      child.stderr.on('data', (d) => { stderr += d.toString(); });
      child.on('error', (err) => {
        clearTimeout(timer);
        resolve({ ok: false, error: err.message, stdout, stderr });
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        resolve({
          ok: code === 0,
          stdout: stdout.trim(),
          stderr: stderr.trim(),
          error: code === 0 ? null : (stderr.trim() || `exit ${code}`),
        });
      });
    });
  }

  sshRack(args, timeout = 20000) {
    return this.spawnAsync('ssh', [
      '-o', 'BatchMode=yes',
      '-o', 'ConnectTimeout=8',
      '-o', 'StrictHostKeyChecking=accept-new',
      RACK_SSH,
      ...args,
    ], timeout);
  }

  tcpOpen(host, port, timeoutMs = 1500) {
    return new Promise((resolve) => {
      const socket = net.connect({ host, port });
      const done = (ok) => {
        try { socket.destroy(); } catch (_) {}
        resolve(ok);
      };
      const timer = setTimeout(() => done(false), timeoutMs);
      socket.once('connect', () => { clearTimeout(timer); done(true); });
      socket.once('error', () => { clearTimeout(timer); done(false); });
    });
  }

  async pingJava(host, port = this.javaPort) {
    return new Promise((resolve) => {
      const socket = net.connect({ host, port });
      const timer = setTimeout(() => {
        try { socket.destroy(); } catch (_) {}
        resolve(null);
      }, 2500);
      socket.once('error', () => {
        clearTimeout(timer);
        resolve(null);
      });
      socket.once('connect', () => {
        try {
          socket.write(buildHandshake(host, port));
          socket.write(Buffer.from([0x01, 0x00]));
        } catch (_) {
          clearTimeout(timer);
          resolve(null);
        }
      });
      let buf = Buffer.alloc(0);
      socket.on('data', (chunk) => {
        buf = Buffer.concat([buf, chunk]);
        const parsed = readStatusJson(buf);
        if (parsed) {
          clearTimeout(timer);
          try { socket.destroy(); } catch (_) {}
          resolve(parsed);
        }
      });
    });
  }

  async rcon(command) {
    return rconExec(RACK_LAN_IP, RCON_PORT, RCON_PASSWORD, command);
  }

  async detectBackend() {
    if (this.backendOverride === 'rack') return 'rack';
    if (this.backendOverride === 'docker') return 'docker';
    const rackUp = await this.tcpOpen(RACK_LAN_IP, 22, 1200)
      || await this.tcpOpen(RACK_LAN_IP, this.javaPort, 800);
    if (rackUp) return 'rack';
    const hasDocker = await this.checkDockerAvailable();
    return hasDocker ? 'docker' : 'rack';
  }

  async checkDockerAvailable() {
    const res = await this.execAsync('docker --version');
    return res.ok;
  }

  async getStatus() {
    const now = Date.now();
    if (this.statusCache && now - this.lastStatusCheck < 2500) {
      return this.statusCache;
    }
    const backend = await this.detectBackend();
    const status = backend === 'rack'
      ? await this.getRackStatus()
      : await this.getDockerStatus();
    this.statusCache = status;
    this.lastStatusCheck = now;
    return status;
  }

  async getRackStatus() {
    const sshOk = await this.tcpOpen(RACK_LAN_IP, 22, 1200);
    const javaOpen = await this.tcpOpen(RACK_LAN_IP, this.javaPort, 1200);
    const slp = javaOpen ? await this.pingJava(RACK_LAN_IP) : null;

    let players = [];
    let memory = null;
    let hostName = RACK_NAME;
    if (javaOpen) {
      const list = await this.rcon('list');
      if (list.ok && list.response) {
        const match = list.response.match(/online:\s*(.*)$/i);
        if (match && match[1].trim()) {
          players = match[1].split(',').map((p) => p.trim()).filter(Boolean);
        } else {
          const countMatch = list.response.match(/are (\d+)/i);
          if (countMatch && slp && Array.isArray(slp.players?.sample)) {
            players = slp.players.sample.map((p) => p.name).filter(Boolean);
          }
        }
      }
    }
    if (sshOk) {
      const mem = await this.sshRack(['tasklist', '/FI', 'IMAGENAME eq java.exe', '/FO', 'CSV', '/NH']);
      if (mem.ok && mem.stdout.includes('java.exe')) {
        const cols = mem.stdout.split('\n')[0].split('","');
        if (cols[4]) memory = cols[4].replace(/"/g, '').trim();
      }
    }

    const motd = stripMotd(slp?.description) || 'Jenkins Robotics | ARES Server';
    const version = slp?.version?.name || (javaOpen ? 'Paper 1.21.11' : null);

    return {
      running: javaOpen,
      status: javaOpen ? 'online' : (sshOk ? 'offline' : 'rack_unreachable'),
      backend: 'rack',
      hasDocker: false,
      host: {
        name: hostName,
        lanIp: RACK_LAN_IP,
        tailscaleIp: RACK_TS_IP,
        ssh: RACK_SSH,
        reachable: sshOk,
      },
      startedAt: null,
      memory: memory || (javaOpen ? 'running' : '0 MB'),
      cpu: javaOpen ? 'n/a' : '0%',
      players,
      playerCount: players.length || slp?.players?.online || 0,
      javaPort: this.javaPort,
      bedrockPort: this.bedrockPort,
      lanIp: RACK_LAN_IP,
      tailscaleIp: RACK_TS_IP,
      crossplayReady: javaOpen,
      serverType: 'Paper + GeyserMC + Floodgate + ViaVersion',
      version,
      motd,
      join: this.joinGuide(RACK_LAN_IP, RACK_TS_IP),
    };
  }

  async getDockerStatus() {
    const hasDocker = await this.checkDockerAvailable();
    if (!hasDocker) {
      return {
        running: false,
        status: 'no_docker',
        error: 'Docker is not running on this Mac. The live world is on the rack PC — set MC_SERVER_BACKEND=rack.',
        hasDocker: false,
        backend: 'docker',
        javaPort: this.javaPort,
        bedrockPort: this.bedrockPort,
        lanIp: this.getLanIp(),
        crossplayReady: false,
        join: this.joinGuide(RACK_LAN_IP, RACK_TS_IP),
      };
    }

    const inspectRes = await this.execAsync(
      `docker inspect --format='{{.State.Status}},{{.State.Running}},{{.State.StartedAt}}' ${this.containerName}`
    );

    if (!inspectRes.ok || !inspectRes.stdout) {
      return {
        running: false,
        status: 'offline',
        hasDocker: true,
        backend: 'docker',
        containerExists: false,
        javaPort: this.javaPort,
        bedrockPort: this.bedrockPort,
        lanIp: this.getLanIp(),
        crossplayReady: false,
        join: this.joinGuide(this.getLanIp(), RACK_TS_IP),
      };
    }

    const [stateStatus, isRunningStr, startedAt] = inspectRes.stdout.split(',');
    const isRunning = isRunningStr === 'true';

    let stats = { memory: '0 MB', cpu: '0%' };
    if (isRunning) {
      const statsRes = await this.execAsync(
        `docker stats --no-stream --format '{{.MemUsage}},{{.CPUPerc}}' ${this.containerName}`
      );
      if (statsRes.ok && statsRes.stdout) {
        const [mem, cpu] = statsRes.stdout.split(',');
        stats = { memory: mem || '0 MB', cpu: cpu || '0%' };
      }
    }

    let players = [];
    if (isRunning) {
      const rconRes = await this.execAsync(`docker exec ${this.containerName} rcon-cli list`);
      if (rconRes.ok && rconRes.stdout) {
        const match = rconRes.stdout.match(/online:\s*(.*)$/i);
        if (match && match[1]) {
          players = match[1].split(',').map((p) => p.trim()).filter(Boolean);
        }
      }
    }

    return {
      running: isRunning,
      status: isRunning ? 'online' : (stateStatus || 'stopped'),
      backend: 'docker',
      hasDocker: true,
      containerExists: true,
      startedAt: startedAt || null,
      memory: stats.memory,
      cpu: stats.cpu,
      players,
      playerCount: players.length,
      javaPort: this.javaPort,
      bedrockPort: this.bedrockPort,
      lanIp: this.getLanIp(),
      crossplayReady: isRunning,
      serverType: 'Paper + GeyserMC + Floodgate',
      version: '1.21.1',
      join: this.joinGuide(this.getLanIp(), RACK_TS_IP),
    };
  }

  async startServer(customConfig = {}) {
    const backend = await this.detectBackend();
    if (backend === 'rack') {
      this.statusCache = null;
      const already = await this.tcpOpen(RACK_LAN_IP, this.javaPort, 800);
      if (already) {
        return { ok: true, message: 'Rack Paper server is already online.', backend: 'rack' };
      }
      const res = await this.sshRack(['schtasks', '/run', '/tn', RACK_TASK]);
      if (!res.ok) {
        return {
          ok: false,
          error: res.error || res.stderr || 'Could not start MCServer on the rack. Is RackPC001 logged in?',
          backend: 'rack',
        };
      }
      this.startLogStreaming();
      return {
        ok: true,
        message: `Started scheduled task ${RACK_TASK} on ${RACK_NAME}. World comes up in ~15s.`,
        backend: 'rack',
        javaPort: this.javaPort,
        bedrockPort: this.bedrockPort,
        lanIp: RACK_LAN_IP,
      };
    }
    return this.startDockerServer(customConfig);
  }

  async startDockerServer(customConfig = {}) {
    const hasDocker = await this.checkDockerAvailable();
    if (!hasDocker) {
      return { ok: false, error: 'Docker is required for the local fallback. The live world is on the rack PC.' };
    }

    const memory = customConfig.memory || '4G';
    const difficulty = customConfig.difficulty || 'normal';
    const gamemode = customConfig.gamemode || 'survival';
    const motd = customConfig.motd || '§bARES §7Companion Server §8[§aPS5 Cross-Play§8]';
    const seed = customConfig.seed || '';
    const pvp = customConfig.pvp !== false ? 'TRUE' : 'FALSE';
    const maxPlayers = customConfig.maxPlayers || 20;

    const checkRes = await this.execAsync(`docker ps -a -q -f name=^/${this.containerName}$`);
    if (checkRes.ok && checkRes.stdout) {
      const startRes = await this.execAsync(`docker start ${this.containerName}`);
      this.statusCache = null;
      if (startRes.ok) {
        this.startLogStreaming();
        return { ok: true, message: `Minecraft server container '${this.containerName}' started.` };
      }
      return { ok: false, error: startRes.error || startRes.stderr };
    }

    const geyserUrl = 'https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot';
    const floodgateUrl = 'https://download.geysermc.org/v2/projects/floodgate/versions/latest/builds/latest/downloads/spigot';
    const plugins = `${geyserUrl},${floodgateUrl}`;
    const seedParam = seed ? `-e SEED="${seed}"` : '';

    const dockerCmd = `docker run -d \\
      --name ${this.containerName} \\
      --restart unless-stopped \\
      -p ${this.javaPort}:25565 \\
      -p ${this.bedrockPort}:19132/udp \\
      -e EULA=TRUE \\
      -e TYPE=PAPER \\
      -e VERSION=1.21.1 \\
      -e MEMORY=${memory} \\
      -e DIFFICULTY=${difficulty} \\
      -e MODE=${gamemode} \\
      -e MOTD="${motd}" \\
      -e PVP=${pvp} \\
      -e MAX_PLAYERS=${maxPlayers} \\
      -e PLUGINS="${plugins}" \\
      -e ONLINE_MODE=FALSE \\
      -e ENABLE_RCON=TRUE \\
      -e RCON_PASSWORD=ares_rcon_pass \\
      -v "${this.dataDir}:/data" \\
      ${seedParam} \\
      itzg/minecraft-server:latest`;

    const createRes = await this.execAsync(dockerCmd);
    this.statusCache = null;
    if (createRes.ok) {
      this.startLogStreaming();
      return {
        ok: true,
        message: 'ARES Cross-Play Minecraft Server created and launched!',
        containerId: createRes.stdout,
        javaPort: this.javaPort,
        bedrockPort: this.bedrockPort,
        lanIp: this.getLanIp(),
      };
    }
    return { ok: false, error: createRes.error || createRes.stderr };
  }

  async stopServer() {
    const backend = await this.detectBackend();
    this.statusCache = null;
    if (backend === 'rack') {
      const res = await this.rcon('stop');
      if (res.ok) {
        return { ok: true, message: 'Rack Paper server received stop. World is saving.', backend: 'rack' };
      }
      return { ok: false, error: res.error || 'RCON stop failed — is the server up?', backend: 'rack' };
    }
    const res = await this.execAsync(`docker stop -t 15 ${this.containerName}`);
    if (res.ok) return { ok: true, message: 'Minecraft server stopped cleanly.' };
    return { ok: false, error: res.error || res.stderr };
  }

  async restartServer() {
    const backend = await this.detectBackend();
    this.statusCache = null;
    if (backend === 'rack') {
      const up = await this.tcpOpen(RACK_LAN_IP, this.javaPort, 800);
      if (up) {
        const stopped = await this.rcon('stop');
        if (!stopped.ok) {
          return { ok: false, error: stopped.error || 'Could not stop the rack server.', backend: 'rack' };
        }
        for (let i = 0; i < 20; i += 1) {
          await sleep(1000);
          if (!(await this.tcpOpen(RACK_LAN_IP, this.javaPort, 400))) break;
        }
      }
      return this.startServer();
    }
    const res = await this.execAsync(`docker restart -t 15 ${this.containerName}`);
    if (res.ok) {
      this.startLogStreaming();
      return { ok: true, message: 'Minecraft server restarted.' };
    }
    return { ok: false, error: res.error || res.stderr };
  }

  async sendCommand(command) {
    if (!command || !command.trim()) {
      return { ok: false, error: 'Command cannot be empty' };
    }
    const cleanCmd = command.startsWith('/') ? command.slice(1) : command;
    const backend = await this.detectBackend();
    if (backend === 'rack') {
      const res = await this.rcon(cleanCmd);
      if (res.ok) return { ok: true, response: res.response };
      return { ok: false, error: res.error || 'RCON failed' };
    }
    const res = await this.execAsync(`docker exec ${this.containerName} rcon-cli ${cleanCmd}`);
    if (res.ok) return { ok: true, response: res.stdout };
    return { ok: false, error: res.error || res.stderr };
  }

  async getConfig() {
    const backend = await this.detectBackend();
    if (backend === 'rack') {
      const res = await this.sshRack([
        'powershell', '-NoProfile', '-Command',
        `Get-Content -Raw '${RACK_PROPS}'`,
      ]);
      const properties = parseProperties(res.ok ? res.stdout : '');
      return {
        motd: properties.motd || 'Jenkins Robotics | ARES Server',
        difficulty: properties.difficulty || 'easy',
        gamemode: properties.gamemode || 'survival',
        maxPlayers: parseInt(properties['max-players'] || '12', 10),
        pvp: properties.pvp !== 'false',
        seed: properties['level-seed'] || '',
        onlineMode: properties['online-mode'] === 'true',
        javaPort: this.javaPort,
        bedrockPort: this.bedrockPort,
        lanIp: RACK_LAN_IP,
        tailscaleIp: RACK_TS_IP,
        host: RACK_NAME,
        dataDir: 'C:\\MinecraftServer',
        backend: 'rack',
      };
    }

    const propsPath = path.join(this.dataDir, 'server.properties');
    const properties = fs.existsSync(propsPath)
      ? parseProperties(fs.readFileSync(propsPath, 'utf8'))
      : {};
    return {
      motd: properties.motd || 'ARES Companion Server',
      difficulty: properties.difficulty || 'normal',
      gamemode: properties.gamemode || 'survival',
      maxPlayers: parseInt(properties['max-players'] || '20', 10),
      pvp: properties.pvp !== 'false',
      seed: properties['level-seed'] || '',
      onlineMode: properties['online-mode'] === 'true',
      javaPort: this.javaPort,
      bedrockPort: this.bedrockPort,
      lanIp: this.getLanIp(),
      dataDir: this.dataDir,
      backend: 'docker',
    };
  }

  async updateConfig(newConfig) {
    const backend = await this.detectBackend();
    if (backend === 'rack') {
      if (newConfig.difficulty) {
        await this.rcon(`difficulty ${newConfig.difficulty}`);
      }
      return {
        ok: true,
        message: 'Live difficulty applied over RCON. MOTD / seed / max players still need a restart after editing server.properties on the rack.',
        backend: 'rack',
      };
    }

    const propsPath = path.join(this.dataDir, 'server.properties');
    if (!fs.existsSync(propsPath)) {
      return { ok: false, error: 'server.properties does not exist yet. Start the server once first.' };
    }
    try {
      let raw = fs.readFileSync(propsPath, 'utf8');
      const map = {
        motd: 'motd',
        difficulty: 'difficulty',
        gamemode: 'gamemode',
        maxPlayers: 'max-players',
        pvp: 'pvp',
        seed: 'level-seed',
      };
      for (const [key, propKey] of Object.entries(map)) {
        if (newConfig[key] !== undefined) {
          const val = String(newConfig[key]);
          const regex = new RegExp(`^${propKey}=.*$`, 'm');
          if (regex.test(raw)) raw = raw.replace(regex, `${propKey}=${val}`);
          else raw += `\n${propKey}=${val}`;
        }
      }
      fs.writeFileSync(propsPath, raw, 'utf8');
      return { ok: true, message: 'Server settings saved. Restart server to apply changes.' };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }

  startLogStreaming() {
    if (this.logProcess) {
      try { this.logProcess.kill(); } catch (_) {}
      this.logProcess = null;
    }
    const backend = this.backendOverride === 'docker' ? 'docker' : 'rack';
    try {
      if (backend === 'rack') {
        this.logProcess = spawn('ssh', [
          '-o', 'BatchMode=yes',
          '-o', 'ConnectTimeout=8',
          RACK_SSH,
          'powershell', '-NoProfile', '-Command',
          `Get-Content -Path '${RACK_LOG}' -Tail 40 -Wait`,
        ]);
      } else {
        this.logProcess = spawn('docker', ['logs', '-f', '--tail', '50', this.containerName]);
      }
      const push = (data) => {
        const lines = data.toString().split('\n').filter(Boolean);
        for (const line of lines) {
          this.recentLogs.push(line);
          if (this.recentLogs.length > this.maxLogBuffer) this.recentLogs.shift();
        }
      };
      this.logProcess.stdout.on('data', push);
      this.logProcess.stderr.on('data', push);
      this.logProcess.on('error', () => {});
    } catch (_) {}
  }

  getLogs(limit = 100) {
    return this.recentLogs.slice(-limit);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseProperties(raw) {
  const properties = {};
  String(raw || '').split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
      const [k, ...v] = trimmed.split('=');
      properties[k.trim()] = v.join('=').trim();
    }
  });
  return properties;
}

function stripMotd(description) {
  if (!description) return '';
  if (typeof description === 'string') return description.replace(/§./g, '');
  if (description.text) return String(description.text).replace(/§./g, '');
  return '';
}

function writeVarInt(value) {
  const bytes = [];
  let v = value >>> 0;
  while (true) {
    if ((v & ~0x7f) === 0) {
      bytes.push(v);
      return Buffer.from(bytes);
    }
    bytes.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
}

function readVarInt(buf, offset) {
  let num = 0;
  let shift = 0;
  let i = offset;
  while (i < buf.length) {
    const b = buf[i];
    num |= (b & 0x7f) << shift;
    i += 1;
    if ((b & 0x80) === 0) return { value: num, size: i - offset };
    shift += 7;
    if (shift > 35) return null;
  }
  return null;
}

function buildHandshake(host, port) {
  const hostBuf = Buffer.from(host, 'utf8');
  const payload = Buffer.concat([
    Buffer.from([0x00]),
    writeVarInt(-1 >>> 0),
    writeVarInt(hostBuf.length),
    hostBuf,
    Buffer.from([(port >> 8) & 0xff, port & 0xff]),
    writeVarInt(1),
  ]);
  return Buffer.concat([writeVarInt(payload.length), payload]);
}

function readStatusJson(buf) {
  const len = readVarInt(buf, 0);
  if (!len) return null;
  if (buf.length < len.size + len.value) return null;
  const id = readVarInt(buf, len.size);
  if (!id) return null;
  const strLen = readVarInt(buf, len.size + id.size);
  if (!strLen) return null;
  const start = len.size + id.size + strLen.size;
  const jsonBuf = buf.subarray(start, start + strLen.value);
  if (jsonBuf.length < strLen.value) return null;
  try {
    return JSON.parse(jsonBuf.toString('utf8'));
  } catch (_) {
    return null;
  }
}

function rconExec(host, port, password, command) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    let buf = Buffer.alloc(0);
    let authed = false;
    const timer = setTimeout(() => {
      socket.destroy();
      resolve({ ok: false, error: 'RCON timeout' });
    }, 6000);

    function send(id, type, body) {
      const payload = Buffer.alloc(4 + 4 + Buffer.byteLength(body) + 2);
      payload.writeInt32LE(id, 0);
      payload.writeInt32LE(type, 4);
      payload.write(body, 8, 'utf8');
      const header = Buffer.alloc(4);
      header.writeInt32LE(payload.length, 0);
      socket.write(Buffer.concat([header, payload]));
    }

    socket.once('connect', () => send(1, 3, password));
    socket.on('error', (err) => {
      clearTimeout(timer);
      resolve({ ok: false, error: err.message });
    });
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      while (buf.length >= 4) {
        const size = buf.readInt32LE(0);
        if (buf.length < 4 + size) return;
        const id = buf.readInt32LE(4);
        const type = buf.readInt32LE(8);
        const body = buf.subarray(12, 4 + size - 2).toString('utf8');
        buf = buf.subarray(4 + size);
        if (!authed) {
          if (id === -1) {
            clearTimeout(timer);
            socket.destroy();
            resolve({ ok: false, error: 'RCON auth failed' });
            return;
          }
          authed = true;
          send(2, 2, command);
          continue;
        }
        if (type === 0 || type === 2) {
          clearTimeout(timer);
          socket.destroy();
          resolve({ ok: true, response: body });
          return;
        }
      }
    });
  });
}

const serverManager = new MinecraftServerManager();
export default serverManager;
export {
  buildHandshake,
  readStatusJson,
  stripMotd,
};
