"""WebUI-owned endpoints for the unified UI (Jenkins Robotics, 2026-10-30).

Minimal, local-only backends the gateway doesn't provide:
  Studio    GET  /v1/studio/providers            image providers + whether each is usable
            POST /v1/studio/generate             {provider, prompt, seed?} -> asset (real output only)
            GET  /v1/studio/assets               library; POST {name, mime, data_base64, tags?} imports
            GET  /v1/studio/assets/<id>/file     the bytes
            PUT  /v1/studio/assets/<id>          {tags?, name?};  DELETE removes it
            GET/PUT /v1/studio/board             arrangement of assets + notes
  Models    GET  /v1/models/local                Ollama models (size, family, quant, loaded)
            GET  /v1/models/hardware             chip, RAM, GPU cores; fit = size vs RAM
            POST /v1/models/pull {name}          background `ollama pull`; GET /v1/models/pulls
            DELETE /v1/models/local/<name>       `ollama rm` equivalent (UI confirms first)
  Compare   POST /v1/compare/run {model, prompt} one non-streamed Ollama completion with timing
            POST /v1/compare/stream {model, prompt}  NDJSON: start, thinking/delta…, done{metrics} | error
            GET/POST /v1/compare/history; PUT {winner} / DELETE /v1/compare/history/<id>
  Pipeline  GET /v1/pipeline; PUT /v1/pipeline/<task_id> {stage, expected_revision?};
            POST /v1/pipeline/<task_id>/attachments {kind, ref?, label?, text?}; DELETE …/attachments/<id>
  YouTube   GET /v1/research/youtube[/tools|/<task>|/<task>/style-guide|/<task>/drafts]; POST /v1/research/youtube
            {playlist_url, task_id?, model?, max_videos?}; POST /<task>/run {force?}|/cancel|/style-guide|/draft {topic}
  Documents GET/POST /v1/documents, GET/PUT/DELETE /v1/documents/<id>; POST /v1/documents/ai-edit
Everything is stored under <state>/studio or <state>/documents (default ~/.jaeger). Ollama is
reached on 127.0.0.1:11434 only. Nothing is fabricated: unavailable providers return 409 with a
setup note.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote

OLLAMA = "http://127.0.0.1:11434"
MAX_ASSET = 14 * 1024 * 1024  # base64 must fit read_body's 20 MB cap
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
_ID = re.compile(r"^[a-z0-9-]{6,64}$")
_lock = threading.Lock()


def state_root() -> Path:
    return Path(os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")


def _studio() -> Path:
    p = state_root() / "studio"
    (p / "assets").mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), "utf-8")
    os.replace(tmp, path)


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.payload = status, {"error": message, **extra}


# ── Studio: assets ───────────────────────────────────────────────────

def list_assets() -> list[dict]:
    return sorted(_read_json(_studio() / "assets.json", []), key=lambda a: -a.get("created_at", 0))


def _save_assets(items: list[dict]) -> None:
    _write_json(_studio() / "assets.json", items)


def add_asset(data: bytes, mime: str, name: str, source: str, tags=None, prompt: str | None = None, provider: str | None = None) -> dict:
    if mime not in MIME_EXT:
        raise ApiError(400, f"unsupported type {mime}")
    if not data or len(data) > MAX_ASSET:
        raise ApiError(400, "asset must be 1 byte to 14 MB")
    aid = uuid.uuid4().hex[:16]
    fname = aid + MIME_EXT[mime]
    (_studio() / "assets" / fname).write_bytes(data)
    item = {"id": aid, "file": fname, "name": (name or fname)[:120], "mime": mime, "size": len(data), "created_at": time.time(),
            "source": source, "tags": clean_tags(tags), "prompt": prompt, "provider": provider}
    with _lock:
        items = list_assets()
        items.append(item)
        _save_assets(items)
    return item


def clean_tags(tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    out = []
    for t in tags:
        if isinstance(t, str) and t.strip():
            out.append(t.strip()[:32])
    return sorted(set(out))[:20]


def get_asset(aid: str) -> dict:
    if not _ID.match(aid):
        raise ApiError(404, "no such asset")
    for a in list_assets():
        if a["id"] == aid:
            return a
    raise ApiError(404, "no such asset")


def update_asset(aid: str, body: dict) -> dict:
    with _lock:
        items = list_assets()
        for a in items:
            if a["id"] == aid:
                if "tags" in body:
                    a["tags"] = clean_tags(body["tags"])
                if isinstance(body.get("name"), str) and body["name"].strip():
                    a["name"] = body["name"].strip()[:120]
                _save_assets(items)
                return a
    raise ApiError(404, "no such asset")


def delete_asset(aid: str) -> dict:
    a = get_asset(aid)
    with _lock:
        _save_assets([x for x in list_assets() if x["id"] != aid])
    try:
        (_studio() / "assets" / a["file"]).unlink()
    except OSError:
        pass
    board = read_board()
    board["items"] = [i for i in board["items"] if i.get("asset_id") != aid]
    write_board(board)
    return {"deleted": aid}


# ── Studio: board ────────────────────────────────────────────────────

def read_board() -> dict:
    b = _read_json(_studio() / "board.json", {"items": []})
    return b if isinstance(b, dict) and isinstance(b.get("items"), list) else {"items": []}


def write_board(body) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("items"), list) or len(body["items"]) > 300:
        raise ApiError(400, "board must be {items: [...]} with at most 300 items")
    items = []
    for i in body["items"]:
        if not isinstance(i, dict) or i.get("kind") not in ("asset", "note") or not isinstance(i.get("id"), str):
            raise ApiError(400, "each item needs id and kind asset|note")
        geo = {k: i.get(k) for k in ("x", "y", "w", "h")}
        if not all(isinstance(v, (int, float)) and -5000 <= v <= 20000 for v in geo.values()):
            raise ApiError(400, "x, y, w, h must be numbers")
        item = {"id": i["id"][:64], "kind": i["kind"], **{k: round(v) for k, v in geo.items()}}
        if i["kind"] == "asset":
            item["asset_id"] = str(i.get("asset_id", ""))[:64]
        else:
            item["text"] = str(i.get("text", ""))[:4000]
            item["color"] = str(i.get("color", "yellow"))[:16]
        items.append(item)
    out = {"items": items, "updated_at": time.time()}
    _write_json(_studio() / "board.json", out)
    return out


# ── Studio: image providers ──────────────────────────────────────────

def _hf_cached(repo: str) -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    snap = hub / ("models--" + repo.replace("/", "--")) / "snapshots"
    return snap.is_dir() and any(snap.iterdir())


def _fal_ready() -> bool:
    try:
        from jaeger_ai.plugins import ai_gen
        return bool(ai_gen._fal_key())
    except Exception:  # noqa: BLE001
        return False


def providers() -> list[dict]:
    try:
        import diffusers  # noqa: F401
        has_diffusers = True
    except Exception:  # noqa: BLE001
        has_diffusers = False
    local_ok = has_diffusers and _hf_cached("stabilityai/sdxl-turbo")
    fal_ok = _fal_ready()
    return [
        {"id": "local-sdxl-turbo", "name": "SDXL-Turbo (on this Mac)", "kind": "local", "available": local_ok, "cost": "free",
         "note": None if local_ok else ("diffusers is installed but the stabilityai/sdxl-turbo weights (~6 GB) are not downloaded. "
                                        "Ask Jaeger in chat to run image_generate once, or download the model, then reload." if has_diffusers else
                                        "diffusers is not installed in the Jaeger environment.")},
        {"id": "fal-flux-schnell", "name": "FLUX schnell (fal.ai cloud)", "kind": "cloud", "available": fal_ok, "cost": "paid, a few cents per image",
         "note": None if fal_ok else "Needs the FAL_KEY credential in Jaeger's credential store (Settings → Credentials)."},
    ]


_pipe = None


def generate(body: dict) -> dict:
    prompt = str(body.get("prompt", "")).strip()
    if not prompt or len(prompt) > 2000:
        raise ApiError(400, "prompt must be 1-2000 characters")
    pid = body.get("provider")
    info = next((p for p in providers() if p["id"] == pid), None)
    if not info:
        raise ApiError(400, "unknown provider")
    if not info["available"]:
        raise ApiError(409, "provider not set up", note=info["note"])
    started = time.perf_counter()
    if pid == "local-sdxl-turbo":
        data = _gen_local(prompt, body.get("seed"))
    else:
        data = _gen_fal(prompt)
    item = add_asset(data, "image/png", prompt[:60], source="generated", tags=["generated"], prompt=prompt, provider=pid)
    item["elapsed_s"] = round(time.perf_counter() - started, 1)
    return item


def _gen_local(prompt: str, seed) -> bytes:
    global _pipe
    import io
    import torch
    from diffusers import AutoPipelineForText2Image
    with _lock:
        if _pipe is None:
            _pipe = AutoPipelineForText2Image.from_pretrained("stabilityai/sdxl-turbo", torch_dtype=torch.float16, variant="fp16", local_files_only=True)
            _pipe.to("mps" if torch.backends.mps.is_available() else "cpu")
        gen = torch.Generator(device="cpu").manual_seed(int(seed)) if isinstance(seed, int) else None
        img = _pipe(prompt=prompt, num_inference_steps=1, guidance_scale=0.0, generator=gen).images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gen_fal(prompt: str) -> bytes:
    from jaeger_ai.plugins import ai_gen
    key = ai_gen._fal_key()
    model = ai_gen._normalize_model("flux/schnell", ai_gen.DEFAULT_IMAGE_MODEL)
    try:
        result = ai_gen._queue_generate(model, {"prompt": prompt}, key, ai_gen.IMAGE_TIMEOUT_S)
        url = ai_gen._first_image_url(result)
        if not url:
            raise ApiError(502, "fal.ai returned no image")
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ApiError(502, f"fal.ai generation failed: {exc}") from exc


# ── Models (Ollama) ──────────────────────────────────────────────────

def _ollama(path: str, body: dict | None = None, timeout: float = 10, method: str | None = None):
    req = urllib.request.Request(OLLAMA + path, data=None if body is None else json.dumps(body).encode(), method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code if exc.code < 500 else 502, f"Ollama: {exc.read()[:200].decode(errors='replace')}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(503, "Ollama is not reachable on 127.0.0.1:11434", note="Start Ollama (ollama serve) to manage local models.") from exc


def local_models() -> dict:
    tags = _ollama("/api/tags").get("models", [])
    try:
        loaded = {m.get("name"): m for m in _ollama("/api/ps").get("models", [])}
    except ApiError:
        loaded = {}
    out = []
    for m in tags:
        d = m.get("details") or {}
        lm = loaded.get(m.get("name"))
        out.append({"name": m.get("name"), "size": m.get("size"), "modified_at": m.get("modified_at"), "family": d.get("family"),
                    "parameters": d.get("parameter_size"), "quantization": d.get("quantization_level"), "format": d.get("format"),
                    "context": d.get("context_length"), "loaded": bool(lm), "vram": (lm or {}).get("size_vram")})
    return {"models": out, "pulls": list(_pulls.values())}


def _sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hardware() -> dict:
    mem = int(_sysctl("hw.memsize") or 0)
    gpu_cores = None
    try:
        out = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'"gpu-core-count"\s*=\s*(\d+)', out)
        gpu_cores = int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        pass
    return {"chip": _sysctl("machdep.cpu.brand_string") or None, "memory": mem or None, "cpu_cores": int(_sysctl("hw.ncpu") or 0) or None,
            "perf_cores": int(_sysctl("hw.perflevel0.physicalcpu") or 0) or None, "gpu_cores": gpu_cores,
            "unified_memory": True, "note": "Fit estimate: a model needs about its file size plus ~20% for context; macOS lets the GPU use ~75% of RAM."}


_pulls: dict[str, dict] = {}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}(:[A-Za-z0-9._-]{1,60})?$")


def pull(body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    if not _NAME.match(name):
        raise ApiError(400, "invalid model name")
    if _pulls.get(name, {}).get("state") == "running":
        return _pulls[name]
    _ollama("/api/version")  # reachable?
    st = {"name": name, "state": "running", "status": "starting", "completed": 0, "total": 0, "started_at": time.time()}
    _pulls[name] = st

    def run():
        req = urllib.request.Request(OLLAMA + "/api/pull", data=json.dumps({"name": name, "stream": True}).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    ev = json.loads(line or b"{}")
                    if ev.get("error"):
                        st.update(state="error", status=ev["error"])
                        return
                    st.update(status=ev.get("status", st["status"]), completed=ev.get("completed", st["completed"]), total=ev.get("total", st["total"]))
            st.update(state="done", status="success")
        except Exception as exc:  # noqa: BLE001
            st.update(state="error", status=str(exc)[:200])
    threading.Thread(target=run, daemon=True, name=f"ollama-pull-{name}").start()
    return st


def remove_model(name: str) -> dict:
    if not _NAME.match(name):
        raise ApiError(400, "invalid model name")
    _ollama("/api/delete", {"name": name}, method="DELETE")
    return {"deleted": name}


def compare_run(body: dict) -> dict:
    model, prompt = str(body.get("model", "")), str(body.get("prompt", ""))
    if not _NAME.match(model) or not prompt.strip() or len(prompt) > 20000:
        raise ApiError(400, "need a model and a prompt (≤20000 chars)")
    t0 = time.perf_counter()
    r = _ollama("/api/generate", {"model": model, "prompt": prompt, "stream": False}, timeout=300)
    return {"model": model, "response": r.get("response", ""), "elapsed_s": round(time.perf_counter() - t0, 2),
            "eval_count": r.get("eval_count"), "tokens_per_s": round(r["eval_count"] / (r["eval_duration"] / 1e9), 1) if r.get("eval_count") and r.get("eval_duration") else None,
            "load_s": round(r.get("load_duration", 0) / 1e9, 2)}


def _metrics(ev: dict, elapsed: float, ttft: float | None, local: bool) -> dict:
    ec, ed = ev.get("eval_count"), ev.get("eval_duration")
    return {"elapsed_s": round(elapsed, 2), "ttft_s": None if ttft is None else round(ttft, 2),
            "eval_count": ec, "prompt_eval_count": ev.get("prompt_eval_count"),
            "tokens_per_s": round(ec / (ed / 1e9), 1) if ec and ed else None,
            "load_s": round(ev.get("load_duration", 0) / 1e9, 2),
            # Local Ollama runs cost nothing per token; Ollama cloud pricing isn't exposed, so unknown.
            "cost_usd": 0.0 if local else None}


_CLI_MODEL = re.compile(r"^cli:([a-z]+):([A-Za-z0-9][A-Za-z0-9._\[\]=,-]{0,80})$")


def _valid_model(name: str) -> bool:
    return bool(_NAME.match(name) or _CLI_MODEL.match(name))


def _cli():
    try:
        from api import cli_providers  # type: ignore
    except ImportError:  # loaded standalone (tests)
        import importlib.util
        spec = importlib.util.spec_from_file_location("_cli_providers", Path(__file__).with_name("cli_providers.py"))
        cli_providers = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli_providers)
    return cli_providers


def compare_stream_events(body: dict, opener=None):
    """Yield NDJSON-able events for one model: {type:start}, {type:delta,text}, {type:done,...metrics} or {type:error}.
    Ollama names go to 127.0.0.1:11434; `cli:<provider>:<model>` runs that signed-in CLI as a subprocess."""
    model, prompt = str(body.get("model", "")), str(body.get("prompt", ""))
    mc = _CLI_MODEL.match(model)
    if mc:
        if not prompt.strip() or len(prompt) > 20000:
            raise ApiError(400, "need a model and a prompt (≤20000 chars)")
        if not _cli().known(mc.group(1)):
            raise ApiError(400, f"unknown CLI provider {mc.group(1)}")
        yield from _cli().stream(mc.group(1), mc.group(2), prompt)
        return
    if not _NAME.match(model) or not prompt.strip() or len(prompt) > 20000:
        raise ApiError(400, "need a model and a prompt (≤20000 chars)")
    local = not re.search(r"(^|[-:])cloud\b", model)
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps({"model": model, "stream": True, "messages": [{"role": "user", "content": prompt}]}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); ttft = None
    yield {"type": "start", "model": model, "local": local}
    try:
        with (opener or urllib.request.urlopen)(req, timeout=600) as r:
            for line in r:
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    yield {"type": "error", "error": f"Ollama: {ev['error']}"[:300]}
                    return
                msg = ev.get("message") or {}
                text = msg.get("content") or ""
                think = msg.get("thinking") or ""
                if (text or think) and ttft is None:
                    ttft = time.perf_counter() - t0
                if think:
                    yield {"type": "thinking", "text": think}
                if text:
                    yield {"type": "delta", "text": text}
                if ev.get("done"):
                    yield {"type": "done", "model": model, **_metrics(ev, time.perf_counter() - t0, ttft, local)}
                    return
    except urllib.error.HTTPError as exc:
        yield {"type": "error", "error": f"Ollama {exc.code}: {exc.read()[:200].decode(errors='replace')}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        yield {"type": "error", "error": f"Ollama is not reachable on 127.0.0.1:11434 ({exc.__class__.__name__})"}


def _chain(first, rest):
    yield first
    yield from rest


def _stream(handler, events) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    try:
        for ev in events:
            data = (json.dumps(ev) + "\n").encode()
            handler.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            handler.wfile.flush()
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass


# ── Compare history ──────────────────────────────────────────────────
_RUN_ID = re.compile(r"^[a-f0-9]{12}$")
MAX_RUNS = 100


def _history_path() -> Path:
    return state_root() / "compare" / "history.json"


def list_runs() -> list[dict]:
    runs = _read_json(_history_path(), [])
    return runs if isinstance(runs, list) else []


def save_run(body: dict) -> dict:
    prompt = str(body.get("prompt", ""))[:20000]
    results = body.get("results")
    if not prompt.strip() or not isinstance(results, list) or not 1 <= len(results) <= 4:
        raise ApiError(400, "need a prompt and 1–4 results")
    keep = ("model", "response", "elapsed_s", "ttft_s", "eval_count", "prompt_eval_count", "tokens_per_s", "load_s", "cost_usd", "error")
    clean = []
    for r in results:
        if not isinstance(r, dict) or not _valid_model(str(r.get("model", ""))):
            raise ApiError(400, "each result needs a valid model")
        c = {k: r.get(k) for k in keep if k in r}
        if isinstance(c.get("response"), str):
            c["response"] = c["response"][:200000]
        clean.append(c)
    run = {"id": uuid.uuid4().hex[:12], "created_at": time.time(), "prompt": prompt, "results": clean, "winner": None}
    with _lock:
        _write_json(_history_path(), ([run] + list_runs())[:MAX_RUNS])
    return run


def update_run(rid: str, body: dict) -> dict:
    if not _RUN_ID.match(rid):
        raise ApiError(404, "no such run")
    with _lock:
        runs = list_runs()
        run = next((r for r in runs if r.get("id") == rid), None)
        if not run:
            raise ApiError(404, "no such run")
        w = body.get("winner")
        if w is not None and w not in {r.get("model") for r in run["results"]} and w != "tie":
            raise ApiError(400, "winner must be one of the run's models, 'tie', or null")
        run["winner"] = w
        _write_json(_history_path(), runs)
    return run


def delete_run(rid: str) -> dict:
    with _lock:
        runs = list_runs()
        if not any(r.get("id") == rid for r in runs):
            raise ApiError(404, "no such run")
        _write_json(_history_path(), [r for r in runs if r.get("id") != rid])
    return {"deleted": rid}


# ── Task pipeline (Intake → Research → Studio → Production → Review → Done) ──
# The gateway's task records have no writable stage field (only presentation flags), so the
# pipeline stage and the task's attached sources/notes/assets/deliverables live here, keyed by the
# gateway task_id, in <state>/pipeline/tasks.json. Stage changes are explicit user actions with a
# history; nothing advances on its own.
STAGES = ("intake", "research", "studio", "production", "review", "done")
ATTACH_KINDS = ("note", "source", "document", "asset", "artifact", "deliverable")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")


def _pipeline_path() -> Path:
    return state_root() / "pipeline" / "tasks.json"


def _pipeline() -> dict:
    d = _read_json(_pipeline_path(), {})
    return d if isinstance(d, dict) else {}


def list_pipeline() -> dict:
    return {"stages": list(STAGES), "items": _pipeline()}


def _task_rec(items: dict, tid: str, create: bool = False) -> dict:
    if not _TASK_ID.match(tid):
        raise ApiError(400, "invalid task id")
    rec = items.get(tid)
    if rec is None:
        if not create:
            raise ApiError(404, "task is not in the pipeline")
        rec = items[tid] = {"task_id": tid, "stage": None, "revision": 0, "history": [], "attachments": [], "created_at": time.time()}
    return rec


def set_stage(tid: str, body: dict) -> dict:
    stage = body.get("stage")
    if stage not in STAGES:
        raise ApiError(400, f"stage must be one of {', '.join(STAGES)}")
    with _lock:
        items = _pipeline()
        rec = _task_rec(items, tid, create=True)
        exp = body.get("expected_revision")
        if exp is not None and exp != rec["revision"]:
            raise ApiError(409, "the task's stage changed elsewhere; reload", current=rec)
        if rec["stage"] != stage:
            rec["history"].append({"from": rec["stage"], "to": stage, "at": time.time(), "note": str(body.get("note", ""))[:500] or None})
            rec["stage"] = stage
            rec["revision"] += 1
            rec["updated_at"] = time.time()
        _write_json(_pipeline_path(), items)
    return rec


def add_attachment(tid: str, body: dict) -> dict:
    kind = body.get("kind")
    if kind not in ATTACH_KINDS:
        raise ApiError(400, f"kind must be one of {', '.join(ATTACH_KINDS)}")
    label = str(body.get("label", "")).strip()[:300]
    ref = str(body.get("ref", "")).strip()[:2000]
    text = str(body.get("text", ""))[:20000]
    if kind == "note" and not text.strip():
        raise ApiError(400, "a note needs text")
    if kind == "source" and not re.match(r"^https?://", ref):
        raise ApiError(400, "a source needs an http(s) URL")
    if kind in ("document", "asset", "artifact", "deliverable") and not ref:
        raise ApiError(400, f"a {kind} needs a ref")
    with _lock:
        items = _pipeline()
        rec = _task_rec(items, tid, create=True)
        if rec["stage"] is None:
            rec["stage"] = "intake"; rec["history"].append({"from": None, "to": "intake", "at": time.time(), "note": None}); rec["revision"] += 1
        if any(a["kind"] == kind and a.get("ref") == ref and ref for a in rec["attachments"]):
            raise ApiError(409, "already attached")
        att = {"id": uuid.uuid4().hex[:12], "kind": kind, "ref": ref or None, "label": label or None, "text": text or None,
               "stage": body.get("stage") if body.get("stage") in STAGES else rec["stage"], "at": time.time()}
        rec["attachments"].append(att)
        rec["updated_at"] = time.time()
        _write_json(_pipeline_path(), items)
    return att


def remove_attachment(tid: str, aid: str) -> dict:
    with _lock:
        items = _pipeline()
        rec = _task_rec(items, tid)
        before = len(rec["attachments"])
        rec["attachments"] = [a for a in rec["attachments"] if a.get("id") != aid]
        if len(rec["attachments"]) == before:
            raise ApiError(404, "no such attachment")
        _write_json(_pipeline_path(), items)
    return {"deleted": aid}


# ── Documents ────────────────────────────────────────────────────────

def _docs() -> Path:
    p = state_root() / "documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_docs() -> list[dict]:
    out = []
    for f in _docs().glob("*.json"):
        d = _read_json(f, None)
        if isinstance(d, dict):
            out.append({k: d.get(k) for k in ("id", "title", "updated_at", "created_at")} | {"chars": len(d.get("body", ""))})
    return sorted(out, key=lambda d: -(d.get("updated_at") or 0))


def get_doc(did: str) -> dict:
    if not _ID.match(did):
        raise ApiError(404, "no such document")
    d = _read_json(_docs() / f"{did}.json", None)
    if not isinstance(d, dict):
        raise ApiError(404, "no such document")
    return d


def save_doc(did: str | None, body: dict) -> dict:
    title, text = str(body.get("title", "")).strip()[:200] or "Untitled", body.get("body", "")
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ApiError(400, "body must be text up to 2 MB")
    now = time.time()
    if did:
        cur = get_doc(did)
        if body.get("expected_updated_at") is not None and abs(float(body["expected_updated_at"]) - cur["updated_at"]) > 1e-6:
            raise ApiError(409, "document changed elsewhere; reload it", current=cur)
        doc = cur | {"title": title, "body": text, "updated_at": now}
    else:
        doc = {"id": uuid.uuid4().hex[:16], "title": title, "body": text, "created_at": now, "updated_at": now}
    _write_json(_docs() / f"{doc['id']}.json", doc)
    return doc


def delete_doc(did: str) -> dict:
    get_doc(did)
    (_docs() / f"{did}.json").unlink()
    return {"deleted": did}


AI_EDITS = {
    "improve": "Improve the clarity and flow of this Markdown text. Keep its meaning, structure and Markdown formatting.",
    "shorten": "Make this Markdown text about half as long, keeping the key points and Markdown formatting.",
    "expand": "Expand this Markdown text with more detail and examples, keeping its tone and Markdown formatting.",
    "fix": "Fix spelling, grammar and punctuation in this Markdown text. Change nothing else.",
    "summarize": "Summarize this Markdown text as a short bulleted list in Markdown.",
    "outline": "Turn this text into a well-structured Markdown outline with headings and bullets.",
}


def ai_edit(body: dict) -> dict:
    action, text, model = body.get("action"), str(body.get("text", "")), str(body.get("model", ""))
    instruction = AI_EDITS.get(action) if action != "custom" else str(body.get("instruction", "")).strip()[:1000]
    if not instruction:
        raise ApiError(400, f"action must be one of {sorted(AI_EDITS) + ['custom']}")
    if not text.strip() or len(text) > 60000:
        raise ApiError(400, "select 1-60000 characters to edit")
    prompt = f"{instruction}\nReturn only the rewritten text, with no preamble.\n\n---\n{text}\n---"
    r = compare_run({"model": model, "prompt": prompt})
    out = r["response"].strip()
    if out.startswith("---"):
        out = out.strip("-\n ")
    return {"text": out, "model": model, "elapsed_s": r["elapsed_s"]}


# ── YouTube research (jobs in youtube_research.py) ──────────────────

def _yt():
    try:
        from api import youtube_research as yt  # type: ignore
    except ImportError:  # loaded standalone (tests)
        import importlib.util, sys
        yt = sys.modules.get("_youtube_research")
        if yt is None:
            spec = importlib.util.spec_from_file_location("_youtube_research", Path(__file__).with_name("youtube_research.py"))
            yt = importlib.util.module_from_spec(spec); sys.modules["_youtube_research"] = yt; spec.loader.exec_module(yt)
    if not yt._deps.get("_bound_by_webui"):
        rm = _rm()
        yt.bind(_bound_by_webui=True, state_root=state_root, llm=llm_text, vision=_vision, ollama_models=lambda: [m.get("name") for m in _ollama("/api/tags").get("models", [])],
                set_stage=set_stage, attach=add_attachment, get_record=lambda tid: _pipeline().get(tid), save_doc=save_doc, rm=rm, usage=lambda: getattr(_usage, "last", None),
                cleanup=lambda d: _rmmod().cleanup_temp(d, older_than_s=0))
    return yt


def _rmmod():
    try:
        from api import resource_manager as rmm  # type: ignore
    except ImportError:
        import importlib.util, sys
        rmm = sys.modules.get("_resource_manager")
        if rmm is None:
            spec = importlib.util.spec_from_file_location("_resource_manager", Path(__file__).with_name("resource_manager.py"))
            rmm = importlib.util.module_from_spec(spec); sys.modules["_resource_manager"] = rmm; spec.loader.exec_module(rmm)
    return rmm


def _rm():
    return _rmmod().shared(state_root)


_usage = threading.local()


def _is_local(model: str) -> bool:
    return not model.startswith("cli:") and not re.search(r"(^|[-:])cloud\b", model)


def llm_text(model: str, prompt: str) -> str:
    """One prompt -> full text. Local Ollama models go straight to /api/chat with thinking off and a 16k context
    (research prompts are long; thinking models are slow); everything else uses the provider layer."""
    if _is_local(model):
        r = _ollama("/api/chat", {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False,
                                  "options": {"num_ctx": 16384}}, timeout=1800)
        _usage.last = {"prompt": r.get("prompt_eval_count"), "output": r.get("eval_count")}
        return (r.get("message") or {}).get("content", "")
    _usage.last = None
    out = []
    for ev in compare_stream_events({"model": model, "prompt": prompt}):
        if ev.get("type") == "delta":
            out.append(ev.get("text", ""))
        elif ev.get("type") == "error":
            raise RuntimeError(f"{model}: {ev.get('error') or ev.get('message') or 'provider error'}")
    return "".join(out)


def _vision(model: str, prompt: str, images) -> str:
    imgs = [images] if isinstance(images, str) else list(images)
    r = _ollama("/api/generate", {"model": model, "prompt": prompt, "images": imgs, "stream": False, "think": False,
                                  "options": {"num_ctx": 8192}}, timeout=600)
    _usage.last = {"prompt": r.get("prompt_eval_count"), "output": r.get("eval_count")}
    return r.get("response", "")


def runner_status() -> dict:
    """24/7 job runner health + queue + per-job progress (read from its heartbeat and the job files)."""
    yt = _yt()
    jd = state_root() / "jobs"
    try:
        hb = json.loads((jd / "runner.json").read_text("utf-8"))
    except (OSError, ValueError):
        hb = None
    age = time.time() - float(hb.get("at") or 0) if hb else None
    health = "down" if hb is None or age > yt.RUNNER_FRESH_S else hb.get("health", "ok")
    try:
        queue = json.loads((jd / "queue.json").read_text("utf-8"))
    except (OSError, ValueError):
        queue = []
    jobs = []
    for q in queue if isinstance(queue, list) else []:
        try:
            s = yt.status(q["task_id"])
        except Exception as exc:  # noqa: BLE001
            jobs.append({**q, "error": str(exc)[:200]}); continue
        idle = time.time() - yt.last_progress_at(s)
        errs = [{"video_id": v["id"], "step": k, "error": (x.get("error") or "")[:200]} for v in s["videos"] for k, x in v["steps"].items() if x.get("status") == "error"]
        jobs.append({**q, "title": s.get("playlist_title"), "state": s.get("state"), "phase": s.get("phase"), "paused": bool(s.get("paused")),
                     "running": s.get("running"), "videos_in_job": len(s["videos"]), "item_count": s.get("item_count"), "progress": s.get("progress"),
                     "videos_done": sum(1 for v in s["videos"] if v["steps"]["analysis"].get("status") == "done"),
                     "last_progress_s": round(idle), "stuck": bool(s.get("running") and idle > 3600), "errors": errs[:20], "error_count": len(errs),
                     "tokens": s.get("tokens"), "style_guide": s.get("style_guide", {}).get("status"), "kb": (s.get("kb") or {}).get("status"), "workers": s.get("workers")})
    return {"service": "com.jenkinsrobotics.jaeger-jobs", "health": health, "heartbeat_age_s": round(age) if age is not None else None,
            "runner": {k: hb.get(k) for k in ("pid", "started_at", "active", "owned", "retries", "next_try", "events")} if hb else None, "jobs": jobs}


def _yt_route(handler, p: str, method: str, body: dict, j, parsed_query: str = "") -> bool:
    yt = _yt()
    try:
        if p == "/v1/research/youtube/tools" and method == "GET":
            return j(handler, yt.tools()) or True
        if p == "/v1/research/youtube" and method == "GET":
            return j(handler, {"jobs": yt.list_jobs()}) or True
        if p == "/v1/research/youtube/preview" and method == "POST":
            return j(handler, yt.preview(body)) or True
        if p == "/v1/research/youtube/techniques" and method == "GET":
            qs = parse_qs(parsed_query or "")
            return j(handler, yt.techniques(q=(qs.get("q") or [""])[0], type_=(qs.get("type") or [""])[0], creator=(qs.get("creator") or [""])[0])) or True
        mv = re.match(r"^/v1/research/youtube/([^/]+)/videos/([A-Za-z0-9_-]{11})$", p)
        if mv and method == "GET":
            return j(handler, yt.video_detail(unquote(mv.group(1)), mv.group(2))) or True
        if p == "/v1/research/youtube" and method == "POST":
            return j(handler, yt.ingest(body), status=202) or True
        mf = re.match(r"^/v1/research/youtube/([^/]+)/videos/([A-Za-z0-9_-]{11})/frames/((?:seq/)?[fs]\d{2,3}(?:_\d)?\.jpg)$", p)
        if mf and method == "GET":
            data = yt.frame_file(unquote(mf.group(1)), mf.group(2), mf.group(3)).read_bytes()
            handler.send_response(200); handler.send_header("Content-Type", "image/jpeg"); handler.send_header("Content-Length", str(len(data)))
            handler.send_header("X-Content-Type-Options", "nosniff"); handler.end_headers(); handler.wfile.write(data)
            return True
        m = re.match(r"^/v1/research/youtube/([^/]+)(?:/(run|cancel|style-guide|draft|drafts|watch|import|poll|pause|resume|reorder))?$", p)
        if m:
            tid, act = unquote(m.group(1)), m.group(2)
            if act is None and method == "GET":
                return j(handler, yt.status(tid)) or True
            if act == "run" and method == "POST":
                force = body.get("force") or []
                if not isinstance(force, list) or not set(force) <= set(yt.STEPS) | {"style_guide"}:
                    raise ApiError(400, f"force must list steps from {list(yt.STEPS) + ['style_guide']}")
                return j(handler, yt.start(tid, force=force, style_guide=body.get("style_guide", True) is not False), status=202) or True
            if act == "cancel" and method == "POST":
                return j(handler, yt.cancel(tid)) or True
            if act == "style-guide" and method == "GET":
                return j(handler, yt.style_guide(tid)) or True
            if act == "style-guide" and method == "POST":
                return j(handler, yt.build_style_guide(tid, force=True, model=body.get("model"))) or True
            if act == "draft" and method == "POST":
                return j(handler, yt.draft(tid, body), status=201) or True
            if act == "watch" and method == "POST":
                return j(handler, yt.watch(tid, bool(body.get("enabled", True)), int(body.get("interval_s") or 3600))) or True
            if act in ("pause", "resume") and method == "POST":
                return j(handler, yt.pause(tid, act == "pause")) or True
            if act == "reorder" and method == "POST":
                return j(handler, yt.reorder(tid, body.get("video_ids"))) or True
            if act == "import" and method == "POST":
                return j(handler, yt.import_existing(tid)) or True
            if act == "poll" and method == "POST":
                return j(handler, yt.poll_new(tid)) or True
            if act == "drafts" and method == "GET":
                return j(handler, {"drafts": yt.status(tid).get("drafts", [])}) or True
        raise ApiError(404, "unknown YouTube research endpoint")
    except yt.YtError as exc:
        raise ApiError(exc.status, str(exc), **exc.extra) from exc
    except RuntimeError as exc:
        raise ApiError(502, str(exc)) from exc


def _avatar():
    try:
        from api import avatar_api as av  # type: ignore
    except ImportError:  # loaded standalone (tests)
        import importlib.util, sys
        av = sys.modules.get("_avatar_api")
        if av is None:
            spec = importlib.util.spec_from_file_location("_avatar_api", Path(__file__).with_name("avatar_api.py"))
            av = importlib.util.module_from_spec(spec); sys.modules["_avatar_api"] = av; spec.loader.exec_module(av)
    return av


# ── Router ───────────────────────────────────────────────────────────

def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    av = _avatar()
    if av.handles(p):
        return av.route(handler, parsed, method, read_body, j)
    if not (p.startswith("/v1/studio/") or p.startswith("/v1/models/") or p == "/v1/compare/run" or p.startswith("/v1/compare/") or p.startswith("/v1/providers/cli") or p == "/v1/pipeline" or p.startswith("/v1/pipeline/") or p == "/v1/resources" or p == "/v1/jobs/runner" or p == "/v1/research/youtube" or p.startswith("/v1/research/youtube/") or p == "/v1/documents" or p.startswith("/v1/documents/")):
        return False
    try:
        body = read_body(handler) if method in ("POST", "PUT") else {}
        if not isinstance(body, dict):
            raise ApiError(400, "JSON object body required")
        m = re.match(r"^/v1/studio/assets/([a-z0-9-]+)(/file)?$", p)
        if p == "/v1/studio/providers" and method == "GET":
            return j(handler, {"providers": providers()}) or True
        if p == "/v1/studio/generate" and method == "POST":
            return j(handler, generate(body)) or True
        if p == "/v1/studio/assets" and method == "GET":
            return j(handler, {"assets": list_assets()}) or True
        if p == "/v1/studio/assets" and method == "POST":
            try:
                data = base64.b64decode(str(body.get("data_base64", "")), validate=True)
            except ValueError as exc:
                raise ApiError(400, "data_base64 is not valid base64") from exc
            return j(handler, add_asset(data, str(body.get("mime", "")), str(body.get("name", "")), "imported", body.get("tags")), status=201) or True
        if m and m.group(2) and method == "GET":
            a = get_asset(m.group(1))
            data = (_studio() / "assets" / a["file"]).read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", a["mime"])
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "private, max-age=3600")
            handler.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            handler.wfile.write(data)
            return True
        if m and not m.group(2) and method == "PUT":
            return j(handler, update_asset(m.group(1), body)) or True
        if m and not m.group(2) and method == "DELETE":
            return j(handler, delete_asset(m.group(1))) or True
        if p == "/v1/studio/board":
            if method == "GET":
                return j(handler, read_board()) or True
            if method == "PUT":
                return j(handler, write_board(body)) or True
        if p == "/v1/models/local" and method == "GET":
            return j(handler, local_models()) or True
        if p == "/v1/models/hardware" and method == "GET":
            return j(handler, hardware()) or True
        if p == "/v1/models/pull" and method == "POST":
            return j(handler, pull(body), status=202) or True
        if p == "/v1/models/pulls" and method == "GET":
            return j(handler, {"pulls": list(_pulls.values())}) or True
        if p.startswith("/v1/models/local/") and method == "DELETE":
            return j(handler, remove_model(unquote(p[len("/v1/models/local/"):]))) or True
        if p == "/v1/compare/run" and method == "POST":
            return j(handler, compare_run(body)) or True
        if p == "/v1/compare/stream" and method == "POST":
            events = compare_stream_events(body)  # validates before headers go out
            first = next(events)
            _stream(handler, _chain(first, events))
            return True
        if p == "/v1/providers/cli" and method == "GET":
            return j(handler, {"providers": _cli().detect(refresh="refresh=1" in (parsed.query or ""))}) or True
        mp = re.match(r"^/v1/providers/cli/([a-z]+)$", p)
        if mp and method == "PUT":
            try:
                return j(handler, _cli().update(mp.group(1), body)) or True
            except KeyError as exc:
                raise ApiError(404, "unknown CLI provider") from exc
        if p == "/v1/jobs/runner" and method == "GET":
            return j(handler, runner_status()) or True
        if p == "/v1/resources" and method == "GET":
            st = _rm().status()
            with contextlib.suppress(Exception):
                st["tokens"] = {x["task_id"]: _yt().status(x["task_id"]).get("tokens", {}) for x in _yt().list_jobs()}
            return j(handler, st) or True
        if p == "/v1/research/youtube" or p.startswith("/v1/research/youtube/"):
            return _yt_route(handler, p, method, body, j, parsed.query)
        if p == "/v1/pipeline" and method == "GET":
            return j(handler, list_pipeline()) or True
        mt = re.match(r"^/v1/pipeline/([^/]+)(?:/attachments(?:/([a-f0-9]{12}))?)?$", p)
        if mt:
            tid = unquote(mt.group(1))
            if p.endswith("/attachments") and method == "POST":
                return j(handler, add_attachment(tid, body), status=201) or True
            if mt.group(2) and method == "DELETE":
                return j(handler, remove_attachment(tid, mt.group(2))) or True
            if "/attachments" not in p and method == "PUT":
                return j(handler, set_stage(tid, body)) or True
            if "/attachments" not in p and method == "GET":
                return j(handler, _task_rec(_pipeline(), tid)) or True
        if p == "/v1/compare/history":
            if method == "GET":
                return j(handler, {"runs": list_runs()}) or True
            if method == "POST":
                return j(handler, save_run(body), status=201) or True
        mr = re.match(r"^/v1/compare/history/([a-f0-9]{12})$", p)
        if mr and method == "PUT":
            return j(handler, update_run(mr.group(1), body)) or True
        if mr and method == "DELETE":
            return j(handler, delete_run(mr.group(1))) or True
        if p == "/v1/documents":
            if method == "GET":
                return j(handler, {"documents": list_docs()}) or True
            if method == "POST":
                return j(handler, save_doc(None, body), status=201) or True
        if p == "/v1/documents/ai-edit" and method == "POST":
            return j(handler, ai_edit(body)) or True
        md = re.match(r"^/v1/documents/([a-z0-9-]+)$", p)
        if md:
            if method == "GET":
                return j(handler, get_doc(md.group(1))) or True
            if method == "PUT":
                return j(handler, save_doc(md.group(1), body)) or True
            if method == "DELETE":
                return j(handler, delete_doc(md.group(1))) or True
        raise ApiError(405 if p.startswith(("/v1/studio/", "/v1/models/", "/v1/documents", "/v1/compare/", "/v1/providers/cli", "/v1/pipeline")) else 404, "method not allowed")
    except ApiError as exc:
        j(handler, exc.payload, status=exc.status)
        return True
    except ValueError as exc:
        j(handler, {"error": str(exc)}, status=400)
        return True
