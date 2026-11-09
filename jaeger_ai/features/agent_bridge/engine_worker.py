"""Headless Hermes/OpenClaw hub worker with a durable, idempotent result outbox."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ENGINES = ("hermes", "openclaw")
MAX_TASK = 16384
MAX_RESULT = 12000


def state_root() -> Path:
    return Path(os.environ.get("JAEGER_HOME", Path.home() / ".jaeger"))


def workspace(engine: str) -> Path:
    return Path(os.environ.get(f"{engine.upper()}_WORKSPACE", state_root() / "agent-workspaces" / engine))


def token(engine: str) -> str:
    path = state_root() / "caller_tokens" / f"{engine}.token"
    return path.read_text().strip()


async def _call(engine: str, tool: str, args: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    url = os.environ.get("JAEGER_HUB_URL", "http://127.0.0.1:8792/mcp")
    async with streamablehttp_client(url, headers={"Authorization": "Bearer " + token(engine)},
                                     timeout=20, sse_read_timeout=20) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            body = "".join(getattr(part, "text", "") for part in result.content)
            if result.isError:
                raise RuntimeError(f"{tool} failed: {body[:300]}")
            return json.loads(body)


def call(engine: str, tool: str, args: dict) -> dict:
    return asyncio.run(asyncio.wait_for(_call(engine, tool, args), timeout=25))


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    temp.replace(path)


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"after": 0, "since": time.time() - 3600, "done": []}


def device_ok() -> list[str]:
    from jaeger_ai.features.webui.api.resource_manager import ResourceManager
    return ResourceManager(state_root).check("light")


def pending(engine: str, state: dict) -> list[dict]:
    after = state["after"]
    tasks = []
    while True:
        page = call(engine, "receipts", {"after": after, "limit": 100})
        messages = page.get("messages") or []
        tasks.extend(m for m in messages if m.get("to") == engine and m.get("kind") == "task"
                     and m.get("from") != engine and m.get("id") not in state["done"]
                     and (m.get("created_at") or 0) >= state["since"])
        next_after = page.get("next_after")
        if not messages or next_after is None or next_after == after:
            break
        after = next_after
    state["after"] = after
    return tasks


def outbox_path(engine: str, task_id: str) -> Path:
    return workspace(engine) / ".worker" / "outbox" / (hashlib.sha256(task_id.encode()).hexdigest() + ".json")


def flush(engine: str) -> None:
    for path in sorted((workspace(engine) / ".worker" / "outbox").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        try:
            call(engine, "send_message", item)
        except Exception:
            continue  # Retain exact message id and payload for the next poll.
        path.unlink()


HOME = Path.home()


def engine_env(engine: str) -> dict:
    """Host-native engine env: Jaeger's Hermes profile / Jaeger's host OpenClaw state.

    Provider API keys are stripped; both engines use the Mac's local Ollama.
    """
    env = {key: val for key, val in os.environ.items() if not key.endswith("_API_KEY")}
    env["PATH"] = ":".join([str(HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin",
                            env.get("PATH", "/usr/bin:/bin")])
    if engine == "hermes":
        env["HERMES_HOME"] = os.environ.get("JAEGER_HERMES_HOME", str(HOME / ".jaeger" / "hermes"))
    else:
        state = os.environ.get("JAEGER_OPENCLAW_STATE", str(HOME / ".jaeger" / "openclaw-host"))
        env["OPENCLAW_STATE_DIR"] = state
        env["OPENCLAW_CONFIG_PATH"] = str(Path(state) / "openclaw.json")
        try:  # the host gateway's own token, so runs go through (and show in) its Control UI
            env["OPENCLAW_GATEWAY_TOKEN"] = (Path(state) / "gateway.token").read_text().strip()
        except OSError:
            pass
    return env


def openclaw_gateway_up(port: int | None = None) -> bool:
    import socket
    port = port or int(os.environ.get("JAEGER_OPENCLAW_UI_PORT", "18789"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def command(engine: str, prompt: str, jobdir: Path) -> list[str]:
    if engine == "hermes":
        return [os.environ.get("HERMES_BIN", str(HOME / ".local/bin/hermes")),
                "chat", "-Q", "--oneshot", "--query-file", str(jobdir / "prompt.md")]
    mode = [] if openclaw_gateway_up() else ["--local"]
    return [os.environ.get("OPENCLAW_BIN", "/opt/homebrew/bin/openclaw"), "agent", *mode,
            "--agent", "main", "--session-id", "jaeger-" + jobdir.name,
            "--message-file", str(jobdir / "prompt.md"), "--json"]


_NOISE = ("Preparing the isolated Hermes runtime", "Installing Python dependencies")


def final_text(engine: str, stdout: str) -> str:
    """The engine's final assistant answer, without launcher noise or metadata."""
    if engine == "openclaw":
        start = stdout.find("{")
        while start != -1:
            try:
                doc, _ = json.JSONDecoder().raw_decode(stdout[start:])
            except ValueError:
                start = stdout.find("{", start + 1)
                continue
            if isinstance(doc.get("result"), dict):  # gateway mode wraps the turn in "result"
                top_err = doc.get("error")
                doc = {**doc["result"], "error": top_err or doc["result"].get("error")}
            meta = doc.get("meta") or {}
            text = meta.get("finalAssistantVisibleText")
            if not text:
                text = "\n".join(p.get("text", "") for p in (doc.get("payloads") or []) if isinstance(p, dict))
            if not text and (doc.get("error") or meta.get("error")):
                err = doc.get("error") or meta.get("error")
                text = "OpenClaw error: " + str(err.get("message") if isinstance(err, dict) else err)[:400]
            return (text or "").strip()
        return ""
    lines = [ln for ln in stdout.splitlines()
             if not any(n in ln for n in _NOISE) and not ln.startswith("session_id:")
             and not ln.strip().startswith(("\u2192", "\u2713"))]
    return "\n".join(lines).strip()


