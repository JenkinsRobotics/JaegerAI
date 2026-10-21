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


def export_template(record: Any, expected_revision: int) -> dict[str,Any]:
    """Explicit owner-local prompt snapshot; no history/tools/accounts/metadata copy."""
    import hashlib
    import json

    from jaeger_ai.core.redaction import redact_text
    if not editable(record):raise PermissionError('Protected definitions cannot be exported as owner templates')
    current=settings(record)
    if type(expected_revision) is not int or expected_revision!=current['revision']:raise RuntimeError('Source configuration changed; review current settings')
    prompt=validate_settings({key:current[key] for key in ('specialty','summary','instructions')})
    payload={'format':'jaeger.specialist-template','schema_version':1,'version':current['revision']+1,
             'visibility':'owner_local','export_policy':'prompt_only_no_grants',
             'source_bot':{'agent_id':record.id,'configuration_revision':current['revision']},
             'settings':prompt,'tools_granted':False,'credentials_included':False,'history_included':False}
    content=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if redact_text(content)!=content:raise ValueError('Potential secret content requires owner review; export refused')
    return {'agent_id':record.id,'revision':current['revision'],'content':content,
            'sha256':hashlib.sha256(content.encode()).hexdigest(),'filename':'jaeger-specialist-template.json',
            'visibility':'owner_local','export_policy':'prompt_only_no_grants'}


def import_template(content: Any) -> dict[str,Any]:
    """Validate an owner-provided local prompt snapshot; provenance is unverified."""
    import hashlib
    import json

    from jaeger_ai.core.redaction import redact_text
    if not isinstance(content,str) or len(content)>100000:raise ValueError('Bounded local template JSON required')
    value=json.loads(content)
    fields={'format','schema_version','version','visibility','export_policy','source_bot','settings','tools_granted','credentials_included','history_included'}
    if not isinstance(value,dict) or set(value)!=fields or value['format']!='jaeger.specialist-template' or type(value['schema_version']) is not int or value['schema_version']!=1 or value['visibility']!='owner_local' or value['export_policy']!='prompt_only_no_grants' or any(value[key] is not False for key in ('tools_granted','credentials_included','history_included')):
        raise ValueError('Only owner-local prompt-only templates without private fields or grants are supported')
    source=value['source_bot']
    if not isinstance(source,dict) or set(source)!={'agent_id','configuration_revision'} or not isinstance(source['agent_id'],str) or not 1<=len(source['agent_id'])<=200 or any(ord(c)<32 for c in source['agent_id']) or type(source['configuration_revision']) is not int or source['configuration_revision']<0 or type(value['version']) is not int or value['version']!=source['configuration_revision']+1:
        raise ValueError('Invalid template source/version linkage')
    prompt=validate_settings(value['settings'])
    if redact_text(content)!=content:raise ValueError('Potential secret content requires review; template refused')
    return {**prompt,'template':{'id':'local:'+hashlib.sha256(content.encode()).hexdigest(),'version':value['version'],
            'source_bot':source,'visibility':'owner_local','export_policy':'prompt_only_no_grants','provenance':'owner_provided_unverified'}}


def template_catalog(record: Any) -> dict[str,Any]:
    """Validate retained immutable snapshots before catalog selection or mutation."""
    import hashlib
    value=record.metadata.get('template_catalog',{'revision':0,'hidden':False,'versions':[]})
    if not isinstance(value,dict) or set(value)!={'revision','hidden','versions'} or type(value['revision']) is not int or value['revision']<0 or type(value['hidden']) is not bool or not isinstance(value['versions'],list) or len(value['versions'])>100:
        raise ValueError('Saved template metadata invalid; retained without replacement')
    seen=set()
    for row in value['versions']:
        if not isinstance(row,dict) or set(row)!={'version','content','sha256'} or not isinstance(row['content'],str):raise ValueError('Invalid retained template version')
        parsed=import_template(row['content']);source=parsed['template']['source_bot']
        if row['sha256']!=hashlib.sha256(row['content'].encode()).hexdigest() or type(row['version']) is not int or row['version']!=parsed['template']['version'] or source['agent_id']!=record.id or row['version'] in seen:raise ValueError('Retained template identity/version mismatch')
        seen.add(row['version'])
    return value
