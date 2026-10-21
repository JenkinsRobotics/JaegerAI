"""Authenticated operator subscription controls, not an ingress/test-send API."""
from aiohttp import web

from . import owner


def register(gateway):
    async def listing(request):
        return web.json_response(owner.catalog(gateway))

    async def history(request):
        try:
            return web.json_response(owner.history(gateway, request.match_info['id']))
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def save(request):
        caller = request.get('caller')
        actor = request.get('caller_actor', '')
        if caller is None or caller.session_prefix or 'admin' not in caller.scopes or not actor.startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        try:
            receipt = owner.save(gateway, request.match_info['id'], await request.json(), actor)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        gateway.event_bus.publish('*', 'webhook.changed', {'subscription_id': request.match_info['id']})
        return web.json_response(receipt, status=receipt['http_status'])

    gateway.app.router.add_get('/v1/webhooks', listing)
    gateway.app.router.add_get('/v1/webhooks/{id}/deliveries', history)
    gateway.app.router.add_post('/v1/webhooks/{id}', save)
