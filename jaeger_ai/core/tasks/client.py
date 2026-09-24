"""Background task client for CLI/TUI surfaces. Only the Gateway executes work."""
from __future__ import annotations
import json
import uuid
from jaeger_ai.core.gateway.client import GatewayTurnClient


def request(method, path, body=None):
    return GatewayTurnClient()._call(method, path, body)


def submit(goal, *, session_id='deepthink', workspace='', proposal=False, request_id=None):
    request('POST', '/v1/sessions', {'session_id':session_id, 'title':'Background work',
                                    'workspace':workspace, 'source':'cli'})
    return request('POST','/v1/tasks', {'goal':goal, 'session_id':session_id,
                                       'execution':{'workspace':workspace}, 'proposal':proposal,
                                       'request_id':request_id or uuid.uuid4().hex})


def tasks():
    return request('GET','/v1/tasks')['tasks']


def approve(task_id):
    return request('POST',f'/v1/tasks/{task_id}/approve',{})


def cancel(task_id):
    return request('POST',f'/v1/tasks/{task_id}/cancel',{})
