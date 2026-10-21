"""Read-only projection of send_message effects from the existing loaded ledger."""
from __future__ import annotations
import hashlib
import json
import sys
from jaeger_ai.core.redaction import redact_text


def listing(*,before=None):
    module=sys.modules.get('jaeger_agent.memory.sqlite_store')
    if module is None or module.db_path() is None:
        return {'initialized':False,'deliveries':[],'next_before':None,'scope':'loaded_entity_effect_ledger_only'}
    clauses=["action='send_message'"];params=[]
    if before is not None:
        if type(before) is not int or before<=0:raise ValueError('Positive delivery cursor required')
        clauses.append('rowid<?');params.append(before)
    rows=module.connection().execute('SELECT rowid AS cursor,key,run_id,status,result_json,claimed_at,completed_at FROM effects WHERE '+' AND '.join(clauses)+' ORDER BY rowid DESC LIMIT 51',params).fetchall()
    result=[]
    for row in rows[:50]:
        try:receipt=json.loads(row['result_json'] or '{}')
        except (ValueError,TypeError):receipt={}
        if not isinstance(receipt,dict):receipt={}
        state='outcome_unknown' if row['status']=='pending' else 'transport_accepted' if receipt.get('sent') is True else 'not_started' if receipt.get('effect')=='not_started' else 'recorded_failure_unclassified'
        item={'id':hashlib.sha256(row['key'].encode()).hexdigest()[:32],'run_id':redact_text(str(row['run_id'] or ''))[:200],
              'state':state,'claimed_at':row['claimed_at'],'completed_at':row['completed_at'],'delivery_verified':False,'message_ids':[]}
        if isinstance(receipt.get('message_ids'),list):item['message_ids']=[redact_text(str(v))[:200] for v in receipt['message_ids'][:100] if isinstance(v,(str,int)) and not isinstance(v,bool)]
        if isinstance(receipt.get('message_id'),(str,int)):item['message_id']=redact_text(str(receipt['message_id']))[:200]
        for key in ('reply_to_message_id','session_id','request_id'):
            if isinstance(receipt.get(key),(str,int)) and not isinstance(receipt.get(key),bool):item[key]=redact_text(str(receipt[key]))[:200]
        result.append(item)
    return {'initialized':True,'deliveries':result,'next_before':rows[49]['cursor'] if len(rows)>50 else None,'scope':'loaded_entity_effect_ledger_only'}
