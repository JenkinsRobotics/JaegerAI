/**
 * ARES Bedrock LAN Broadcaster
 *
 * Broadcasts RakNet UNCONNECTED_PONG packets on UDP 19132 across all local
 * network interfaces so that PlayStation 5, iPad / iOS, Xbox, Nintendo Switch,
 * and Windows Bedrock clients automatically detect the ARES Rack server
 * under "Play → Friends → LAN Games" natively without any third-party apps.
 *
 * Copyright (c) 2026 Jenkins Robotics. MIT License.
 */

import dgram from 'dgram';
import os from 'os';

const MAGIC = Buffer.from('00ffff00fefefefefdfdfdfd12345678', 'hex');
const BROADCAST_PORT = 19132;

export class BedrockLanBroadcaster {
  constructor(options = {}) {
    this.serverName = options.serverName || '§bARES §f| §aJenkins Rack';
    this.worldName = options.worldName || 'ARES Cross-Play World';
    this.gameMode = options.gameMode || 'Survival';
    this.port = options.port || 19132;
    this.protocol = options.protocol || 774;
    this.version = options.version || '1.21.60';
    this.maxPlayers = options.maxPlayers || 20;
    this.socket = null;
    this.interval = null;
    this.isRunning = false;
  }

  buildPongPacket(onlineCount = 0) {
    const serverGuid = BigInt('1234567890123456789');
    // Format: MCPE;ServerName;Protocol;Version;OnlinePlayers;MaxPlayers;ServerGUID;WorldName;GameMode;Difficulty;PortIPv4;PortIPv6;
    const motd = [
      'MCPE',
      this.serverName,
      String(this.protocol),
      this.version,
      String(onlineCount),
      String(this.maxPlayers),
      String(serverGuid),
      this.worldName,
      this.gameMode,
      '1', // Difficulty: Normal
      String(this.port),
      String(this.port),
      ''
    ].join(';');

    const motdBytes = Buffer.from(motd, 'utf8');
    const packet = Buffer.alloc(1 + 8 + 8 + 16 + 2 + motdBytes.length);
    let offset = 0;

    // 0x1c = ID_UNCONNECTED_PONG
    packet.writeUInt8(0x1c, offset++);
    packet.writeBigInt64BE(BigInt(Date.now()), offset);
    offset += 8;
    packet.writeBigInt64BE(serverGuid, offset);
    offset += 8;
    MAGIC.copy(packet, offset);
    offset += 16;
    packet.writeUInt16BE(motdBytes.length, offset);
    offset += 2;
    motdBytes.copy(packet, offset);

    return packet;
  }

  getBroadcastTargets() {
    const targets = new Set(['255.255.255.255', '10.15.0.255']);
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
      for (const iface of interfaces[name] || []) {
        if (iface.family === 'IPv4' && !iface.internal) {
          const parts = iface.address.split('.');
          if (parts.length === 4) {
            targets.add(`${parts[0]}.${parts[1]}.${parts[2]}.255`);
          }
        }
      }
    }
    return Array.from(targets);
  }

  start(playerCountFn = () => 0) {
    if (this.isRunning) return;
    this.isRunning = true;

    try {
      this.socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
      this.socket.on('error', (err) => {
        console.warn('[LAN-Broadcaster] Socket error:', err.message);
      });

      this.socket.bind(0, () => {
        try {
          this.socket.setBroadcast(true);
        } catch (_) {}

        console.log(`[LAN-Broadcaster] Bedrock native LAN discovery active on UDP ${BROADCAST_PORT}`);

        // Broadcast every 1.5 seconds for instant detection on PS5 & iPad
        this.interval = setInterval(() => {
          if (!this.socket || !this.isRunning) return;
          const count = typeof playerCountFn === 'function' ? playerCountFn() : 0;
          const packet = this.buildPongPacket(count);
          const targets = this.getBroadcastTargets();

          for (const target of targets) {
            this.socket.send(packet, 0, packet.length, BROADCAST_PORT, target, () => {});
          }
        }, 1500);
      });
    } catch (err) {
      console.warn('[LAN-Broadcaster] Failed to start:', err.message);
    }
  }

  stop() {
    this.isRunning = false;
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
      this.socket = null;
    }
  }
}

export default new BedrockLanBroadcaster();
