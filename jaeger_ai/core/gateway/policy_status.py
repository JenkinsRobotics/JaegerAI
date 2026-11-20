"""Owner-only passive view of policy sources and active grants bound to the current resident."""
from aiohttp import web


def _require_owner_admin(request) -> None:
    caller = request.get('caller')
    if caller is None or caller.session_prefix or 'admin' not in caller.scopes or not request.get('caller_actor', '').startswith('owner:'):
        raise web.HTTPForbidden(text='Existing owner administration scope required')


def register(gateway):
    async def read(request):
        _require_owner_admin(request)
        from jaeger_ai.core.authority.status import snapshot
        from jaeger_ai.core.entity.runtime import EntityRuntime
        # Never get_singleton(): status cannot start/bind a resident or new store.
        runtime = EntityRuntime._instance
        return web.json_response(snapshot(getattr(runtime, 'layout', None)))

    async def list_grants(request):
        _require_owner_admin(request)
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_ai.core.frameworks.grants import FrameworkGrants
        from jaeger_ai.core.runtime.autonomy import AUTONOMY_LABELS, effective_autonomy
        from jaeger_os.core.safety.permissions import PermissionGrants

        runtime = EntityRuntime._instance
        layout = getattr(runtime, 'layout', None)
        root = layout.root if layout is not None else gateway._instance_root()
        mode = effective_autonomy(root / 'config.yaml')
        skill_grants = PermissionGrants.load(root).inspect()
        framework_grants = FrameworkGrants().all()
        return web.json_response({
            'autonomy': mode,
            'autonomy_label': AUTONOMY_LABELS.get(mode, mode),
            'skill_grants': skill_grants,
            'framework_grants': framework_grants,
        })

    async def revoke_grant(request):
        _require_owner_admin(request)
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_ai.core.frameworks.grants import FrameworkGrants
        from jaeger_os.core.safety.permissions import PermissionGrants

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('JSON object required')
        except (ValueError, TypeError) as exc:
            return web.json_response({'ok': False, 'error': str(exc)}, status=400)

        runtime = EntityRuntime._instance
        layout = getattr(runtime, 'layout', None)
        root = layout.root if layout is not None else gateway._instance_root()
        skill = str(body.get('skill') or '').strip()
        framework = str(body.get('framework') or '').strip()
        capability = str(body.get('capability') or '').strip()
        if skill:
            grants = PermissionGrants.load(root)
            grants.revoke(skill)
            return web.json_response({'ok': True, 'revoked': {'skill': skill}, 'skill_grants': grants.inspect()})
        if framework and capability:
            fg = FrameworkGrants()
            fg.set(framework, capability, False, by=str(request.get('caller_actor') or 'owner'))
            return web.json_response({'ok': True, 'revoked': {'framework': framework, 'capability': capability}})
        return web.json_response({'ok': False, 'error': 'Provide skill or framework+capability to revoke'}, status=400)

    gateway.app.router.add_get('/v1/runtime/policy-sources', read)
    gateway.app.router.add_get('/v1/runtime/authority/grants', list_grants)
    gateway.app.router.add_post('/v1/runtime/authority/grants/revoke', revoke_grant)
