# ARES Minecraft Companion 🎮🤖

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ARES Extension](https://img.shields.io/badge/ARES-Extension-08EBF1.svg)](https://github.com/JenkinsRobotics)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D18.0.0-green.svg)](https://nodejs.org)

**ARES Minecraft Companion** is an embodied autonomous AI companion that lives and acts inside your Minecraft world. Built by **Jenkins Robotics** using [Mineflayer](https://github.com/PrismarineJS/mineflayer), it connects directly to **ARES** and **Jaeger AI** to provide real-time perception, dynamic 3D pathfinding, combat defense, resource gathering, and multi-player social awareness.

---

## 🌟 Key Features

* **Embodied AI Companion**: Moves, explores, mines, crafts, eats, and fights with genuine initiative and autonomy.
* **Server Manager & PS5 Cross-Play**: One-click Paper server hosting with **GeyserMC** & **Floodgate** cross-play enabling PS5, Xbox, Switch, and Mobile players to play with ARES.
* **ARES WebUI Dashboard**: Embedded live HUD featuring Companion HUD (health, hunger, 3D coordinates, equipped armor, inventory grid, player radar) and dedicated Server Manager tab.
* **Player Recognition**: Recognizes friends and VIP players (**Matthew / Shu_Walker** and **Sean / Blackstar3156**), auto-whispers, and follows orders.
* **Agent Tool Suite (`mc_*`)**: Exposes native Python and MCP tool bindings for both gameplay (`mc_mine`, `mc_follow_player`) and server operations (`mc_server_status`, `mc_server_start`, `mc_server_command`).
* **Model Context Protocol (MCP)**: Native stdio MCP server for seamless integration with external AI agent runtimes (ARES, Jaeger AI, Claude Code, Cursor).
* **Self-Healing Sidecar Service**: Runs as a managed local daemon on port `3847` with health-probe endpoints and automated reconnect.

---

## 📁 Repository Structure

```
ares-minecraft/
├── manifest.json              # ARES Extension & Plugin manifest
├── README.md                  # Documentation & Quickstart
├── LICENSE                    # MIT License
├── dashboard/                 # Embedded WebUI Dashboard Panel
│   ├── index.html             # Live Bot HUD + Server Manager & PS5 Cross-Play Panel
│   ├── app.js                 # Realtime status poller, server lifecycle & command dispatcher
│   └── style.css              # Cyber-robotic theme matching ARES UI
├── bot/                       # Mineflayer Sidecar & Server Manager (Node.js)
│   ├── package.json           # Bot engine dependencies
│   ├── server.js              # HTTP REST API server on port 3847
│   ├── server-manager.js      # Paper + GeyserMC / Floodgate PS5 cross-play lifecycle engine
│   ├── autopilot.js           # Autonomous survival & gathering routines
│   ├── ares-responder.js      # Player chat parser & interaction logic
│   └── lib/                   # Perception & chat analysis libraries
├── tools/                     # ARES & Jaeger Agent Tool Bridge
│   ├── minecraft.py           # Native Python tool call functions for ARES & server management
│   └── mcp_minecraft.py       # MCP Server implementation (stdio)
└── prompts/                   # Embodied AI Personas
    └── ares_embodied.md       # ARES companion system prompt
```

---

## 🚀 Installation & Usage

### Option 1: Install as an ARES Extension (Recommended)

1. Open **ARES WebUI** $\rightarrow$ **Settings** $\rightarrow$ **Extensions Gallery**.
2. Click **Install** on **"ARES Minecraft Companion"** (or run CLI):
   ```bash
   ares extension install JenkinsRobotics/ares-minecraft
   ```
3. Enable the extension in ARES settings. The background sidecar starts automatically and adds the **Minecraft Tab** to your sidebar.

---

### Option 2: Standalone / Development Mode

1. **Install Bot Dependencies**:
   ```bash
   cd bot
   npm install
   ```

2. **Start the Bot Server**:
   ```bash
   MC_HOST="localhost" MC_PORT=25565 MC_USERNAME="ARES" npm start
   ```

3. **Environment Variables**:
   | Variable | Default | Description |
   | :--- | :--- | :--- |
   | `MC_HOST` | `localhost` | Minecraft server host or IP |
   | `MC_PORT` | `25565` | Minecraft server port |
   | `MC_USERNAME` | `ARES` | Bot username |
   | `MC_AUTH` | `offline` | Auth mode (`offline` or `microsoft`) |
   | `API_PORT` | `3847` | Sidecar REST API port |

4. **Launch the WebUI HUD**:
   Open [`dashboard/index.html`](dashboard/index.html) in any modern web browser or embed it in an iframe.

---

## 🛠️ Agent Tools Reference

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `mc_status()` | *None* | Returns health, hunger, coordinates, dimension, and players |
| `mc_move_to(x, y, z)` | `x, y, z` | Pathfinds to specific world coordinates |
| `mc_follow_player(player)` | `player` | Follows a specific player |
| `mc_mine(block_name, count)` | `block_name, count` | Locates and mines requested ores/blocks |
| `mc_craft(item_name, count)` | `item_name, count` | Crafts specified item recipe at a workbench |
| `mc_chat(message)` | `message` | Sends a message in public Minecraft chat |
| `mc_whisper(player, message)` | `player, message` | Sends a private whisper to a player |
| `mc_attack(target)` | `target` | Engages combat with a hostile mob or entity |
| `mc_inventory()` | *None* | Lists items and armor currently equipped/held |
| `mc_save_location(name)` | `name` | Saves current coordinates as a named waypoint |

---

## 🔌 Model Context Protocol (MCP) Integration

To use with Claude Desktop, Claude Code, or Cursor, add the MCP server configuration:

```json
{
  "mcpServers": {
    "ares-minecraft": {
      "command": "python3",
      "args": ["/path/to/ares-minecraft/tools/mcp_minecraft.py"]
    }
  }
}
```

---

## 📄 License

MIT © [Jenkins Robotics](https://github.com/Jenkins-Robotics)
