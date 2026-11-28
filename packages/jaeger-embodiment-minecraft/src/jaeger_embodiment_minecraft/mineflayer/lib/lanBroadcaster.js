/**
 * JaegerAI Config-Driven Bedrock / PS5 / iPad LAN Broadcaster & Join Guide (CommonJS)
 *
 * Adapted from JenkinsRobotics/ares-minecraft (`bot/lan-broadcaster.js` &
 * `bot/server-manager.js`, MIT License). Zero hardcoded IPs or personal names.
 *
 * Broadcasts RakNet UNCONNECTED_PONG packets on UDP 19132 across local network
 * interfaces so PS5, iPad/iOS, Xbox, Switch, and Windows Bedrock clients
 * automatically detect a local GeyserMC cross-play server under "Friends -> LAN Games".
 */

const dgram = require("dgram");
const os = require("os");

const RAKNET_MAGIC = Buffer.from("00ffff00fefefefefdfdfdfd12345678", "hex");

function getLocalLanIp() {
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
        for (const iface of interfaces[name] || []) {
            if (iface.family === "IPv4" && !iface.internal) {
                return iface.address;
            }
        }
    }
    return "127.0.0.1";
}

function getBroadcastTargets() {
    const targets = new Set(["255.255.255.255"]);
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
        for (const iface of interfaces[name] || []) {
            if (iface.family === "IPv4" && !iface.internal) {
                const parts = iface.address.split(".");
                if (parts.length === 4) {
                    targets.add(`${parts[0]}.${parts[1]}.${parts[2]}.255`);
                }
            }
        }
    }
    return Array.from(targets);
}

class BedrockLanBroadcaster {
    constructor(options = {}) {
        this.serverName = String(options.serverName || "Jaeger Co-Op World");
        this.worldName = String(options.worldName || "Jaeger Survival");
        this.gameMode = String(options.gameMode || "Survival");
        this.port = Number(options.port || 19132);
        this.protocol = Number(options.protocol || 774);
        this.version = String(options.version || "1.21.60");
        this.maxPlayers = Number(options.maxPlayers || 10);
        this.socket = null;
        this.interval = null;
        this.running = false;
    }

    buildPongPacket(onlineCount = 1) {
        const serverGuid = BigInt("20260000000019132");
        const motd = [
            "MCPE",
            this.serverName,
            String(this.protocol),
            this.version,
            String(onlineCount),
            String(this.maxPlayers),
            String(serverGuid),
            this.worldName,
            this.gameMode,
            "1",
            String(this.port),
            String(this.port),
            "",
        ].join(";");
        const motdBytes = Buffer.from(motd, "utf8");
        const packet = Buffer.alloc(1 + 8 + 8 + 16 + 2 + motdBytes.length);
        let offset = 0;
        packet.writeUInt8(0x1c, offset++);
        packet.writeBigInt64BE(BigInt(Date.now()), offset);
        offset += 8;
        packet.writeBigInt64BE(serverGuid, offset);
        offset += 8;
        RAKNET_MAGIC.copy(packet, offset);
        offset += 16;
        packet.writeUInt16BE(motdBytes.length, offset);
        offset += 2;
        motdBytes.copy(packet, offset);
        return packet;
    }

    start(getOnlineCount = () => 1) {
        if (this.running) return this.status();
        this.socket = dgram.createSocket({ type: "udp4", reuseAddr: true });
        this.socket.on("error", () => {});
        this.socket.bind(() => {
            try {
                this.socket.setBroadcast(true);
            } catch {}
            const targets = getBroadcastTargets();
            const sendOnce = () => {
                if (!this.socket) return;
                const pkt = this.buildPongPacket(getOnlineCount());
                for (const addr of targets) {
                    try {
                        this.socket.send(pkt, 0, pkt.length, this.port, addr);
                    } catch {}
                }
            };
            sendOnce();
            this.interval = setInterval(sendOnce, 2500);
        });
        this.running = true;
        return this.status();
    }

    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
        }
        if (this.socket) {
            try {
                this.socket.close();
            } catch {}
            this.socket = null;
        }
        this.running = false;
        return this.status();
    }

    status() {
        return {
            running: this.running,
            server_name: this.serverName,
            world_name: this.worldName,
            bedrock_port: this.port,
            lan_ip: getLocalLanIp(),
        };
    }
}

function buildJoinGuide({ javaPort = 25565, bedrockPort = 19132, lanIp = null } = {}) {
    const ip = lanIp || getLocalLanIp();
    return {
        lan_ip: ip,
        java: {
            title: "Minecraft Java Edition (Mac / PC)",
            address: `${ip}:${javaPort}`,
            local: `127.0.0.1:${javaPort}`,
            steps: [
                `Open Minecraft Java Edition -> Multiplayer -> Direct Connection`,
                `Enter ${ip}:${javaPort} (or 127.0.0.1:${javaPort} on this host)`,
            ],
        },
        bedrock: {
            title: "iPad / PS5 / Xbox / Switch (requires GeyserMC + Floodgate plugin on Paper server)",
            address: `${ip}:${bedrockPort}`,
            steps: [
                `On same Wi-Fi with LAN broadcast enabled: Play -> Friends -> LAN Games`,
                `Or add Server manually: IP ${ip}, Port ${bedrockPort}`,
            ],
        },
    };
}

module.exports = {
    BedrockLanBroadcaster,
    buildJoinGuide,
    getLocalLanIp,
};
