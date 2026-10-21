"""Opt-in bounded transport diagnostics; existing Gateway auth and process owner."""
from aiohttp import web
from jaeger_ai.core.diagnostics.transport import TransportDiagnostics


def register(gateway):
    owner=TransportDiagnostics()
    async def read(request):return web.json_response(owner.snapshot())
    async def export(request):
        # Allowlisted fixed labels/counts/hashed references only, never durable
        # transcript/session metadata, exceptions, paths, headers or raw traces.
        return web.json_response({'format':'jaeger-transport-diagnostics-v1',**owner.snapshot()},headers={'Content-Disposition':'attachment; filename="jaeger-diagnostics.json"'})
    async def change(request):
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('Diagnostic command must be an object')
            action=request.match_info['action']
            if action=='start' and set(body)=={'operation_id','duration_seconds'}:
                return web.json_response(owner.start(body['operation_id'],body['duration_seconds']))
            if action=='stop' and set(body)=={'capture_id'}:
                return web.json_response(owner.stop(body['capture_id']))
            if action=='report' and {'capture_id','event_id','code'}<=set(body)<= {'capture_id','event_id','code','session_id','request_id'}:
                sid,rid=body.get('session_id'),body.get('request_id')
                if sid is not None and (not isinstance(sid,str) or gateway.store.get_session(sid) is None):raise ValueError('Diagnostic conversation is not retained')
                if rid is not None:
                    row=gateway.store.get_request(rid) if isinstance(rid,str) else None
                    if row is None or not sid or row['session_id']!=sid:raise ValueError('Diagnostic request is outside conversation scope')
                return web.json_response(owner.report(body['capture_id'],body['event_id'],body['code'],session_id=sid,request_id=rid))
            raise ValueError('Unsupported diagnostic fields/action; raw payloads are refused')
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
    gateway.app.router.add_get('/v1/runtime/diagnostics/capture',read)
    gateway.app.router.add_get('/v1/runtime/diagnostics/export',export)
    gateway.app.router.add_post('/v1/runtime/diagnostics/capture/{action}',change)