def run_job(engine: str, message: dict) -> dict:
    job = "".join(c if c.isalnum() or c in "-_" else "_" for c in message["id"])[:80]
    jobdir = workspace(engine) / "jobs" / job
    jobdir.mkdir(parents=True, exist_ok=True)
    prompt = ("You are a Jaeger worker. Work only on this Mac. Read as needed; write only "
              f"inside {jobdir}. Do not send messages or publish anything. Never read secrets. "
              "Finish with a concise answer and ARTIFACT: absolute paths for files written.\n\n"
              + (message.get("body") or message.get("title") or "")[:MAX_TASK])
    (jobdir / "prompt.md").write_text(prompt, encoding="utf-8")
    timeout = int(os.environ.get(f"{engine.upper()}_JOB_TIMEOUT_S", "900"))
    started = time.time()
    env = engine_env(engine)
    try:
        proc = subprocess.run(command(engine, prompt, jobdir), cwd=jobdir, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        body = final_text(engine, proc.stdout)[-MAX_RESULT:]
        outcome = "done" if proc.returncode == 0 and body else "failed"
        status = "done" if outcome == "done" else f"failed (exit {proc.returncode})"
    except subprocess.TimeoutExpired:
        body, status = "", f"timed out after {timeout}s"
        outcome = "timeout"
    body = body or f"{engine} run {status}; no final message."
    (jobdir / "result.md").write_text(body, encoding="utf-8")
    refs = [str(jobdir / "result.md")]
    for line in body.splitlines():
        if line.startswith("ARTIFACT:"):
            candidate = Path(line.partition(":")[2].strip())
            if candidate.is_relative_to(jobdir):
                refs.append(str(candidate))
    return {"status": status, "outcome": outcome, "body": body, "refs": refs[:20], "elapsed_s": round(time.time() - started, 1)}


def tick(engine: str, state: dict, state_path: Path) -> int:
    flush(engine)
    count = 0
    for message in pending(engine, state):
        if device_ok():
            break
        task_id = message["id"]
        if outbox_path(engine, task_id).exists():
            continue
        try:
            result = run_job(engine, message)
        except Exception as exc:
            result = {"status": "error", "outcome": "error", "body": f"{engine} worker error: {type(exc).__name__}: {str(exc)[:200]}", "refs": []}
        args = {"id": f"{engine}-result-" + hashlib.sha256(task_id.encode()).hexdigest(),
                "to": message["from"], "thread": message["thread"], "kind": "result",
                "title": f"{engine.title()} result: {result['status']}", "body": result["body"],
                "refs": result["refs"], "status_line": result.get("outcome", "execution_unknown"), "reply_to": task_id}
        atomic_json(outbox_path(engine, task_id), args)
        state["done"] = (state["done"] + [task_id])[-2000:]
        atomic_json(state_path, state)
        flush(engine)
        count += 1
    atomic_json(state_path, state)
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=ENGINES)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    worker_dir = workspace(args.engine) / ".worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    with open(worker_dir / "worker.lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another worker is running", file=sys.stderr)
            return 1
        state_path = worker_dir / "state.json"
        state = load_state(state_path)
        while True:
            try:
                tick(args.engine, state, state_path)
            except Exception as exc:
                print(f"{args.engine} worker tick error: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
            if args.once:
                return 0
            time.sleep(int(os.environ.get(f"{args.engine.upper()}_POLL_S", "15")))


if __name__ == "__main__":
    raise SystemExit(main())
