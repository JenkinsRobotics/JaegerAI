"""Model Context Protocol (MCP) Server for ARES Minecraft Companion.

Exposes Minecraft embodiment tools as an MCP standard server over stdio.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from tools.minecraft import (
    mc_attack,
    mc_chat,
    mc_craft,
    mc_follow_player,
    mc_get_locations,
    mc_inventory,
    mc_mine,
    mc_move_to,
    mc_save_location,
    mc_server_command,
    mc_server_config,
    mc_server_logs,
    mc_server_restart,
    mc_server_start,
    mc_server_status,
    mc_server_stop,
    mc_status,
    mc_whisper,
)

MCP_TOOLS = [
    {
        "name": "mc_status",
        "description": "Get current Minecraft bot status, health, hunger, coordinates, and nearby players.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mc_server_status",
        "description": "Get Minecraft server lifecycle, rack-PC host, online/offline status, RAM, CPU, players, and iOS/PS5 join instructions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mc_server_start",
        "description": "Start the Paper + GeyserMC + Floodgate cross-play Minecraft server.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory": {"type": "string", "description": "RAM allocation (e.g. 4G)", "default": "4G"},
                "difficulty": {"type": "string", "description": "Difficulty (peaceful/easy/normal/hard)", "default": "normal"},
                "gamemode": {"type": "string", "description": "Gamemode (survival/creative)", "default": "survival"},
            },
        },
    },
    {
        "name": "mc_server_stop",
        "description": "Stop the Minecraft server cleanly.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mc_server_restart",
        "description": "Restart the Minecraft server.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mc_server_command",
        "description": "Send an administrative RCON console command to the server (e.g. 'op Shu_Walker', 'time set day').",
        "inputSchema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Command string"}},
            "required": ["command"],
        },
    },
    {
        "name": "mc_chat",
        "description": "Send a public chat message to the Minecraft server.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Message to send"}},
            "required": ["message"],
        },
    },
    {
        "name": "mc_whisper",
        "description": "Send a private direct whisper to a specific Minecraft player.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "player": {"type": "string", "description": "Target player username"},
                "message": {"type": "string", "description": "Private message text"},
            },
            "required": ["player", "message"],
        },
    },
    {
        "name": "mc_move_to",
        "description": "Pathfind and navigate the bot to (X, Y, Z) coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate"},
                "y": {"type": "number", "description": "Y coordinate"},
                "z": {"type": "number", "description": "Z coordinate"},
            },
            "required": ["x", "y", "z"],
        },
    },
    {
        "name": "mc_follow_player",
        "description": "Follow a specific player in the Minecraft world.",
        "inputSchema": {
            "type": "object",
            "properties": {"player": {"type": "string", "description": "Player username to follow"}},
            "required": ["player"],
        },
    },
    {
        "name": "mc_mine",
        "description": "Locate and mine nearby blocks or ore blocks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "block_name": {"type": "string", "description": "Name of block (e.g. iron_ore, oak_log, stone)"},
                "count": {"type": "integer", "description": "Number of blocks to mine", "default": 1},
            },
            "required": ["block_name"],
        },
    },
    {
        "name": "mc_inventory",
        "description": "View items, weapons, and armor in bot inventory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool_map = {
        "mc_status": lambda args: mc_status(),
        "mc_server_status": lambda args: mc_server_status(),
        "mc_server_start": lambda args: mc_server_start(args.get("memory", "4G"), args.get("difficulty", "normal"), args.get("gamemode", "survival")),
        "mc_server_stop": lambda args: mc_server_stop(),
        "mc_server_restart": lambda args: mc_server_restart(),
        "mc_server_command": lambda args: mc_server_command(args.get("command", "")),
        "mc_chat": lambda args: mc_chat(args.get("message", "")),
        "mc_whisper": lambda args: mc_whisper(args.get("player", ""), args.get("message", "")),
        "mc_move_to": lambda args: mc_move_to(args.get("x", 0), args.get("y", 64), args.get("z", 0)),
        "mc_follow_player": lambda args: mc_follow_player(args.get("player", "")),
        "mc_mine": lambda args: mc_mine(args.get("block_name", "stone"), args.get("count", 1)),
        "mc_inventory": lambda args: mc_inventory(),
    }
    handler = tool_map.get(name)
    if not handler:
        return {"error": f"Unknown tool {name}"}
    return handler(arguments)


def run_mcp_stdio_server():
    """Simple JSON-RPC 2.0 stdio server for MCP."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            
            if method == "tools/list":
                res = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
            elif method == "tools/call":
                params = req.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                tool_result = handle_tool_call(name, args)
                res = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(tool_result)}]}}
            else:
                res = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            err_res = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(exc)}}
            sys.stdout.write(json.dumps(err_res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_mcp_stdio_server()
