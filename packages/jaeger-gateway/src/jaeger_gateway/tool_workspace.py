"""Owner WebUI source workspace for tool development."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import threading
from pathlib import Path

SOURCE_LIMIT = 256_000
DRAFT_ROOT = "packages/jaeger-tools/src/jaeger_tools/custom"
SOURCES = {
    "packages/jaeger-tools/src/jaeger_tools/builtins.py": "Built-in tool definitions",
    "packages/jaeger-tools/src/jaeger_tools/registry.py": "Tool registry and shell",
    "packages/jaeger-tools/src/jaeger_tools/editors.py": "File editing helpers",
    "packages/jaeger-tools/src/jaeger_tools/search.py": "Tool search helpers",
    "packages/jaeger-tools/src/jaeger_tools/router.py": "Tool routing",
    "packages/jaeger-gateway/src/jaeger_gateway/runtime.py": "Platform tool registrations",
    "packages/jaeger-youtube/src/jaeger_youtube/data_api.py": "YouTube Data API",
    "packages/jaeger-youtube/src/jaeger_youtube/av_analysis.py": "Audiovisual analysis",
    "packages/jaeger-youtube/src/jaeger_youtube/browse.py": "Supervised YouTube browsing",
}
SLASH_COMMANDS = (
    ("/help", "List terminal chat commands."),
    ("/status", "Show Gateway, model, resources, and embodiment status."),
    ("/droid", "Inspect attached cameras, microphones, and speakers."),
    ("/identity", "Show the current identity and character settings."),
    ("/goals", "List persistent goals."),
    ("/clear", "Start a fresh terminal conversation."),
    ("/open", "Open the Studio WebUI."),
    ("/quit", "Exit terminal chat. Alias: /exit."),
)
_DRAFT = re.compile(re.escape(DRAFT_ROOT) + r"/[a-z][a-z0-9_]{0,63}\.py")


class SourceConflict(Exception):
    """Source changed since the owner opened it."""


class ToolWorkspace:
    def __init__(self, workspace: Path) -> None:
        self.root = workspace.resolve()
        self._lock = threading.Lock()

    def _path(self, path: str) -> Path:
        if path not in SOURCES and not _DRAFT.fullmatch(path):
            raise ValueError("Select a tool source file or a valid new tool module.")
        target = self.root / path
        if target.resolve() != target:
            raise ValueError("Linked source paths are unavailable in the editor.")
        return target

    def catalog(self) -> dict[str, list[dict[str, str]]]:
        candidates = list(SOURCES) + [
            str(path.relative_to(self.root)) for path in sorted((self.root / DRAFT_ROOT).glob("*.py"))
            if not path.is_symlink()
        ]
        rows = []
        for path in candidates:
            try:
                if self._path(path).is_file():
                    rows.append({"path": path, "label": SOURCES.get(path, Path(path).stem)})
            except ValueError:
                continue
        return {"sources": rows, "slash_commands": [
            {"name": name, "description": description, "surface": "Terminal Chat"}
            for name, description in SLASH_COMMANDS
        ]}

    def read(self, path: str) -> dict[str, str]:
        target = self._path(path)
        with target.open("rb") as source:
            data = source.read(SOURCE_LIMIT + 1)
        if len(data) > SOURCE_LIMIT:
            raise ValueError("Source exceeds the editor size limit.")
        return {"path": path, "source": data.decode("utf-8"), "revision": hashlib.sha256(data).hexdigest()}

    def save(self, path: str, source: str, revision: str | None) -> dict[str, str]:
        target = self._path(path)
        data = source.encode("utf-8")
        if not data or len(data) > SOURCE_LIMIT:
            raise ValueError("Provide between 1 and 256,000 bytes of Python source.")
        try:
            compile(source, path, "exec")
        except SyntaxError as error:
            raise ValueError(f"Line {error.lineno}: {error.msg}") from None
        with self._lock:
            if revision is None:
                if not _DRAFT.fullmatch(path):
                    raise ValueError("New files must be tool modules.")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise SourceConflict("That tool module already exists.")
                mode = 0o644
            else:
                if not target.is_file() or self.read(path)["revision"] != revision:
                    raise SourceConflict("Source changed on disk. Reload it before saving.")
                mode = stat.S_IMODE(target.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".tool-", delete=False) as tmp:
                temporary = Path(tmp.name)
                try:
                    tmp.write(data)
                    tmp.flush()
                    os.fchmod(tmp.fileno(), mode)
                    if revision is None:
                        try:
                            os.link(temporary, target)
                        except FileExistsError:
                            raise SourceConflict("That tool module already exists.") from None
                    else:
                        os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            return self.read(path)
