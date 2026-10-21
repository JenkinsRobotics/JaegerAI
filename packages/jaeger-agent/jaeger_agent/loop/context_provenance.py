"""Private producer-to-dispatch references; receipts never contain source text.

A fresh random reference binds a complete JSON fragment to an owner-selected
item. Matching a marker alone, similar text, or a budget count is insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import uuid

OWNERS = frozenset({'semantic', 'episodic', 'reflection', 'skill', 'document'})


def safe_json(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'))
            .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))


@dataclass
class ContextReference:
    owner: str
    source_id: str = field(repr=False)
    text: str = field(repr=False)
    reference: str = field(default_factory=lambda: uuid.uuid4().hex)
    selected: bool = False

    def fragment(self):
        return safe_json({'context_ref': self.reference, 'owner': self.owner, 'text': self.text})

    def receipt(self, state):
        # Source IDs can be arbitrary server-supplied paths/names. Opaque stable
        # owner refs correlate them without echoing secrets into receipt fields.
        value = {'reference': self.reference, 'owner': self.owner,
                 'record_ref': hashlib.sha256((self.owner + '\0' + self.source_id).encode()).hexdigest(),
                 'state': state}
        if self.owner == 'semantic' and re.fullmatch(r'clm_[0-9a-f]{12}', self.source_id):
            value['claim_id'] = self.source_id
        if self.owner == 'episodic' and re.fullmatch(r'evt-[0-9a-f]{12}', self.source_id):
            value['event_id'] = self.source_id
        document = re.fullmatch(r'(doc_[0-9a-f]{32}):([1-9][0-9]{0,8})', self.source_id) if self.owner == 'document' else None
        if document:
            value.update(document_id=document.group(1), document_revision=int(document.group(2)))
        return value


def observe_references(payload, references):
    """Inspect supported textual fields, excluding reasoning, blobs and headers.

    Exact JSON escaping used by CLI prompt formatters is recognized; arbitrary
    adapter rewriting is unobservable, never fabricated as admitted context.
    A missing complete fragment means not retained *verbatim*, not forgotten.
    """
    texts = []
    supported = False
    limited = False
    def text_blocks(value):
        nonlocal limited
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            limited |= len(value) > 2048
            for part in value[:2048]:
                if isinstance(part, dict) and part.get('type') in ('text', 'input_text', 'output_text') and isinstance(part.get('text'), str):
                    texts.append(part['text'])
    if isinstance(payload, dict):
        if isinstance(payload.get('messages'), list):
            supported = True
            text_blocks(payload.get('system'))
            limited |= len(payload['messages']) > 2048
            for row in payload['messages'][:2048]:
                if isinstance(row, dict):
                    text_blocks(row.get('content'))
        elif isinstance(payload.get('prompt'), str):
            supported = True
            texts.append(payload['prompt'])
    receipts = []
    for ref in references[:128]:
        if not isinstance(ref, ContextReference) or ref.owner not in OWNERS:
            continue
        state = 'budget_dropped'
        if ref.selected:
            if not supported:
                state = 'unobservable'
            else:
                fragment = ref.fragment()
                variants = (fragment, json.dumps(fragment, ensure_ascii=True)[1:-1], json.dumps(fragment, ensure_ascii=False)[1:-1])
                found = any(variant in text for variant in variants for text in texts)
                state = 'retained_exact' if found else 'unobservable' if limited else 'not_retained_exact'
        receipts.append(ref.receipt(state))
    return receipts
