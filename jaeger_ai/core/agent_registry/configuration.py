"""Original, permission-neutral specialist presets and validated prompt settings.

Registry metadata owns these settings; presentation names/pins/primary stay in
Gateway presentation storage. Presets never inherit tools, credentials or roles.
"""
from __future__ import annotations
from typing import Any

TEMPLATES = (
    {"id": "research-assistant", "version": 1, "name": "Research assistant", "specialty": "research", "summary": "Organize questions, evaluate supplied evidence and identify uncertainty.", "instructions": "Separate evidence from inference. Cite supplied sources where available. Never invent research or claim a tool was used."},
    {"id": "planning-assistant", "version": 1, "name": "Planning assistant", "specialty": "planning", "summary": "Turn a goal into a bounded plan with dependencies and checks.", "instructions": "Clarify the intended result, break it into concrete steps, and identify decisions requiring the operator. A plan is not evidence of execution."},
    {"id": "writing-assistant", "version": 1, "name": "Writing assistant", "specialty": "writing", "summary": "Draft and revise clear text from the operator's supplied material.", "instructions": "Preserve the author's intent. Mark missing facts and avoid invented quotes or references. Return the requested draft directly."},
)


def validate_settings(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"specialty", "summary", "instructions"}:
        raise ValueError("Only specialty, summary and instructions are editable")
    result = {}
    for key, limit in (("specialty", 200), ("summary", 2000), ("instructions", 12000)):
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise ValueError(f"{key} must be text of at most {limit} characters without control codes")
        result[key] = text.strip()
    return result


def editable(record: Any) -> bool:
    from .specialists import STANDING_SPECIALISTS
    return bool(record and record.kind.value == 'jaeger_native' and record.role.value == 'specialist'
                and record.source == 'registry' and not record.metadata.get('internal')
                and record.name not in {s['name'] for s in STANDING_SPECIALISTS})


def settings(record: Any) -> dict[str, Any]:
    meta = record.metadata or {}
    return {"agent_id": record.id, "revision": int(meta.get('configuration_revision', 0)),
            **{key: str(meta.get('operator_instructions' if key == 'instructions' else key) or '') for key in ('specialty', 'summary', 'instructions')},
            "template": meta.get('template')}
