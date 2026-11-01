"""ARES worker: turns hub handoffs to ``ares`` into bounded ``codex exec`` runs.

ARES is Matthew's agent in OpenAI Codex. Handoffs to it are inbox ``task``
messages that nothing used to act on unless a Codex session happened to be
open. This worker polls the hub *as the ares caller* (its own token, so the
identity, workspace grants and activity rows stay ``ares``), runs one task at a
time with ``codex exec`` in ARES's workspace using Codex's own ChatGPT login
(no API keys), and posts the result plus artifact paths back on the thread
with ``post_result``.

Bounds: one job at a time (file lock), per-job timeout, device-resource gate
(<state>/resources.json via ResourceManager.check, "light" class), prompt and
output size caps, and a durable done-set so a task never runs twice.

Run: python -m jaeger_ai.features.agent_bridge.ares_worker [--once]
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE_ROOT = Path(os.environ.get("JAEGER_HOME", HOME / ".jaeger"))
WORKSPACE = Path(os.environ.get("ARES_WORKSPACE", STATE_ROOT / "agent-workspaces" / "ares"))
WORKER_DIR = WORKSPACE / ".worker"
HUB_URL = os.environ.get("ARES_HUB_URL", "http://127.0.0.1:8792/mcp")
TOKEN_PATHS = [STATE_ROOT / "caller_tokens" / "ares.token", STATE_ROOT / "secrets" / "mcp-ares.token"]
CODEX = os.environ.get("ARES_CODEX_BIN", "/opt/homebrew/bin/codex")
#: Both Jaeger hub entries in Codex's config; a run may pick either one.
HUB_MCP = tuple(n for n in os.environ.get("ARES_HUB_MCP_NAMES", "jaeger-ares,jaeger-local").split(",") if n)
#: Report-only hub tools: posting a result back is a report, not an action, so a headless
#: run (approval policy "never") may call them without an owner card. Everything else
#: (send_message, handoff_task, goals, app/backlog writes...) stays on Codex's default gate.
REPORT_TOOLS = ("post_result",)


def report_overrides() -> list[str]:
    out = []
    for server in HUB_MCP:
        for tool in REPORT_TOOLS:
            out += ["-c", f'mcp_servers.{server}.tools.{tool}.approval_mode="approve"']
    return out
# The Codex config default may be a model the ChatGPT login can't use in exec.
MODEL = os.environ.get("ARES_CODEX_MODEL", "gpt-6-sol")
TIMEOUT_S = int(os.environ.get("ARES_JOB_TIMEOUT_S", "900"))
POLL_S = int(os.environ.get("ARES_POLL_S", "15"))
# Every hub call is bounded so a hub that is down, half-up or restarting can
# never wedge the loop; failures retry with capped exponential backoff.
HUB_TIMEOUT_S = float(os.environ.get("ARES_HUB_TIMEOUT_S", "20"))
HUB_RETRIES = int(os.environ.get("ARES_HUB_RETRIES", "3"))
BACKOFF_MAX_S = float(os.environ.get("ARES_BACKOFF_MAX_S", "300"))
# Single switch for the busy-Mac hold: "1" (default) waits while resources.json
# limits say the device is busy; "0" exempts ARES (Codex runs in OpenAI's cloud).
RESOURCE_GATE = os.environ.get("ARES_RESOURCE_GATE", "1") != "0"
MAX_TASK_BYTES = 16384
MAX_RESULT_CHARS = 12000

INSTRUCTIONS = """You are ARES, Matthew Jenkins's agent running in OpenAI Codex, working as a
Jaeger worker. A teammate handed you the task below through Jaeger's local hub.
Rules:
- Work only on this Mac. Do not send anything off the machine, post anywhere,
  push git, or open PRs.
- Read files anywhere you need, but write only inside your workspace
  ({ws}/jobs/{job}/ unless the task names another path in your workspace).
- Never read or print secrets, tokens, keys or ~/.jaeger/secrets.
- Do not edit launchd plists, Codex/VS Code config, or other bots' worktrees.
- If the task needs something risky or outside these rules, stop and explain.
- Finish with a short plain-language summary of what you did and list any
  files you wrote, one per line, prefixed with ARTIFACT: and an absolute path.
