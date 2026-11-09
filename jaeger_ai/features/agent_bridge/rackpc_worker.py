"""Rack PC worker: turns hub handoffs to ``rackpc`` into bounded Ollama runs.

Runs on the rack PC (Windows, GTX 1080 Ti). It polls the Mac hub *as the
rackpc caller* (its own token; the Gateway confines that caller to reading its
messages and posting results) through a reverse SSH tunnel the Mac opens, so
the hub itself stays loopback-only. One job at a time, per-job timeout,
durable result outbox, idempotent delivery, size caps.

A task body may start with ``model: <name>`` to pick an Ollama model; the
body ``capabilities`` returns this machine's CPU/RAM/GPU/load/loaded models.

Run: python -m jaeger_ai.features.agent_bridge.rackpc_worker [--once]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
WORKDIR = Path(os.environ.get("RACKPC_WORKDIR", HOME / ".jaeger-rackpc"))
HUB_URL = os.environ.get("RACKPC_HUB_URL", "http://127.0.0.1:18792/mcp")
TOKEN_PATH = Path(os.environ.get("RACKPC_TOKEN_FILE", WORKDIR / "rackpc.token"))
OLLAMA_URL = os.environ.get("RACKPC_OLLAMA_URL", "http://100.78.245.49:11434")
DEFAULT_MODEL = os.environ.get("RACKPC_MODEL", "qwen3:8b")
TIMEOUT_S = int(os.environ.get("RACKPC_JOB_TIMEOUT_S", "600"))
POLL_S = int(os.environ.get("RACKPC_POLL_S", "15"))
ME = "rackpc"
MAX_TASK_BYTES = 16384
MAX_RESULT_CHARS = 12000
SYSTEM = ("You are the Jaeger rack PC worker, a local model on Matthew Jenkins's rack PC. "
          "Answer the handed-off task directly and concisely. You have no tools and cannot "
          "act on anything; if the task needs actions, say what would be needed.")


def _token() -> str:
    try:
        return TOKEN_PATH.read_text().strip()
    except OSError:
        raise SystemExit("rackpc caller token not found") from None


def _log(event: str, **data) -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **data}
    with open(WORKDIR / "worker.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
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
    async with streamablehttp_client(HUB_URL, headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            res = await session.call_tool(tool, args)
            text = "".join(getattr(c, "text", "") for c in res.content)
            if res.isError:
                raise RuntimeError(f"{tool} failed: {text[:500]}")
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}


def call(tool: str, args: dict) -> dict:
    return asyncio.run(_call(tool, args))


def _ollama(path: str, payload: dict | None = None, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed local URL
        return json.loads(resp.read())


def capabilities() -> dict:
    caps: dict = {"host": platform.node(), "os": platform.platform(), "cpu_count": os.cpu_count(),
                  "cpu": platform.processor()}
    try:
        import psutil
        vm = psutil.virtual_memory()
        caps.update(ram_gb=round(vm.total / 2**30, 1), ram_free_gb=round(vm.available / 2**30, 1),
                    cpu_load_pct=psutil.cpu_percent(interval=0.5))
    except Exception:  # noqa: BLE001 - optional probe
        pass
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        gpus = []
        for line in out.stdout.strip().splitlines():
            name, total, used, util = [x.strip() for x in line.split(",")]
            gpus.append({"name": name, "vram_mb": int(total), "vram_used_mb": int(used), "util_pct": int(util)})
        caps["gpus"] = gpus
    except Exception:  # noqa: BLE001
        caps["gpus"] = []
    try:
        caps["loaded_models"] = [m["name"] for m in _ollama("/api/ps").get("models", [])]
        caps["local_models"] = sorted(m["name"] for m in _ollama("/api/tags").get("models", [])
                                      if not m.get("remote_host"))
    except Exception as exc:  # noqa: BLE001
        caps["ollama_error"] = str(exc)[:200]
    return caps


def parse_task(body: str) -> tuple[str, str]:
    """``model: name`` on the first line picks the model; the rest is the prompt."""
    lines = body.strip().splitlines()
    if lines and lines[0].lower().startswith("model:"):
        model = lines[0].split(":", 1)[1].strip() or DEFAULT_MODEL
        return model, "\n".join(lines[1:]).strip()
    return DEFAULT_MODEL, body.strip()


def run_job(m: dict) -> dict:
    task = (m.get("body") or m.get("title") or "")[:MAX_TASK_BYTES]
    t0 = time.time()
    if task.strip().lower() == "capabilities":
        return {"status": "done", "outcome": "done", "body": json.dumps(capabilities(), indent=1), "elapsed_s": 0.0, "model": None}
    model, prompt = parse_task(task)
    try:
        d = _ollama("/api/chat", {"model": model, "stream": False, "think": False,
                                  "messages": [{"role": "system", "content": SYSTEM},
                                               {"role": "user", "content": prompt}]}, timeout=TIMEOUT_S)
        body = (d.get("message") or {}).get("content", "").strip()[:MAX_RESULT_CHARS]
        outcome = "done" if body else "failed"
        status = "done" if body else "failed (empty reply)"
        tps = round(d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-9), 1)
    except TimeoutError:
        body, status, tps = "", f"timed out after {TIMEOUT_S}s", 0
        outcome = "timeout"
    except Exception as exc:  # noqa: BLE001
        body, status, tps = "", f"error: {_error_text(exc)}", 0
        outcome = "error"
    elapsed = round(time.time() - t0, 1)
    body = (body or f"rackpc run {status}") + f"\n\n— rackpc · {model} · {tps} tok/s · {elapsed}s"
    return {"status": status, "outcome": outcome, "body": body, "elapsed_s": elapsed, "model": model}


def pending(state: State) -> list[dict]:
    tasks, after = [], state.data.get("after", 0)
    while True:
        page = call("receipts", {"after": after, "limit": 100})
        msgs = page.get("messages") or []
        for m in msgs:
            if (m.get("to") == ME and m.get("kind") == "task" and m.get("from") != ME
                    and m.get("id") not in state.data["done"]
                    and (m.get("created_at") or 0) >= state.data.get("since", 0)):
                tasks.append(m)
        nxt = page.get("next_after")
        if not msgs or nxt is None or nxt == after:
            break
        after = nxt
    state.data["after"] = after
    return tasks


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_error_text(child) for child in exc.exceptions)[:300]
    return str(exc)[:300]


def _outbox_path(task_id: str) -> Path:
    return WORKDIR / "outbox" / (hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".json")


def _queue(task_id: str, args: dict) -> None:
    path = _outbox_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"task_id": task_id, "args": args}), encoding="utf-8")
    tmp.replace(path)


def _flush_outbox() -> None:
    for path in sorted((WORKDIR / "outbox").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        try:
            call("send_message", item["args"])
        except Exception as exc:  # noqa: BLE001 - retry on the next tick
            _log("post_error", id=item["task_id"], error=_error_text(exc)[:500])
            continue
        path.unlink()
        _log("posted", id=item["task_id"])


def tick(state: State) -> int:
    _flush_outbox()
    n = 0
    for m in pending(state):
        _log("start", id=m["id"], thread=m.get("thread"), sender=m.get("from"))
        if _outbox_path(m["id"]).exists():
            continue
        try:
            out = run_job(m)
        except Exception as exc:  # noqa: BLE001
            detail = _error_text(exc)
            out = {"status": f"error: {detail}", "outcome": "error", "body": f"rackpc worker error: {detail}", "elapsed_s": 0}
        title = "Rack PC result" if out["status"] == "done" else f"Rack PC result: {out['status']}"
        task_id = m["id"]
        args = {"id": "rackpc-result-" + hashlib.sha256(task_id.encode("utf-8")).hexdigest(),
                "to": m["from"], "thread": m["thread"], "kind": "result", "title": title,
                "body": out["body"], "refs": [], "status_line": out.get("outcome", "execution_unknown"), "reply_to": task_id}
        _queue(task_id, args)
        state.data["done"].append(task_id)
        state.data["done"] = state.data["done"][-2000:]
        state.save()
        _flush_outbox()
        _log("finish", id=task_id, status=out["status"], elapsed_s=out["elapsed_s"])
        n += 1
    state.save()
    return n


def _lock(path: Path):
    fh = open(path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    WORKDIR.mkdir(parents=True, exist_ok=True)
    lock = _lock(WORKDIR / "worker.lock")
    if lock is None:
        print("another rackpc worker is running", file=sys.stderr)
        return 1
    state = State(WORKDIR / "state.json")
    (WORKDIR / "capabilities.json").write_text(json.dumps(capabilities(), indent=1))
    _log("worker_start", hub=HUB_URL, model=DEFAULT_MODEL, timeout_s=TIMEOUT_S)
    while True:
        try:
            tick(state)
        except Exception as exc:  # noqa: BLE001 - tunnel/hub restarts must not kill the worker
            _log("tick_error", error=_error_text(exc)[:500])
        if a.once:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
