"""Normalize WebUI input without discarding attachment references."""
import base64
import os
from pathlib import Path
from urllib.parse import urlsplit


def normalize_input(value):
    texts, attachments = [], []
    def visit(part):
        if isinstance(part, str):
            texts.append(part)
            return
        if not isinstance(part, dict):
            raise ValueError('Input blocks must be objects or text')
        if 'role' in part:
            if part['role'] != 'user':
                raise ValueError('Run input accepts user messages only')
            content = part.get('content')
            for item in content if isinstance(content, list) else [content]:
                visit(item)
            return
        kind = part.get('type')
        if kind in {'text', 'input_text'}:
            if not isinstance(part.get('text'), str):
                raise ValueError('Text blocks require text')
            texts.append(part['text'])
        elif kind in {'image_url', 'input_image', 'file', 'input_file'}:
            ref = part.get('image_url') if kind in {'image_url', 'input_image'} else part.get('file', part)
            if isinstance(ref, dict):
                ref = ref.get('url') or ref.get('file_data') or ref.get('file_url') or ref.get('path')
            if not isinstance(ref, str) or not ref:
                raise ValueError('Attachment requires a URL, data URL or file path')
            scheme = urlsplit(ref).scheme
            if scheme not in {'', 'http', 'https', 'data'}:
                raise ValueError('Unsupported attachment reference scheme')
            if scheme == 'data':
                header, sep, encoded = ref.partition(',')
                if not sep or not header.endswith(';base64'):
                    raise ValueError('Attachments require base64 data URLs')
                mime = header[5:-7]
                if mime not in {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'application/pdf', 'text/plain'}:
                    raise ValueError('Unsupported attachment MIME type')
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise ValueError('Invalid attachment base64') from exc
                if not decoded or len(decoded) > 8 * 1024 * 1024:
                    raise ValueError('Attachment is empty or exceeds 8 MiB')
            attachments.append(ref)
        else:
            raise ValueError(f'Unsupported input block type: {kind!r}')
    for part in value if isinstance(value, list) else [value]:
        visit(part)
    text = '\n'.join(texts).strip()
    if not text and not attachments:
        raise ValueError('A session_id and non-empty text input are required')
    return text, attachments


def attachment_prompt(root: Path, run_id: str, text: str, attachments: list[str]) -> str:
    """Give the native agent usable references for its file/vision tools.

    Embedded bytes become private files beside the run receipt. URL references
    are not fetched by the adapter; the native agent owns tool use and policy.
    """
    lines = []
    suffixes = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif',
                'image/webp': '.webp', 'application/pdf': '.pdf', 'text/plain': '.txt'}
    for index, ref in enumerate(attachments):
        if ref.startswith('data:'):
            header, _, encoded = ref.partition(',')
            directory = root / 'attachments' / run_id
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / (str(index) + suffixes[header[5:-7]])
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
                handle.write(base64.b64decode(encoded, validate=True))
            ref = str(path.resolve())
        lines.append(ref)
        if ref.startswith('/'):
            path = Path(ref).resolve()
            for folder in ('GitHub', 'Desktop', 'Documents'):
                try:
                    relative = path.relative_to(Path.home() / folder)
                except ValueError:
                    continue
                lines.append('Container mount: ' + str(Path('/mnt/host') / folder / relative))
                break
    if lines:
        return text + '\n\nUser attachments (use the native file or vision tools to inspect; report any inability to read them):\n' + '\n'.join(lines)
    return text


# WebUI uploads (including large composer pastes as pasted-text-*.md) live in
# the attachment inbox, not the workspace. Inline those text files for Jaeger.
_TEXT_ATTACHMENT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".sh",
    ".log", ".rst", ".env",
}
_INLINE_TEXT_ATTACHMENT_CHARS = 512_000


def _webui_attachment_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(raw: str | Path | None) -> None:
        if not raw:
            return
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            return
        if path in seen:
            return
        seen.add(path)
        roots.append(path)

    add(os.getenv("HERMES_WEBUI_ATTACHMENT_DIR", "").strip())
    for env in ("HERMES_WEBUI_STATE_DIR", "JAEGER_WEBUI_STATE_DIR"):
        state = os.getenv(env, "").strip()
        if state:
            add(Path(state).expanduser() / "attachments")
    add(Path.home() / ".jaeger" / "hermes-webui-state" / "attachments")
    add(Path.home() / ".hermes" / "webui" / "attachments")
    return roots


def _is_text_webui_attachment(name: str, mime: str, is_image: bool) -> bool:
    if is_image:
        return False
    mime = str(mime or "").strip().lower()
    if mime.startswith("image/"):
        return False
    suffix = Path(name or "").suffix.lower()
    if suffix in _TEXT_ATTACHMENT_EXTENSIONS:
        return True
    return mime.startswith("text/") or mime in {"application/json", "application/yaml"}


def _read_allowed_webui_attachment(path_s: str, max_chars: int) -> tuple[str, bool] | None:
    if not path_s:
        return None
    try:
        path = Path(path_s).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if not path.is_file():
        return None
    if not any(path.is_relative_to(root) for root in _webui_attachment_roots()):
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n", True


def _markdown_fence(body: str) -> str:
    ticks = "```"
    while ticks in body:
        ticks += "`"
    return f"{ticks}\n{body}\n{ticks}"


def inline_webui_text_attachments(text: str, attachments, *, max_chars: int = _INLINE_TEXT_ATTACHMENT_CHARS) -> str:
    """Expand WebUI file-path attachments into the Jaeger turn prompt.

    Images and non-text files stay as path notes. Text and markdown files
    under the WebUI attachment inbox are inlined so a large paste-as-.md
    send actually reaches the agent.
    """
    prompt = str(text or "").strip()
    blocks: list[str] = []
    if not isinstance(attachments, list):
        return prompt
    cap = max_chars if isinstance(max_chars, int) and max_chars > 0 else _INLINE_TEXT_ATTACHMENT_CHARS
    for item in attachments:
        if not isinstance(item, dict):
            continue
        path_s = str(item.get("path") or "").strip()
        name = str(item.get("name") or item.get("filename") or Path(path_s).name).strip() or "attachment"
        mime = str(item.get("mime") or "").strip()
        is_image = item.get("is_image") is True
        if not _is_text_webui_attachment(name, mime, is_image):
            if path_s:
                kind = "image attachment" if is_image or mime.startswith("image/") else "attachment"
                blocks.append(f"({kind}: {name} at {path_s})")
            continue
        read = _read_allowed_webui_attachment(path_s, cap)
        if read is None:
            if path_s:
                blocks.append(f"(could not read attachment {name} at {path_s})")
            continue
        body, truncated = read
        header = f"Attached file `{name}`"
        if truncated:
            header += f" (truncated to {cap} characters)"
        blocks.append(f"{header}:\n{_markdown_fence(body)}")
    if not blocks:
        return prompt
    suffix = "\n\n".join(blocks)
    return f"{prompt}\n\n{suffix}" if prompt else suffix
