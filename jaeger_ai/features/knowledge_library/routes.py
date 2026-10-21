"""Authenticated client access to the existing library owner. No filesystem grants."""
from __future__ import annotations
import hashlib
import json
import time
from aiohttp import web
from .managed import DocumentConflict
from jaeger_ai.contract.knowledge import DOCUMENT_WRITE_WINDOW_SECONDS, MANAGED_DOCUMENT_MAX_BYTES
from .store import LibraryError


def register(gateway):
    def use(operation):
        from .tools import _library
        library = _library()
        try:
            return operation(library)
        finally:
            library.close()

    async def read(request):
        document_id = request.match_info.get('document_id')
        try:
            if request.path.endswith('/export'):
                raw_revision = request.query.get('revision', '')
                if not 1 <= len(raw_revision) <= 16 or not raw_revision.isascii() or not raw_revision.isdecimal():
                    return web.json_response({'error': 'Reviewed saved revision required'}, status=400)
                return web.json_response(use(lambda lib: lib.export_document(document_id, expected_revision=int(raw_revision), expected_digest=request.query.get('digest', ''))))
            if request.path.endswith('/versions'):

                return web.json_response({'versions': use(lambda lib: lib.document_versions(document_id))})
            if document_id:
                def document(lib):
                    try:
                        return {**lib.managed_document(document_id), 'editable': True}
                    except KeyError:
                        return {**lib.read(document_id), 'editable': False}
                return web.json_response(use(document))
            if request.path.endswith('/search'):
                query = request.query.get('q', '')[:1000]
                return web.json_response({'results': use(lambda lib: lib.search(query))})
            return web.json_response(use(lambda lib: {'collections': lib.list(), 'documents': lib.managed_documents(include_archived=True), 'limits': {'document_bytes': MANAGED_DOCUMENT_MAX_BYTES}, 'write_policy': {'kind': 'revision_cas_and_server_write_window', 'seconds': DOCUMENT_WRITE_WINDOW_SECONDS, 'exclusive_editor_lock': False}, 'sharing': {'scope': 'single_local_operator', 'manual_export': True, 'recipient_grants': False, 'public_links': False, 'reason': 'No cross-account principal or recipient-access authority is configured; export does not grant Library access.'}}))
        except DocumentConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (LibraryError, KeyError):
            return web.json_response({'error': 'Document not found'}, status=404)
        except (RuntimeError, OSError) as exc:
            return web.json_response({'error': str(exc)}, status=503)

    async def mutate(request):
        write_deadline = time.monotonic() + DOCUMENT_WRITE_WINDOW_SECONDS
        action = request.match_info.get('action', 'create')
        if action not in {'create', 'save', 'archive', 'restore', 'version'}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            fields = {'operation_id', 'title', 'content'} if action == 'create' else {'operation_id', 'expected_revision'} | ({'title', 'content'} if action == 'save' else {'revision'} if action == 'version' else set())
            if not isinstance(body, dict) or set(body) != fields:
                raise ValueError('Unexpected or missing document fields')
            oid = body['operation_id']
            if not isinstance(oid, str) or not oid.strip() or len(oid) > 128:
                raise ValueError('Stable operation_id required')
            document_id = request.match_info.get('document_id', '')
            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            if not gateway.store.reserve_control_operation(oid, {'action': 'library.' + action, 'document_id': document_id, 'fingerprint': fingerprint}):
                previous = gateway.store.control_operation(oid)
                receipt = previous['receipt']
                return web.json_response(receipt or {'operation_id': oid, 'error': 'Previous document action outcome is unknown; do not replay'}, status=receipt.get('http_status', 200) if receipt else 409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        try:
            def apply(lib):
                if action == 'create':
                    return lib.create_document(title=body['title'], content=body['content'], command_id=oid)
                if action == 'save':
                    return lib.save_document(document_id, title=body['title'], content=body['content'], expected_revision=body['expected_revision'], write_deadline=write_deadline)
                if action == 'version':
                    return lib.restore_document_version(document_id, revision=body['revision'], expected_revision=body['expected_revision'], write_deadline=write_deadline)
                return lib.archive_document(document_id, archived=action == 'archive', expected_revision=body['expected_revision'], write_deadline=write_deadline)
            result = use(apply)
            receipt = {'ok': True, 'operation_id': oid, 'http_status': 200, 'document': {k: result[k] for k in ('id', 'revision', 'digest', 'archived')}}
        except DocumentConflict as exc:
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 409, 'error': str(exc)}
        except (KeyError, LibraryError):
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 404, 'error': 'Managed document not found'}
        except (ValueError, TypeError) as exc:
            receipt = {'ok': False, 'operation_id': oid, 'http_status': 400, 'error': str(exc)}
        except Exception:
            return web.json_response({'operation_id': oid, 'execution_unknown': True, 'error': 'Document outcome unknown; check saved operation, do not replay'}, status=503)
        gateway.store.finish_control_operation(oid, receipt)
        if receipt['ok']:
            gateway.event_bus.publish('*', 'library.document.updated', receipt['document'])
        return web.json_response(receipt, status=receipt['http_status'])

    async def artifacts(request):
        from jaeger_ai.core.tasks.artifacts import catalog
        return web.json_response({'artifacts': catalog(gateway, request.query.get('task_id'), request.query.get('session_id')), 'max_bytes': gateway.UPLOAD_MAX_BYTES})

    async def artifact(request):
        from jaeger_ai.core.tasks.artifacts import read as read_artifact
        return await read_artifact(gateway, request)

    gateway.app.router.add_get('/v1/library/artifacts', artifacts)
    gateway.app.router.add_get('/v1/library/artifacts/{task_id}/{artifact_id}', artifact)
    gateway.app.router.add_get('/v1/library', read)
    gateway.app.router.add_get('/v1/library/search', read)
    gateway.app.router.add_get('/v1/library/documents/{document_id}', read)
    gateway.app.router.add_get('/v1/library/documents/{document_id}/versions', read)
    gateway.app.router.add_get('/v1/library/documents/{document_id}/export', read)
    gateway.app.router.add_post('/v1/library/documents', mutate)
    gateway.app.router.add_post('/v1/library/documents/{document_id}/{action}', mutate)
