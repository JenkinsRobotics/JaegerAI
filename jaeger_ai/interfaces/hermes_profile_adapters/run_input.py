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
