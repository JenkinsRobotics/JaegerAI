"""Own the browser child processes; clients never launch a second browser."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets

from aiohttp import ClientSession, ClientTimeout
from jaeger_ai.core.instance.instance import operator_state_root


class BrowserUnavailable(RuntimeError):
    pass


class BrowserWorker:
    def __init__(self, process, port, token, log):
        self.process, self.port, self.token, self.log = process, port, token, log

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.token}

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    async def close(self):
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 12)
            except asyncio.TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 5)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        self.log.close()


class BrowserRuntime:
    def __init__(self, bundle: Path | None = None, state: Path | None = None):
        self.state = state or operator_state_root() / "browser"
        self.bundle = bundle or Path(os.environ.get("JAEGER_BROWSER_BUNDLE", str(operator_state_root() / "runtimes/browser")))
        self.workers = {}
        self.lock = asyncio.Lock()

    async def worker(self, session_id: str):
        async with self.lock:
            worker = self.workers.get(session_id)
            if worker and worker.process.returncode is None:
                return worker
            if worker:
                await worker.close()
                del self.workers[session_id]
            if len(self.workers) >= 4:
                raise BrowserUnavailable("Four browser workspaces are open. Close one before opening another.")
            manifest_file = self.bundle / "manifest.json"
            if not manifest_file.is_file():
                raise BrowserUnavailable("The bundled browser runtime is missing. Repair the Jaeger installation.")
            manifest = json.loads(manifest_file.read_text())
            node, chrome = self.bundle / manifest["node"], self.bundle / manifest["chrome"]
            if not node.is_file() or not chrome.is_file():
                raise BrowserUnavailable("The browser runtime is incomplete. Repair the Jaeger installation.")
            home = self.state / hashlib.sha256(session_id.encode()).hexdigest()
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
            token = secrets.token_urlsafe(32)
            # Do not leak provider credentials into the third-party browser process.
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"}}
            env.update(HOST="127.0.0.1", PORT="0", CDP_REDIRECT_PORT="0", NODE_ENV="production",
                       CHROME_EXECUTABLE_PATH=str(chrome), CHROME_USER_DATA_DIR=str(home / "profile"),
                       JAEGER_BROWSER_FILES=str(home / "downloads"), JAEGER_BROWSER_ARCHIVES=str(home / "archives"),
                       CHROME_HEADLESS="true", SKIP_FINGERPRINT_INJECTION="true",
                       FILTER_CHROME_ARGS="--remote-debugging-port=9222", CHROME_ARGS="--remote-debugging-port=0",
                       JAEGER_BROWSER_TOKEN=token)
            log = (home / "worker.log").open("ab")
            process = await asyncio.create_subprocess_exec(str(node), str(self.bundle / "worker.mjs"),
                cwd=home, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log)
            worker = BrowserWorker(process, 0, token, log)
            try:
                async with asyncio.timeout(60):
                    while True:
                        line = await process.stdout.readline()
                        if not line:
                            raise BrowserUnavailable("The browser could not start. See its worker log in Jaeger state.")
                        log.write(line); log.flush()
                        try:
                            ready = json.loads(line)
                        except ValueError:
                            continue
                        if ready.get("jaeger_browser_ready"):
                            worker.port = int(ready["port"])
                            break
                    async with ClientSession(timeout=ClientTimeout(total=3)) as client:
                        while True:
                            async with client.get(worker.base + "/jaeger/ready", headers=worker.headers) as response:
                                if response.status == 200:
                                    break
                            await asyncio.sleep(.2)
            except BaseException:
                await worker.close()
                raise
            # Drain upstream console output so a long-lived process cannot block on its pipe.
            worker.drain = asyncio.create_task(self._drain(process.stdout, log))
            self.workers[session_id] = worker
            return worker

    async def _drain(self, stream, log):
        while line := await stream.readline():
            if not log.closed:
                log.write(line)

    async def close_session(self, session_id):
        async with self.lock:
            worker = self.workers.pop(session_id, None)
            if worker:
                await worker.close()

    async def close(self):
        for session_id in list(self.workers):
            await self.close_session(session_id)
