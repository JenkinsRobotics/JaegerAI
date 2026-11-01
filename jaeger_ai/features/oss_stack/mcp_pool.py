"""Official MCP servers run as stdio children of the Gateway and shared with callers.

Each server lives in one asyncio task (stdio/anyio scopes must open and close in
the same task); calls are queued to it. Idle servers stop after IDLE_S to save
RAM (Playwright especially). Tools are allowlisted per server: the Documents
filesystem view is read-only, writes are only possible under Jaeger-Handoffs,
git is read-only on one repo. Fetch is NOT here: callers use jaeger.fetch,
which carries the SSRF guard.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .browser_proxy import start_proxy

logger = logging.getLogger(__name__)
HOME = Path.home()
OSS = Path(os.environ.get("JAEGER_OSS_DIR", HOME / ".jaeger" / "oss"))
NODE_BIN = OSS / "mcp-node" / "node_modules" / ".bin"
UV_BIN = HOME / ".local" / "bin"
IDLE_S = float(os.environ.get("JAEGER_MCP_IDLE_S", "600"))
CALL_TIMEOUT = float(os.environ.get("JAEGER_MCP_CALL_TIMEOUT_S", "120"))
MAX_RESULT_CHARS = 60_000

FS_READ = frozenset({"read_file", "read_text_file", "read_media_file", "read_multiple_files", "list_directory",
                     "list_directory_with_sizes", "directory_tree", "search_files", "get_file_info",
                     "list_allowed_directories"})
FS_WRITE = FS_READ | {"write_file", "edit_file", "create_directory", "move_file"}
GIT_READ = frozenset({"git_status", "git_diff_unstaged", "git_diff_staged", "git_diff", "git_log", "git_show",
                      "git_branch"})


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list[str]
    allow: frozenset | None = None  # None = every tool the server lists
    env: dict = field(default_factory=dict)
    description: str = ""


LOCAL_PORTS = (5678, 6333, 6334, 8090, 8790, 8791, 8792, 8793, 8796, 8811, 8888, 11434, 11435, 18792, 33418, 62518)
BLOCKED_ORIGINS = ";".join(f"{s}://{h}:{p}" for s in ("http", "https") for h in ("127.0.0.1", "localhost")
                           for p in LOCAL_PORTS)


def default_specs() -> dict[str, ServerSpec]:
    docs = str(HOME / "Documents")
    handoffs = str(HOME / "Documents" / "Jaeger-Handoffs")
    repo = os.environ.get("JAEGER_MCP_GIT_REPO", str(HOME / "GitHub" / "JaegerAI-unified-ui"))
    pw_profile = str(OSS / "playwright-profile")
    specs = [
        ServerSpec("docs", str(NODE_BIN / "mcp-server-filesystem"), [docs], FS_READ,
                   description="Read-only view of ~/Documents"),
        ServerSpec("handoffs", str(NODE_BIN / "mcp-server-filesystem"), [handoffs], FS_WRITE,
                   description="Read/write ~/Documents/Jaeger-Handoffs (no delete)"),
        ServerSpec("git", str(UV_BIN / "mcp-server-git"), ["--repository", repo], GIT_READ,
                   description=f"Read-only git on {Path(repo).name}"),
        ServerSpec("memory", str(NODE_BIN / "mcp-server-memory"), [], None,
                   env={"MEMORY_FILE_PATH": str(OSS / "memory.jsonl")},
                   description="Shared knowledge-graph memory (~/.jaeger/oss/memory.jsonl)"),
        ServerSpec("time", str(UV_BIN / "mcp-server-time"), ["--local-timezone", "America/Los_Angeles"], None,
                   description="Current time and timezone conversion"),
        ServerSpec("browser", str(NODE_BIN / "playwright-mcp"),
                   ["--headless", "--browser", "chromium", "--user-data-dir", pw_profile,
                    "--block-service-workers", "--blocked-origins", BLOCKED_ORIGINS,
                    "--proxy-server", "http://127.0.0.1:0", "--proxy-bypass", "<-loopback>", "--output-dir", str(OSS / "playwright-out")], None,
                   description="Shared headless Chromium (own profile, no network listener)"),
    ]
    return {s.name: s for s in specs}


class ToolError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _Server:
    def __init__(self, spec: ServerSpec):
        self.spec = spec
        self.queue: asyncio.Queue | None = None
        self.task: asyncio.Task | None = None
        self.tools: list[dict] = []
        self.ready: asyncio.Future | None = None

    async def _main(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin") + ":/opt/homebrew/bin", "HOME": str(HOME),
               **self.spec.env}
        proxy = None
        args = list(self.spec.args)
        try:
            if self.spec.name == "browser":
                proxy = await start_proxy()
                port = proxy.sockets[0].getsockname()[1]
                args[args.index("--proxy-server") + 1] = f"http://127.0.0.1:{port}"
            params = StdioServerParameters(command=self.spec.command, args=args, env=env,
                                           cwd=str(OSS))
            async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
                await session.initialize()
                listed = await session.list_tools()
                self.tools = [{"name": t.name, "description": (t.description or "")[:500],
                               "input_schema": t.inputSchema} for t in listed.tools
                              if self.spec.allow is None or t.name in self.spec.allow]
                self.ready.set_result(True)
                while True:
                    try:
                        name, args, fut = await asyncio.wait_for(self.queue.get(), IDLE_S)
                    except asyncio.TimeoutError:
                        return
                    if fut.cancelled():
                        continue
                    try:
                        res = await asyncio.wait_for(session.call_tool(name, args), CALL_TIMEOUT)
                        fut.set_result(res)
                    except Exception as exc:  # noqa: BLE001 - surface to caller
                        if not fut.done():
                            fut.set_exception(exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp server %s stopped: %s", self.spec.name, exc)
            if self.ready and not self.ready.done():
                self.ready.set_exception(exc)
        finally:
            if proxy:
                proxy.close()
                await proxy.wait_closed()
            self.task = None

    async def ensure(self):
        if self.task is None or self.task.done():
            loop = asyncio.get_running_loop()
            self.queue, self.ready = asyncio.Queue(), loop.create_future()
            self.task = loop.create_task(self._main(), name=f"mcp-{self.spec.name}")
        await asyncio.wait_for(asyncio.shield(self.ready), 90)

    async def call(self, name: str, args: dict):
        await self.ensure()
        fut = asyncio.get_running_loop().create_future()
        await self.queue.put((name, args, fut))
        return await asyncio.wait_for(fut, CALL_TIMEOUT + 5)


def _content_to_json(res) -> dict:
    parts, total = [], 0
    for c in getattr(res, "content", []) or []:
        d = c.model_dump() if hasattr(c, "model_dump") else dict(c)
        if d.get("type") == "text":
            txt = d.get("text", "")[: max(0, MAX_RESULT_CHARS - total)]
            total += len(txt)
            parts.append({"type": "text", "text": txt})
        elif d.get("type") == "image":
            parts.append({"type": "image", "mimeType": d.get("mimeType"), "bytes": len(d.get("data") or "")})
        else:
            parts.append({"type": d.get("type")})
    return {"is_error": bool(getattr(res, "isError", False)), "content": parts}


class McpPool:
    def __init__(self, specs: dict[str, ServerSpec] | None = None):
        self.specs = specs or default_specs()
        self.servers = {n: _Server(s) for n, s in self.specs.items()}

    async def list(self) -> dict:
        out = {}
        for name, srv in self.servers.items():
            try:
                await srv.ensure()
                out[name] = {"description": srv.spec.description, "tools": srv.tools}
            except Exception as exc:  # noqa: BLE001
                out[name] = {"description": srv.spec.description, "error": str(exc)[:300], "tools": []}
        return out

    async def call(self, server: str, tool: str, args: dict | None) -> dict:
        srv = self.servers.get(server)
        if srv is None:
            raise ToolError(f"Unknown tool server {server!r}", 404)
        spec = srv.spec
        if spec.allow is not None and tool not in spec.allow:
            raise ToolError(f"Tool {tool!r} is not allowed on {server}", 403)
        if not isinstance(args, dict):
            raise ToolError("args must be an object")
        res = await srv.call(tool, args)
        return _content_to_json(res)

    async def close(self):
        for srv in self.servers.values():
            if srv.task:
                srv.task.cancel()
                with contextlib.suppress(BaseException):
                    await srv.task
