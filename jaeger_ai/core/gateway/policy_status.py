"""Owner-only passive view of policy sources bound to the current resident."""
from aiohttp import web


def register(gateway):
    async def read(request):
        caller = request.get('caller')
        if caller is None or caller.session_prefix or 'admin' not in caller.scopes or not request.get('caller_actor', '').startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        from jaeger_ai.core.authority.status import snapshot
        from jaeger_ai.core.entity.runtime import EntityRuntime
        # Never get_singleton(): status cannot start/bind a resident or new store.
        runtime = EntityRuntime._instance
        return web.json_response(snapshot(getattr(runtime, 'layout', None)))
    gateway.app.router.add_get('/v1/runtime/policy-sources', read)