Task from {sender} (thread {thread}, id {id}):
---
{task}
---"""


def _token() -> str:
    for path in TOKEN_PATHS:
        if path.exists():
            return path.read_text().strip()
    raise SystemExit("ares caller token not found")


def _log(event: str, **data) -> None:
    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **data}
    with open(WORKER_DIR / "worker.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            # First start: only tasks from the last hour count, not old history.
            self.data = {"after": 0, "done": [], "since": time.time() - 3600}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


async def _call(tool: str, args: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": "Bearer " + _token()}
    async with streamablehttp_client(HUB_URL, headers=headers, timeout=HUB_TIMEOUT_S,
                                     sse_read_timeout=HUB_TIMEOUT_S) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            res = await session.call_tool(tool, args)
            text = "".join(getattr(c, "text", "") for c in res.content)
            if res.isError:
                raise HubToolError(f"{tool} failed: {text[:500]}")
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}


class HubToolError(RuntimeError):
    """The hub answered but the tool failed; retrying will not help."""


def _backoff(attempt: int, base: float = 1.0) -> float:
    return min(BACKOFF_MAX_S, base * (2 ** attempt))


def call(tool: str, args: dict, retries: int | None = None) -> dict:
    """One hub tool call, hard-bounded by HUB_TIMEOUT_S, retried on transport errors."""
    retries = HUB_RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        try:
            return asyncio.run(asyncio.wait_for(_call(tool, args), HUB_TIMEOUT_S))
        except HubToolError:
            raise
        except BaseException as exc:  # noqa: BLE001 - incl. TimeoutError, ExceptionGroup
            if isinstance(exc, (KeyboardInterrupt, SystemExit)) or attempt >= retries:
                raise RuntimeError(f"hub unreachable ({tool}): {type(exc).__name__}: {str(exc)[:200]}") from None
            _log("hub_retry", tool=tool, attempt=attempt + 1, error=type(exc).__name__)
            time.sleep(_backoff(attempt))
    raise AssertionError("unreachable")


def device_ok() -> list[str]:
    if not RESOURCE_GATE:
        return []
    try:
        from jaeger_ai.features.webui.api.resource_manager import ResourceManager
        return ResourceManager(lambda: STATE_ROOT).check("light")
    except Exception as exc:  # noqa: BLE001 - a broken probe must not block forever
        _log("resource_probe_error", error=str(exc))
        return []


def pending(state: State) -> list[dict]:
    tasks, after = [], state.data.get("after", 0)
    while True:
        page = call("receipts", {"after": after, "limit": 100})
        msgs = page.get("messages") or []
        for m in msgs:
            if (m.get("to") == "ares" and m.get("kind") == "task" and m.get("from") != "ares"
                    and m.get("id") not in state.data["done"]
                    and (m.get("created_at") or 0) >= state.data.get("since", 0)):
                tasks.append(m)
        nxt = page.get("next_after")
        if not msgs or nxt is None or nxt == after:
            break
        after = nxt
    state.data["after"] = after
    return tasks


def run_job(m: dict) -> dict:
    job = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in m["id"])[:80]
    jobdir = WORKSPACE / "jobs" / job
    jobdir.mkdir(parents=True, exist_ok=True)
    task = (m.get("body") or m.get("title") or "")[:MAX_TASK_BYTES]
    prompt = INSTRUCTIONS.format(ws=WORKSPACE, job=job, sender=m.get("from"), thread=m.get("thread"),
                                 id=m.get("id"), task=task)
    (jobdir / "task.json").write_text(json.dumps(m, indent=1))
    last = jobdir / "result.md"
    cmd = [CODEX, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
           *report_overrides(), "-C", str(WORKSPACE), "-m", MODEL, "-o", str(last), prompt]
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    t0 = time.time()
    status = "done"
    try:
        with open(jobdir / "codex.log", "w") as logf:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                  env=env, timeout=TIMEOUT_S, cwd=WORKSPACE)
        if proc.returncode != 0:
            status = f"failed (exit {proc.returncode})"
    except subprocess.TimeoutExpired:
        status = f"timed out after {TIMEOUT_S}s"
    body = last.read_text()[:MAX_RESULT_CHARS] if last.exists() else ""
    if not body:
        body = f"ARES run {status}; no final message. See {jobdir / 'codex.log'}."
    artifacts = [str(last), str(jobdir / "codex.log")]
    for line in body.splitlines():
        if line.strip().startswith("ARTIFACT:"):
            artifacts.append(line.split(":", 1)[1].strip())
    return {"status": status, "body": body, "artifacts": artifacts[:20], "elapsed_s": round(time.time() - t0, 1)}


def tick(state: State) -> int:
    n = 0
    for m in pending(state):
        why = device_ok()
        if why:
            _log("deferred", id=m["id"], reason="; ".join(why))
            break
        _log("start", id=m["id"], thread=m.get("thread"), sender=m.get("from"))
        # Mark first so a crash mid-run never re-runs a task (at-most-once).
        state.data["done"].append(m["id"]); state.data["done"] = state.data["done"][-2000:]; state.save()
        try:
            out = run_job(m)
        except Exception as exc:  # noqa: BLE001
            out = {"status": f"error: {exc}", "body": f"ARES worker error: {exc}", "artifacts": [], "elapsed_s": 0}
        title = "ARES result" if out["status"] == "done" else f"ARES result: {out['status']}"
        call("post_result", {"to": m["from"], "thread": m["thread"], "title": title, "body": out["body"],
                              "artifacts": out["artifacts"], "reply_to": m["id"]})
        _log("finish", id=m["id"], status=out["status"], elapsed_s=out["elapsed_s"])
        n += 1
    state.save()
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(WORKER_DIR / "worker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another ARES worker is running", file=sys.stderr)
        return 1
    state = State(WORKER_DIR / "state.json")
    _log("worker_start", workspace=str(WORKSPACE), timeout_s=TIMEOUT_S)
    fails = 0
    while True:
        try:
            tick(state)
            if fails:
                _log("hub_recovered", after_failures=fails)
            fails = 0
        except Exception as exc:  # noqa: BLE001 - hub restarts must not kill the worker
            fails += 1
            _log("tick_error", error=str(exc)[:500], failures=fails)
        if a.once:
            return 0
        time.sleep(next_sleep(fails))


def next_sleep(fails: int) -> float:
    """Poll interval, backing off (capped) while the hub keeps failing."""
    return POLL_S if fails == 0 else max(POLL_S, _backoff(fails - 1, POLL_S))


if __name__ == "__main__":
    raise SystemExit(main())
