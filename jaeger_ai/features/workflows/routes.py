"""Workflow controls; storage remains Library and execution remains TaskOwner."""
from __future__ import annotations
import json
from aiohttp import web
from jaeger_ai.contract.workflows import WORKFLOW_FORMAT, WORKFLOW_MAX_BYTES, WORKFLOW_MAX_STEPS, WORKFLOW_COLLECTION_ID
from jaeger_ai.features.knowledge_library.managed import DocumentConflict
from .definitions import goal, read as read_workflow, validate


def register(gateway):
    def use(operation):
        from jaeger_ai.features.knowledge_library.tools import _library
        library = _library()
        try:
            return operation(library)
        finally:
            library.close()

    async def read(request):
        try:
            document_id = request.match_info.get('id')
            if document_id:
                return web.json_response(use(lambda lib: read_workflow(lib, document_id)))
            def listing(lib):
                items = []
                for row in lib.conn.execute('SELECT d.id,d.title,m.revision,m.archived FROM library_documents d JOIN library_managed_documents m ON m.document_id=d.id WHERE d.collection_id=? ORDER BY d.modified_at DESC', (WORKFLOW_COLLECTION_ID,)):
                    items.append({**dict(row), 'archived': bool(row['archived'])})
                return items
            return web.json_response({'workflows': use(listing), 'format': WORKFLOW_FORMAT, 'limits': {'steps': WORKFLOW_MAX_STEPS, 'bytes': WORKFLOW_MAX_BYTES}})
        except KeyError:
            return web.json_response({'error': 'Workflow not found'}, status=404)
        except ValueError as exc:
            return web.json_response({'error': str(exc), 'hint': 'Original definition is preserved in Library'}, status=409)
        except (RuntimeError, OSError):
            return web.json_response({'error': 'Instance Library unavailable'}, status=503)

    async def mutate(request):
        action = request.match_info.get('action', 'create')
        if action not in {'create', 'save', 'archive', 'restore', 'propose'}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            fields = {'operation_id'} | ({'definition'} if action == 'create' else {'expected_revision'})
            if action == 'save': fields.add('definition')
            if action == 'propose': fields.add('session_id')
            if not isinstance(body, dict) or set(body) != fields:
                raise ValueError('Unexpected or missing workflow fields')
            oid = body['operation_id']
            if not isinstance(oid, str) or not oid.strip() or len(oid) > 128:
                raise ValueError('Stable operation_id required')
            document_id = request.match_info.get('id', '')
            if not gateway.store.reserve_control_operation(oid, {'action': 'workflow.' + action, 'id': document_id, 'body': body}):
                previous = gateway.store.control_operation(oid)['receipt']
                return web.json_response(previous or {'operation_id': oid, 'execution_unknown': True, 'error': 'Workflow outcome unknown; check the saved operation, do not replay'}, status=previous.get('http_status', 200) if previous else 409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        try:
            def apply(lib):
                if action == 'create':
                    definition = validate(body['definition'])
                    row = lib.create_document(title=definition['name'], content=json.dumps(definition, ensure_ascii=False), command_id=oid, collection_id=WORKFLOW_COLLECTION_ID)
                    return read_workflow(lib, row['id'])
                current = read_workflow(lib, document_id)
                if type(body['expected_revision']) is not int or body['expected_revision'] != current['revision']:
                    raise DocumentConflict('Workflow changed; reload before continuing')
                if action == 'save':
                    definition = validate(body['definition'])
                    lib.save_document(document_id, title=definition['name'], content=json.dumps(definition, ensure_ascii=False), expected_revision=current['revision'])
                elif action in {'archive', 'restore'}:
                    lib.archive_document(document_id, archived=action == 'archive', expected_revision=current['revision'])
                elif current['archived']:
                    raise DocumentConflict('Restore workflow before proposing a run')
                return read_workflow(lib, document_id)
            workflow = use(apply)
            task = None
            if action == 'propose':
                if gateway._current_tier() == 'chat':
                    raise ValueError('Workflow task proposals are unavailable in Chat mode')
                parent = gateway.store.get_session(body['session_id'])
                if parent is None:
                    raise ValueError('Existing originating conversation required')
                metadata = parent.get('metadata') or {}
                execution = {'workspace': parent.get('workspace') or '', 'caller': request.get('caller_actor'), 'model': metadata.get('model'), 'provider': metadata.get('provider')}
                task = gateway.task_owner.submit(goal(workflow), context={'session_id': parent['session_id'], 'source': 'client', 'request_id': oid, 'execution': execution, 'agent_id': gateway._session_agent_id(parent)}, proposal=True, key='workflow:' + oid)
                gateway.task_owner.store.update_task(task['task_id'], lambda row: row.provenance.update(workflow_id=workflow['id'], workflow_revision=workflow['revision'], workflow_digest=workflow['digest']))
            receipt = {'ok': True, 'operation_id': oid, 'http_status': 200, 'workflow': workflow, 'task': task}
        except DocumentConflict as exc:
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 409, 'error': str(exc)}
        except KeyError:
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 404, 'error': 'Workflow not found'}
        except (ValueError, TypeError) as exc:
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 400, 'error': str(exc)}
        except Exception:
            return web.json_response({'operation_id': oid, 'execution_unknown': True, 'error': 'Workflow outcome unknown; read current state without retry'}, status=503)
        gateway.store.finish_control_operation(oid, receipt)
        if receipt['ok']:
            gateway.event_bus.publish('*', 'workflow.changed', {'id': workflow['id'], 'revision': workflow['revision'], 'action': action})
        return web.json_response(receipt, status=receipt['http_status'])

    gateway.app.router.add_get('/v1/workflows', read)
    gateway.app.router.add_get('/v1/workflows/{id}', read)
    gateway.app.router.add_post('/v1/workflows', mutate)
    gateway.app.router.add_post('/v1/workflows/{id}/{action}', mutate)
