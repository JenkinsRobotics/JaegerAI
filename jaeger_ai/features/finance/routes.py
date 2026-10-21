"""Owner-only local review controls. No store setup, keys, sync or payments."""
import re
import sqlite3

from aiohttp import web

from . import review
from .store import FinanceStore


def register(gateway):
    def allowed(request):
        caller = request.get('caller')
        if caller is None or caller.session_prefix or 'admin' not in caller.scopes or not request.get('caller_actor', '').startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required for financial review')

    async def status(request):
        allowed(request)
        try:
            return web.json_response(review.snapshot(FinanceStore.open_existing()))
        except FileNotFoundError:
            return web.json_response({'state': 'not_initialized', 'policy': review.policy(), 'actions': [], 'initialization_performed': False})
        except (sqlite3.Error, OSError, ValueError):
            return web.json_response({'error': 'Existing local financial metadata unavailable; no key or provider access attempted'}, status=503)

    async def operation(request):
        allowed(request)
        try:
            result = review.operation(FinanceStore.open_existing(), request.match_info['id'])
            return web.json_response({'receipt': result})
        except (sqlite3.Error, OSError, ValueError):
            return web.json_response({'error': 'Local finance review receipt unavailable; inspect without retry'}, status=503)

    async def decide(request):
        allowed(request)
        try:
            body = await request.json()
            if (not isinstance(body, dict) or set(body) != {'operation_id', 'expected_revision', 'decision'}
                    or not isinstance(body['expected_revision'], str) or re.fullmatch('[a-f0-9]{64}', body['expected_revision']) is None):
                raise ValueError('Exact reviewed local financial scope and stable operation required')
            receipt = review.decide(FinanceStore.open_existing(readonly=False), request.match_info['id'],
                body['decision'], expected_revision=body['expected_revision'], operation_id=body['operation_id'], actor=request['caller_actor'])
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except (sqlite3.Error, OSError):
            return web.json_response({'execution_unknown': True, 'error': 'Review outcome unknown; check original operation. No payment execution exists in this route.'}, status=503)
        gateway.event_bus.publish('*', 'finance.review.changed', {'action_id': receipt['action_id']})
        return web.json_response(receipt, status=receipt['http_status'])

    gateway.app.router.add_get('/v1/finance/review', status)
    gateway.app.router.add_get('/v1/finance/operations/{id}', operation)
    gateway.app.router.add_post('/v1/finance/actions/{id}/review', decide)
