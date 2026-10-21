"""Operator task presentation over existing Gateway metadata and command receipts.

Not execution state. No worker/task JSON/configuration is rewritten. One local
operator scope, matching current authenticated admin controls, not invented teams.
"""
from __future__ import annotations
import json
import math
import time
import uuid
from jaeger_ai.core.gateway.session_store import input_fingerprint

ACTIONS = {'pin','unpin','mark_read','mark_unread','todo_done','todo_open'}


def _read(conn, task_id, updated_at):
    row=conn.execute('SELECT value FROM schema_meta WHERE key=?',('task-presentation:'+task_id,)).fetchone()
    value=json.loads(row[0]) if row else {'revision':0,'pinned':False,'todo_done':False,'read_updated_at':0.,'unread_override':False}
    return {**value,'unread':bool(value['unread_override'] or updated_at>value['read_updated_at'])}


def view(gateway, task):
    with gateway.store._get_conn() as conn:
        return {**task.to_dict(),'presentation':_read(conn,task.task_id,task.updated_at)}


def operation(gateway, task_id, oid, actor):
    row=gateway.store.control_operation(oid)
    receipt=row.get('receipt') if row else None
    if not receipt or receipt.get('scope')!='task_presentation' or receipt.get('task_id')!=task_id or receipt.get('actor')!=actor:
        raise KeyError('Task presentation operation not found')
    return row


def change(gateway,task_id,body,actor):
    if not isinstance(body,dict) or set(body)!={'operation_id','action','expected_revision','expected_updated_at'}:
        raise ValueError('Exact task presentation command required')
    oid=body['operation_id']
    try:
        if not isinstance(oid,str) or len(oid)>36:raise ValueError()
        uuid.UUID(oid)
    except (ValueError,AttributeError):raise ValueError('Valid operation identity required') from None
    action=body['action'];revision=body['expected_revision'];stamp=body['expected_updated_at']
    if not isinstance(action,str) or action not in ACTIONS:raise ValueError('Unsupported task presentation action')
    if type(revision) is not int or revision<0 or type(stamp) not in (int,float) or not math.isfinite(stamp):raise ValueError('Valid task and presentation revisions required')
    fingerprint=input_fingerprint(json.dumps({'scope':'task_presentation','actor':actor,'task_id':task_id,'body':body},sort_keys=True))
    with gateway.store._immediate() as conn:
        old=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(oid,)).fetchone()
        if old:
            if old['fingerprint']!=fingerprint:raise ValueError('Operation identity belongs to another command')
            if old['receipt_json'] is None:raise ValueError('Previous operation is unknown; inspect only')
            return json.loads(old['receipt_json'])
        task=conn.execute('SELECT updated_at FROM durable_tasks WHERE task_id=?',(task_id,)).fetchone()
        if task is None:raise KeyError(task_id)
        current=_read(conn,task_id,task['updated_at'])
        ok=revision==current['revision'] and stamp==task['updated_at']
        receipt={'ok':ok,'scope':'task_presentation','actor':actor,'task_id':task_id,'operation_id':oid,'action':action,'http_status':200 if ok else 409}
        if ok:
            value={key:val for key,val in current.items() if key!='unread'}
            if action in {'pin','unpin'}:value['pinned']=action=='pin'
            elif action in {'todo_done','todo_open'}:value['todo_done']=action=='todo_done'
            elif action=='mark_unread':value['unread_override']=True
            else:value.update(read_updated_at=stamp,unread_override=False)
            value['revision']+=1
            conn.execute('INSERT INTO schema_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('task-presentation:'+task_id,json.dumps(value)))
            receipt['presentation']=_read(conn,task_id,task['updated_at'])
        else:receipt['error']='Task or presentation changed; refresh this task and review'
        # Configuration and known outcome commit together. No uncertain execution replay.
        conn.execute("INSERT INTO control_operations VALUES (?,?,'completed',?,?)",(oid,fingerprint,json.dumps(receipt),time.time()))
    return receipt
