"""Operator controls and read-only view of the resident entity's existing semantic memory owner."""
from __future__ import annotations
import asyncio
from aiohttp import web


def register(gateway):
    async def read(request):
        from jaeger_ai.core.entity.runtime import EntityRuntime
        runtime=EntityRuntime._instance  # Never create another entity/runtime merely to inspect memory.
        semantic=getattr(getattr(runtime,'memory_subsystem',None),'semantic',None)
        owner=getattr(semantic,'world_store',None)
        if owner is None:return web.json_response({'available':False,'claims':[],'next_before':None,'scope':'loaded_entity_semantic_owner'})
        try:
            raw=request.query.get('before');before=int(raw) if raw else None
            inactive=request.query.get('include_inactive','false')
            if inactive not in {'true','false'}:raise ValueError('Invalid inactive filter')
            result=await asyncio.to_thread(owner.search_claims,request.query.get('q',''),before=before,include_inactive=inactive=='true')
            return web.json_response({'available':True,'scope':'loaded_entity_semantic_owner',**result})
        except (ValueError,TypeError):return web.json_response({'error':'Invalid semantic memory query/filter/cursor'},status=400)
        except Exception:return web.json_response({'error':'Loaded semantic memory unavailable; original state preserved'},status=503)
    def loaded_owner(*, writing=False):
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_ai.core.entity.ownership import EntityRuntimeMode
        runtime=EntityRuntime._instance
        owner=getattr(getattr(getattr(runtime,'memory_subsystem',None),'semantic',None),'world_store',None)
        if owner is None or writing and (getattr(runtime,'mode',None)!=EntityRuntimeMode.OWNER or not getattr(runtime,'is_resident',False)):
            raise ValueError('Resident semantic owner unavailable; no runtime was started')
        return owner
    def admin(request):
        caller=request.get('caller')
        return caller is not None and 'admin' in caller.scopes and caller.session_prefix is None
    async def detail(request):
        try:
            result=await asyncio.to_thread(loaded_owner().claim_detail,request.match_info['id'])
            try:loaded_owner(writing=True);editable=admin(request)
            except ValueError:editable=False
            if not editable:result['actions']=[]
            return web.json_response(result)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=409)
    async def operation(request):
        try:
            stored=gateway.store.control_operation(request.match_info['id'])
            candidate=stored.get('receipt') if stored else None
            receipt=candidate if candidate and (candidate.get('domain')=='semantic_claim' or (candidate.get('result') or {}).get('domain')=='semantic_claim') else None
            if receipt is None:receipt=await asyncio.to_thread(loaded_owner().claim_operation,request.match_info['id'])
            return web.json_response({'receipt':receipt})
        except ValueError as exc:return web.json_response({'error':str(exc)},status=400)
    async def mutate(request):
        if not admin(request):return web.json_response({'error':'Existing owner admin scope required'},status=403)
        action=request.match_info['action']
        if action not in {'correct','forget','restore'}:raise web.HTTPNotFound()
        try:
            body=await request.json()
            fields={'operation_id','expected_revision'}|({'text'} if action=='correct' else set())
            if not isinstance(body,dict) or set(body)!=fields:raise ValueError('Invalid claim command fields')
            oid=body['operation_id']
            owner=loaded_owner(writing=True)
            owner._claim_operation_id(oid)
            if not isinstance(body['expected_revision'],str) or len(body['expected_revision'])!=64:raise ValueError('Current claim revision required')
            command={'domain':'semantic_claim','id':request.match_info['id'],'action':action,'actor':request['caller_actor'],'body':body}
            if not gateway.store.reserve_control_operation(oid,command):
                receipt=owner.claim_operation(oid) or gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'execution_unknown':True,'operation_id':oid,'error':'Original outcome unresolved; inspect receipt without replay'},status=receipt.get('http_status',200) if receipt else 409)
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=400)
        try:
            from .server import _control_plane_block
            if _control_plane_block():raise ValueError('Global Stop or live-owner guard prevents memory changes')
            receipt=await asyncio.to_thread(owner.manage_claim,request.match_info['id'],action,expected_revision=body['expected_revision'],operation_id=oid,actor=request['caller_actor'],text=body.get('text'))
        except ValueError as exc:receipt={'ok':False,'domain':'semantic_claim','operation_id':oid,'http_status':409,'error':str(exc)}
        except Exception:return web.json_response({'execution_unknown':True,'operation_id':oid,'error':'Claim outcome unknown; inspect saved receipt without replay'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_get('/v1/runtime/memory/claims',read)
    gateway.app.router.add_get('/v1/runtime/memory/claims/{id}',detail)
    gateway.app.router.add_post('/v1/runtime/memory/claims/{id}/{action}',mutate)
    gateway.app.router.add_get('/v1/runtime/memory/claim-operations/{id}',operation)
