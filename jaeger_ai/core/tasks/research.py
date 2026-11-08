"""Opt-in Research artifact/reference consistency, never factual verification.

The ledger is worker-writable. Matching quotes do not authenticate retrieval or
prove that a citation supports a claim. Only the admitted files are checked.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import re
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit

RESEARCH_CONTRACT = {
    'version': 1, 'kind': 'citation_consistency',
    'report_path': 'research-report.md', 'ledger_path': 'sources.json',
}


def validate_contract(value):
    if (not isinstance(value, dict) or value != RESEARCH_CONTRACT
            or type(value.get('version')) is not int):
        raise ValueError('Unsupported Research citation-consistency contract')
    return dict(RESEARCH_CONTRACT)


def artifact_paths(task_id):
    if not isinstance(task_id, str) or re.fullmatch(r'task_[0-9a-f]{24}', task_id) is None:
        raise ValueError('Research requires an owner-generated task identity')
    return {field: f'research/{task_id}/{RESEARCH_CONTRACT[field]}'
            for field in ('report_path', 'ledger_path')}


def guidance(contract):
    return ('Research completion requires the admitted citation-consistency contract: '
            + json.dumps(contract, sort_keys=True)
            + '. Save a UTF-8 report with numeric inline citations [n] and a final '
            '## Sources section containing [n] https://source-url and indented > "quote" '
            'lines for each cited source. Save a version:1 JSON ledger with sources '
            '(integer id, http(s) url, quotes:[{text: nonempty quote}]). Each quote must '
            'match the report Sources quote exactly. Use retrieved sources; if none are '
            'available retain partial work and report that limitation. The owner checks '
            'these files and publishes the exact report bytes as the result, not your '
            'completion summary. These checks do not prove factual accuracy or retrieval provenance.')


def _url(value):
    if not isinstance(value, str) or value.strip() != value or any(c.isspace() for c in value):
        raise ValueError('Malformed source URL')
    parsed = urlsplit(value)
    parsed.port  # urlsplit defers invalid/non-numeric/out-of-range port checks.
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Malformed source URL')
    return value.split('#', 1)[0]


def check_references(text, ledger):
    if (not isinstance(ledger, dict) or type(ledger.get('version')) is not int
            or ledger['version'] != 1 or not isinstance(ledger.get('sources'), list)
            or not ledger['sources']):
        raise ValueError('Missing or malformed nonempty source ledger')
    sources = {}
    for entry in ledger['sources']:
        if not isinstance(entry, dict) or type(entry.get('id')) is not int or not 1 <= entry['id'] <= 9999:
            raise ValueError('Malformed source ID')
        sid = entry['id']
        if sid in sources:
            raise ValueError('Duplicate source ID')
        url = _url(entry.get('url'))
        quotes = entry.get('quotes')
        if not isinstance(quotes, list) or not quotes:
            raise ValueError('Missing source quotes')
        texts = []
        for quote in quotes:
            if (not isinstance(quote, dict) or not isinstance(quote.get('text'), str)
                    or len(quote['text'].split()) < 3 or '\n' in quote['text'] or '\r' in quote['text']):
                raise ValueError('Malformed source quote')
            texts.append(quote['text'])
        sources[sid] = (url, texts)
    # A deliberately narrow, unambiguous Sources format, matching render --style evidence.
    headers = list(re.finditer(r'(?m)^## Sources\s*$', text))
    if len(headers) != 1:
        raise ValueError('Report requires one final ## Sources section')
    prose, block = text[:headers[0].start()], text[headers[0].end():]
    if re.search(r'<[!/?a-zA-Z]', prose):
        raise ValueError('HTML is not supported in a sourced report body')
    body_lines, fence = [], None
    for line in prose.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif (run[0] == fence[0] and len(run) >= len(fence)
                  and not line[marker.end():].strip()):
                fence = None
            continue
        if fence is None and not re.match(r'^(?: {4}| *\t)', line):
            body_lines.append(line)
    if fence is not None:
        raise ValueError('Unclosed fenced code before Sources section')
    prose = '\n'.join(body_lines)
    # Disallow ambiguous/unclosed inline code rather than count its markers.
    prose = re.sub(r'(`+).*?\1', '', prose, flags=re.DOTALL)
    if '`' in prose:
        raise ValueError('Unclosed inline code in report body')
    cited = {int(i) for i in re.findall(r'(?<![!\\])\[(\d{1,4})\](?![(:])', prose)}
    if not cited:
        raise ValueError('Report has no inline source citations')
    listed, sid = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\[(\d{1,4})\] (\S+)(?: — .*)?', line)
        if match:
            sid = int(match[1])
            if sid in listed:
                raise ValueError('Duplicate report source ID')
            listed[sid] = (_url(match[2]), [])
            continue
        quote = re.fullmatch(r'\s+> "(.+)"', line)
        if quote and sid is not None:
            listed[sid][1].append(quote[1])
        else:
            raise ValueError('Malformed Sources entry or quote')
    if set(listed) != cited or not cited.issubset(sources):
        raise ValueError('Unknown or missing report citation/source reference')
    for sid in cited:
        if listed[sid] != sources[sid]:
            raise ValueError('Report URL or quote does not match source ledger')
    return sorted(cited)


@contextmanager
def _artifact_directory(root: Path, relative_directory: Path):
    """Pin one task directory for the report/ledger pair, never reopen a root."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in (*root.parts[1:], *relative_directory.parts):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_snapshot(directory_fd: int, filename: str, created_at: float):
    """One no-follow regular-file descriptor supplies both stat and bytes."""
    leaf = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(leaf, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode):
            raise ValueError('Research artifact is not a regular file')
        if observed.st_mtime + 1 < created_at:
            raise ValueError('Research artifact predates task')
        blob = stream.read()
        if not blob:
            raise ValueError('Empty Research artifact')
        return blob


def verify_research(task, result, root: Path | None):
    blobs = {}
    try:
        validate_contract(task.payload['research_contract'])
        if root is None:
            raise ValueError('No admitted Research workspace')
        paths = artifact_paths(task.task_id)
        if task.payload.get('research_artifacts') != paths:
            raise ValueError('Research artifact admission does not match owner task identity')
        blobs, receipts = {}, []
        with _artifact_directory(root, Path(paths['report_path']).parent) as directory_fd:
            for field in ('report_path', 'ledger_path'):
                path = root / paths[field]
                blob = _read_snapshot(directory_fd, Path(paths[field]).name, task.created_at)
                blobs[field] = blob
                receipts.append({'path': str(path), 'sha256': hashlib.sha256(blob).hexdigest(),
                                 'research_artifact': field})
        text = blobs['report_path'].decode('utf-8')
        cited = check_references(text, json.loads(blobs['ledger_path']))
        # Overwrite every display path, including worker-supplied output. No
        # later file read or worker summary may substitute different bytes.
        result['text'] = text
        result.pop('output', None)
        for row in receipts:
            row['citation_consistency'] = {'version': 1, 'cited_source_ids': cited}
        return True, receipts
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RuntimeError, AttributeError) as exc:
        reason = 'Research citation consistency not verified: ' + str(exc)
        # Worker claims stay explicitly unverified; never display 'complete'
        # as the primary outcome after the owner rejected the evidence.
        result['unverified_worker_result'] = {k: v for k, v in result.items()
                                             if k != 'unverified_worker_result'}
        result['text'] = reason
        partial = blobs.get('report_path', b'').decode('utf-8', errors='replace')
        if partial:
            result['text'] += '\n\nRetained partial report (not verified):\n' + partial
        result.pop('output', None)
        return False, reason
