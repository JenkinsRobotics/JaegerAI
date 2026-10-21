"""Real isolated HTTP/SQLite presentation; never substitutes checklist for execution."""
import json
import uuid
import pytest
from unittest.mock import Mock
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.tasks.models import DurableTask,TaskState


@pytest.mark.asyncio
async def test_task_presentation_atomic_replay_conflict_scope_and_worker_preservation(tmp_path,monkeypatch):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    # These fixtures deliberately do not execute; only their presentation is mutable.
    monkeypatch.setattr(gateway.task_owner,'start',Mock())
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        tasks=[]
        for i,state in enumerate((TaskState.QUEUED,TaskState.BLOCKED,TaskState.FAILED,TaskState.COMPLETED_VERIFIED)):
            task=DurableTask(task_id=f'owned-task-{i}',owning_agent='fixture',goal='fixture',state=state,error='retained fixture failure' if state==TaskState.FAILED else None,provenance={'session_id':'owned-parent','request_id':'owned-request','authorized':False})
            gateway.task_owner.store.save_task(task);tasks.append(task)
        task=tasks[2];before=task.to_dict();path=f'/v1/tasks/{task.task_id}'
        row=await (await http.get(path)).json();assert row['presentation']['unread']
        def body(action,rev,stamp=task.updated_at):return {'operation_id':uuid.uuid4().hex,'action':action,'expected_revision':rev,'expected_updated_at':stamp}
        pin=body('pin',0)
        first=await (await http.post(path+'/presentation',json=pin)).json()
        assert first['ok'] and first['presentation']['revision']==1
        assert await (await http.post(path+'/presentation',json=pin)).json()==first
        todo=body('todo_done',1)
        assert (await (await http.post(path+'/presentation',json=todo)).json())['presentation']['todo_done']
        # Replay pin must not undo the later checklist metadata.
        assert await (await http.post(path+'/presentation',json=pin)).json()==first
        assert (await http.post(path+'/presentation',json=body('unpin',0))).status==409
        assert (await http.post(path+'/presentation',json={**pin,'action':'todo_open'})).status==409
        assert (await http.post(path+'/presentation',json=body('unpin',2),headers=client_headers('jaegerd'))).status==403
        assert (await http.get(path,headers=client_headers('a2a'))).status==403
        assert (await http.post('/v1/tasks/missing/presentation',json=body('pin',0))).status==404
        assert (await http.get('/v1/tasks/other/presentation-operations/'+pin['operation_id'])).status==404
        assert (await http.get(path+'/presentation-operations/'+pin['operation_id'],headers=client_headers('jaegerd'))).status==404
        assert (await (await http.get(path+'/presentation-operations/'+pin['operation_id'])).json())['receipt']==first
        assert gateway.task_owner.store.get_task(task.task_id).to_dict()==before
        # A stale worker save cannot overwrite presentation in separate owner metadata.
        task.goal='updated by existing worker';gateway.task_owner.store.save_task(task)
        current=await (await http.get(path)).json()
        assert current['presentation']['pinned'] and current['presentation']['todo_done'] and current['error']==before['error']
        # Read of a stale snapshot cannot clear genuinely newer work.
        assert (await http.post(path+'/presentation',json=body('mark_read',2))).status==409
        read=body('mark_read',2,current['updated_at'])
        assert not (await (await http.post(path+'/presentation',json=read)).json())['presentation']['unread']
        gateway.task_owner.store.update_task(task.task_id,lambda t:setattr(t,'result',{'fixture':'new result'}))
        later=await (await http.get(path)).json();assert later['presentation']['unread']
        tasks_json=await (await http.get('/v1/tasks')).json()
        assert {t['state'] for t in tasks_json['tasks']}=={'queued','blocked','failed','completed_verified'}
        # Reopen the actual receipt owner; no repeated operation, task or history mutation.
        gateway.store=GatewaySessionStore(gateway.store.path)
        assert await (await http.post(path+'/presentation',json=read)).json()==(await (await http.get(path+'/presentation-operations/'+read['operation_id'])).json())['receipt']
        assert (await (await http.get(path)).json())['presentation']['unread']
        assert 'fixture failure' in json.dumps(await (await http.get(path)).json())
