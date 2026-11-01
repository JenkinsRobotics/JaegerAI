"""Background ~/Documents indexer: Docling parse -> qwen3-embedding (Mac Ollama) -> Qdrant.

Runs in its own venv (~/.jaeger/venvs/rag) as a low-priority LaunchAgent.
Holds while the Mac is busy (resources.json gate), stops adding when the disk
budget or free-disk floor is hit, skips secrets/hidden/build dirs.
Run: python -m jaeger_ai.features.oss_stack.docs_indexer [--once] [--root DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from jaeger_ai.features.oss_stack import docs  # noqa: E402

HOME = Path.home()
STATE_DIR = Path(os.environ.get("JAEGER_STATE_DIR", HOME / ".jaeger"))
OSS = STATE_DIR / "oss"
STATE_FILE = OSS / "docs-index.json"
LOG = OSS / "logs" / "docs-indexer.jsonl"
TEXT_EXT = {".md", ".txt", ".markdown", ".rst", ".org", ".csv", ".json", ".yaml", ".yml", ".toml", ".py", ".ts",
            ".tsx", ".js", ".swift", ".sh", ".html", ".htm", ".tex"}
DOCLING_EXT = {".pdf", ".docx", ".pptx", ".xlsx"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", "DerivedData",
             "Pods", ".cache", "site-packages", "Library"}
SECRET_HINTS = ("secret", "token", "password", "passwd", "credential", ".env", "id_rsa", "id_ed25519", ".pem",
                ".key", ".p12", "keychain", "apikey", "api_key")
MAX_FILE_MB = float(os.environ.get("JAEGER_DOCS_MAX_FILE_MB", "25"))
MAX_POINTS = int(os.environ.get("JAEGER_DOCS_MAX_POINTS", "400000"))  # ~2.5 GB with 1024-d vectors
CHUNK, OVERLAP, BATCH = 1500, 200, 32
RESCAN_S = int(os.environ.get("JAEGER_DOCS_RESCAN_S", "1800"))


def log(event, **kw):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"ts": time.time(), "event": event, **kw}) + "\n")


def skip_path(p: Path, root: Path) -> bool:
    rel = p.relative_to(root).parts
    if any(part.startswith(".") or part in SKIP_DIRS for part in rel[:-1]):
        return True
    name = p.name.lower()
    return name.startswith(".") or any(h in name for h in SECRET_HINTS)


def chunks(text: str) -> list[str]:
    text = " ".join(text.split()) if len(text) > 200_000 else text.strip()
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + CHUNK].strip()
        if len(piece) > 40:
            out.append(piece)
        i += CHUNK - OVERLAP
    return out


def dir_prefixes(path: Path) -> list[str]:
    return [str(p) for p in path.parents if str(p).startswith(str(HOME))]


class Indexer:
    def __init__(self, root: Path, post=None, gate=None, converter=None):
        self.root, self.post = root, post or docs._post
        self.gate = gate or self._gate
        self._converter = converter
        try:
            self.state = json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            self.state = {"files": {}, "points": 0}

    # -- environment -------------------------------------------------------
    def _gate(self) -> list[str]:
        # Load average counts runnable work across the whole Mac and is not a
        # useful admission signal for this low-priority embedding job.
        try:
            from jaeger_ai.features.webui.api.resource_manager import ResourceManager
            manager = ResourceManager(lambda: STATE_DIR)
            snap = manager.snapshot().copy()
            snap["cpu_load"] = None
            why = manager.check("light", snap=snap)
        except Exception:  # noqa: BLE001 - minimal native pressure check if manager is unavailable
            why = []
            try:
                level = subprocess.run(
                    ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                    capture_output=True, text=True, timeout=3, check=True,
                ).stdout.strip()
                if level.isdigit() and int(level) > 1:
                    why.append(f"memory pressure level {level}")
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            cfg = json.loads((STATE_DIR / "resources.json").read_text())
            if not isinstance(cfg, dict):
                cfg = {}
        except (OSError, ValueError):
            cfg = {}
        try:
            if shutil.disk_usage(HOME).free / 1e9 < float(cfg.get("min_free_disk_gb", 15)):
                if not any("disk" in reason for reason in why):
                    why.append("low disk")
        except OSError:
            why.append("disk probe unavailable")
        return why

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(STATE_FILE)

    def ensure_collection(self, dim: int):
        base = docs._loopback(docs.QDRANT_URL)
        import urllib.request
        try:
            urllib.request.urlopen(f"{base}/collections/{docs.COLLECTION}", timeout=10)  # noqa: S310
            return
        except Exception:  # noqa: BLE001
            pass
        req = urllib.request.Request(f"{base}/collections/{docs.COLLECTION}", method="PUT",
                                     data=json.dumps({"vectors": {"size": dim, "distance": "Cosine"},
                                                      "on_disk_payload": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30)  # noqa: S310
        self.post(f"{base}/collections/{docs.COLLECTION}/index",
                  {"field_name": "dir_prefixes", "field_schema": "keyword"}, 30)
        self.post(f"{base}/collections/{docs.COLLECTION}/index", {"field_name": "path", "field_schema": "keyword"}, 30)

    # -- parsing -----------------------------------------------------------
    def converter(self):
        if self._converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
            opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
            self._converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
        return self._converter

    def read(self, p: Path) -> str:
        if p.suffix.lower() in DOCLING_EXT:
            return self.converter().convert(str(p)).document.export_to_markdown()
        return p.read_text(errors="ignore")

    # -- indexing ----------------------------------------------------------
    def candidates(self) -> list[Path]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
            for f in filenames:
                p = Path(dirpath) / f
                ext = p.suffix.lower()
                if ext in TEXT_EXT | DOCLING_EXT and not skip_path(p, self.root):
                    out.append(p)
        out.sort(key=lambda p: (p.suffix.lower() in DOCLING_EXT, -self._mtime(p)))
        return out

    @staticmethod
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def delete_file(self, path: str):
        base = docs._loopback(docs.QDRANT_URL)
        self.post(f"{base}/collections/{docs.COLLECTION}/points/delete?wait=true",
                  {"filter": {"must": [{"key": "path", "match": {"value": path}}]}}, 60)

    def index_file(self, p: Path) -> int:
        st = p.stat()
        if st.st_size > MAX_FILE_MB * 1e6 or st.st_size == 0:
            return 0
        pieces = chunks(self.read(p))
        if not pieces:
            return 0
        base = docs._loopback(docs.QDRANT_URL)
        n = 0
        for i in range(0, len(pieces), BATCH):
            batch = pieces[i:i + BATCH]
            vecs = docs.embed(batch, post=self.post)
            if i == 0:
                self.ensure_collection(len(vecs[0]))
            pts = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{p}#{i + j}")), "vector": v,
                    "payload": {"path": str(p), "chunk": i + j, "text": t, "mtime": st.st_mtime,
                                "dir_prefixes": dir_prefixes(p)}}
                   for j, (t, v) in enumerate(zip(batch, vecs))]
            self._put(f"{base}/collections/{docs.COLLECTION}/points?wait=true", {"points": pts})
            n += len(pts)
        return n

    @staticmethod
    def _put(url, body):
        import urllib.request
        req = urllib.request.Request(url, method="PUT", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - loopback
            return json.loads(r.read() or b"{}")

    def pass_once(self, max_files: int | None = None) -> dict:
        files, done, added, errors = self.state.setdefault("files", {}), 0, 0, 0
        seen = set()
        for p in self.candidates():
            key = str(p)
            seen.add(key)
            st_m, st_s = self._mtime(p), (p.stat().st_size if p.exists() else 0)
            sig = hashlib.sha1(f"{st_m}:{st_s}".encode()).hexdigest()[:12]
            prev = files.get(key, {})
            if prev.get("sig") == sig or prev.get("tries", 0) >= 3:
                continue
            while (why := self.gate()):
                self.state["skip_reasons"] = why
                self.state["last_skip"] = time.time()
                self.save()
                log("hold", reasons=why)
                time.sleep(60)
            if self.state.get("skip_reasons"):
                self.state["skip_reasons"] = []
                self.save()
            if self.state.get("points", 0) >= MAX_POINTS:
                log("budget_reached", points=self.state["points"])
                break
            try:
                if key in files:
                    self.delete_file(key)
                    self.state["points"] -= files[key].get("chunks", 0)
                n = self.index_file(p)
                files[key] = {"sig": sig, "chunks": n}
                self.state["points"] = self.state.get("points", 0) + n
                added += n
                self.state["last_successful_index"] = time.time()
                self.save()
            except Exception as exc:  # noqa: BLE001 - one bad file never stops the pass
                errors += 1
                files[key] = {"sig": "", "chunks": 0, "error": str(exc)[:200], "tries": files.get(key, {}).get("tries", 0) + 1}
                log("file_error", path=key, error=str(exc)[:200])
            done += 1
            if done % 20 == 0:
                self.save()
                log("progress", files=done, chunks=added, points=self.state["points"])
            if max_files and done >= max_files:
                break
        for gone in [k for k in files if k not in seen and k.startswith(str(self.root))]:
            if max_files:
                break
            try:
                self.delete_file(gone)
                self.state["points"] -= files.pop(gone).get("chunks", 0)
            except Exception:  # noqa: BLE001
                pass
        self.state["last_pass"] = time.time()
        self.save()
        log("pass_done", files=done, chunks=added, errors=errors, points=self.state["points"])
        return {"files": done, "chunks": added, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HOME / "Documents"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-files", type=int)
    a = ap.parse_args(argv)
    ix = Indexer(Path(a.root).expanduser())
    while True:
        try:
            ix.pass_once(a.max_files)
        except Exception as exc:  # noqa: BLE001
            log("pass_error", error=str(exc)[:300])
        if a.once:
            return
        time.sleep(RESCAN_S)


if __name__ == "__main__":
    main()
