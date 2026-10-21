"""Read-only view of the resident entity's existing semantic memory owner."""
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
    gateway.app.router.add_get('/v1/runtime/memory/claims',read)
