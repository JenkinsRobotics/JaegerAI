"""Read-only local execution-host projection. No hardware discovery or provider probe.

One existing Gateway process is an execution host, not a new machine registry.
OS permissions belong to the native shell process and are reported separately.
"""
import os
import platform

from aiohttp import web


def register(gateway):
    async def read(request):
        facts=gateway.store.diagnostics_snapshot()
        return web.json_response({'scope':'gateway_process_only','computers':[{
            'id':'gateway-local','kind':'local_gateway','state':'serving',
            'process_id':os.getpid(),'os':platform.system(),'architecture':platform.machine(),
            'screen_view':'no_shared_ui_viewport','input_authorization':'per_admitted_turn_and_existing_policy',
            'os_permissions':'not_inferred_from_gateway','recovery':'existing_foreground_lifecycle_owner_only',
        }], 'hosted':{'state':'not_observed_by_gateway_inventory','allocation_supported':False},
            'requests':facts['requests'],'approvals':facts['approvals'],
            'actions':{'allocate':False,'restart':False,'input':False,'capture':False},
            'limits':['Serving proves this local Gateway transport, not an end-to-end agent/tool result.',
                      'No hostname, address, serial, credentials, app list or hardware/media probe is collected.',
                      'No provider, remote host, tunnel, screen capture, input or permission change is attempted.']})
    gateway.app.router.add_get('/v1/runtime/computers',read)
