"""Default-admission regression: real handlers/store, no worker or network."""
import copy
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity import runtime as runtime_module
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.models import external_model
from jaeger_ai.core.runtime import truth


class Request(dict):
    can_read_body = True
    def __init__(self, body, session_id=None):
        super().__init__()
        self.body = body
        self.match_info = {'id': session_id} if session_id else {}
    async def json(self):
        return copy.deepcopy(self.body)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    for name in ('JAEGER_HOME', 'JAEGER_STATE_DIR'):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setenv('JAEGER_NO_ATTACH', '1')
    monkeypatch.setenv('JAEGER_NO_GUI', '1')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    layout = SimpleNamespace(root=tmp_path, workspace_dir=workspace, config_path=tmp_path/'config.yaml')
    config = SimpleNamespace(external_model=SimpleNamespace(
        enabled=True, model='gpt-4.1', provider='openai'),
        automation=SimpleNamespace(interaction_tier='agent'))
    runtime = SimpleNamespace(layout=layout)
    reads = []
    def load(actual_layout):
        assert actual_layout is layout
        reads.append('config')
        return copy.deepcopy(config)
    monkeypatch.setattr(runtime_module, 'load_instance_config_or_default', load)
    monkeypatch.setattr(runtime_module.EntityRuntime, '_instance', runtime)
    def forbidden(*args, **kwargs):
        pytest.fail('Admission/replay must not construct an external client or access credentials')
    monkeypatch.setattr(external_model.ExternalModelClient, '__init__', forbidden)
    discoveries = []
    def inventory():
        discoveries.append('inventory')
        return {'providers': []}  # unknown, not unavailable; no network
    monkeypatch.setattr(truth, 'provider_model_inventory', inventory)
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'sessions.sqlite3'))
    monkeypatch.setattr(app, '_activate_owner_session', lambda *a, **kw: None)
    monkeypatch.setattr(app, '_current_tier', lambda: 'agent')
    launches = []
    def before_dispatch(admitted, session_id, text):
        # Observe persisted truth at the dispatch boundary, before any effects.
        if not admitted.get('replayed'):
            row = app.store.get_request(admitted['request_id'])
            assert row['execution'] == admitted['execution']
            launches.append(copy.deepcopy(row['execution']))
    monkeypatch.setattr(app, '_start_admitted_turn', before_dispatch)
    return SimpleNamespace(app=app, config=config, layout=layout, launches=launches,
                           reads=reads, discoveries=discoveries)


async def new_session(probe, **body):
    response = await probe.app.handle_create_session(Request(body))
    assert response.status == 201, response.text
    return json.loads(response.text)['session_id']


async def send(probe, sid, **extra):
    body = {'text': 'Create a verified report', 'request_id': 'r', 'attachment_ids': [], **extra}
    response = await probe.app.handle_send_turn(Request(body, sid))
    assert response.status == 200, response.text
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_minimal_new_chat_freezes_global_defaults_before_dispatch(probe):
    sid = await new_session(probe)
    await send(probe, sid)
    [execution] = probe.launches
    assert {k: execution[k] for k in ('model', 'provider', 'workspace')} == {
        'model': 'gpt-4.1', 'provider': 'openai', 'workspace': str(probe.layout.workspace_dir.resolve())}
    assert execution['allowed_tools'] is None
    assert execution['attachments'] == []
    assert execution['interaction_tier'] == 'agent'


@pytest.mark.asyncio
@pytest.mark.parametrize('grant', [None, [], ['read_file']])
@pytest.mark.parametrize('explicit', [False, True])
async def test_requested_and_session_precedence_and_exact_grants(probe, grant, explicit, tmp_path):
    session_workspace = tmp_path / 'session-project'
    explicit_workspace = tmp_path / 'explicit-project'
    session_workspace.mkdir(); explicit_workspace.mkdir()
    sid = await new_session(probe, workspace=str(session_workspace),
                            metadata={'model': 'session-model', 'provider': 'openai'})
    choices = {} if grant is None else {'allowed_tools': grant}
    if explicit:
        choices.update(model='explicit-model', provider='openai', workspace=str(explicit_workspace))
    await send(probe, sid, **choices)
    [execution] = probe.launches
    assert execution['model'] == ('explicit-model' if explicit else 'session-model')
    assert execution['provider'] == 'openai'
    assert execution['workspace'] == str(explicit_workspace if explicit else session_workspace)
    assert execution['allowed_tools'] == grant


@pytest.mark.asyncio
async def test_identical_replay_ignores_changed_defaults_and_does_not_discover_or_mutate_session(probe, monkeypatch):
    sid = await new_session(probe)
    await send(probe, sid)
    original = copy.deepcopy(probe.app.store.get_request('r')['execution'])
    probe.app.store.complete_request('r', status='completed', result={'output': 'saved'})
    probe.app.store.update_metadata(sid, {'model': 'later-model', 'provider': 'anthropic'})
    probe.config.external_model.model = 'later-global'
    probe.config.external_model.provider = 'anthropic'
    probe.layout.workspace_dir = probe.layout.root / 'later-workspace'
    before = copy.deepcopy(probe.app.store.get_session(sid))
    reads, discoveries = len(probe.reads), len(probe.discoveries)
    def forbidden(*a, **kw):
        pytest.fail('Replay must not rediscover defaults or provider availability')
    monkeypatch.setattr(runtime_module, 'load_instance_config_or_default', forbidden)
    monkeypatch.setattr(truth, 'provider_model_inventory', forbidden)
    result = await send(probe, sid)
    assert result['replayed'] is True
    assert probe.app.store.get_request('r')['execution'] == original
    assert probe.app.store.get_session(sid) == before
    assert len(probe.launches) == 1
    assert (len(probe.reads), len(probe.discoveries)) == (reads, discoveries)


def test_configured_route_round_trips_without_constructing_another_client(probe):
    from jaeger_ai.core.runtime.execution_defaults import configured_execution_defaults
    from jaeger_ai.core.models.router import select_client
    from jaeger_ai.core.instance.schemas import ExternalModelConfig
    probe.config.external_model = ExternalModelConfig(enabled=True, model='gpt-4.1', provider='openai', base_url='https://custom.invalid/v1')
    snapshot = configured_execution_defaults(probe.layout, probe.config)
    client = SimpleNamespace(model_name='gpt-4.1', provider='openai', endpoint='https://custom.invalid/v1')
    assert select_client(client, probe.config, probe.layout,
                         snapshot['model'], snapshot['provider']) is client


@pytest.mark.parametrize('provider,model,enabled', [
    ('cli','gpt-4.1',True), ('local','gpt-4.1',True),
    ('ollama-cloud','gpt-4.1',True), ('openai','default',True),
    ('openai','@openai:gpt-4.1',True), ('openai','gpt-4.1',False),
])
def test_unsupported_defaults_do_not_infer_a_route(probe, provider, model, enabled):
    from jaeger_ai.core.runtime.execution_defaults import configured_execution_defaults
    probe.config.external_model = SimpleNamespace(provider=provider, model=model, enabled=enabled)
    snapshot = configured_execution_defaults(probe.layout, probe.config)
    assert 'model' not in snapshot and 'provider' not in snapshot


@pytest.mark.asyncio
async def test_provider_only_choice_is_not_completed_from_global_model(probe):
    sid = await new_session(probe)
    await send(probe, sid, provider='anthropic')
    assert probe.launches[0]['model'] is None
    assert probe.launches[0]['provider'] == 'anthropic'


def test_missing_runtime_is_not_started_by_default_lookup(probe, monkeypatch):
    monkeypatch.setattr(runtime_module.EntityRuntime, '_instance', None)
    def forbidden(*a, **kw):
        pytest.fail('Admission must not boot the EntityRuntime')
    monkeypatch.setattr(runtime_module.EntityRuntime, 'get_singleton', forbidden)
    assert probe.app._foreground_execution_defaults() == {}


def test_default_workspace_preserves_bare_paths_and_writable_roots(probe):
    from jaeger_agent.core import workspace as ws
    from jaeger_ai.core.runtime.execution_defaults import execution_project_root
    layout = SimpleNamespace(root=probe.layout.root, workspace_dir=probe.layout.workspace_dir,
                             skills_dir=probe.layout.root/'skills', memory_dir=probe.layout.root/'memory')
    layout.skills_dir.mkdir()
    ws.bind(layout)
    execution = {'workspace': str(layout.workspace_dir),
                 '_instance_defaults': {'workspace': str(layout.workspace_dir)}}
    try:
        with ws.project_scope(None):
            before = (ws._resolve_write('new-bare.txt'), ws.writable_roots())
        with ws.project_scope(execution_project_root(execution, layout)):
            after = (ws._resolve_write('new-bare.txt'), ws.writable_roots())
            assert after == before
            assert after[0] == layout.skills_dir/'new-bare.txt'
            path = ws._resolve_write('new-bare.txt')
            path.write_text('preserved')
            assert ws._resolve_read('new-bare.txt').read_text() == 'preserved'
        # Explicit project behavior remains distinct and unchanged.
        with ws.project_scope(execution_project_root({'workspace': str(layout.workspace_dir)}, layout)):
            assert ws._resolve_write('new-bare.txt') == layout.workspace_dir/'new-bare.txt'
        layout.workspace_dir.rmdir()
        # Instance mode historically permits an absent workspace directory.
        with ws.project_scope(execution_project_root(execution, layout)):
            assert ws.get_project_root() is None
    finally:
        ws.bind(layout)


@pytest.mark.parametrize('field,value', [('base_url','https://changed.invalid/v1'),
    ('provider','anthropic'), ('model','changed'), ('api_key_env','DIFFERENT_KEY')])
def test_default_route_drift_rejected_before_external_client_construction(probe, field, value):
    from jaeger_ai.core.runtime.execution_defaults import default_route_fingerprint, validate_default_route
    fingerprint = default_route_fingerprint(probe.config)
    setattr(probe.config.external_model, field, value)
    with pytest.raises(ValueError, match='no model dispatch'):
        validate_default_route(probe.config, fingerprint)


def test_instance_marker_cannot_be_injected_as_client_choice(probe):
    row = probe.app.store.admit_request('s', 'test', request_id='injection', requested={
        'workspace': str(probe.layout.workspace_dir), '_instance_defaults': {'workspace': '/forged'}})
    assert '_instance_defaults' not in row['execution']


def test_runtime_checks_exact_loaded_config_before_constructing_client(probe, monkeypatch):
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.core import workspace
    from jaeger_ai.core.instance import commissioning
    from jaeger_ai.core.runtime.execution_defaults import default_route_fingerprint
    expected = default_route_fingerprint(probe.config)
    probe.config.external_model.base_url = 'https://changed.invalid/v1'
    monkeypatch.setattr(sqlite_store, 'bind', lambda layout: None)
    monkeypatch.setattr(workspace, 'bind', lambda layout: None)
    monkeypatch.setattr(commissioning, 'install_commissioning_permissions', lambda layout: None)
    # Fixture forbids ExternalModelClient construction. The actual runtime
    # must reject drift first, not instantiate a new route and then inspect it.
    with pytest.raises(ValueError, match='no model dispatch'):
        runtime_module.EntityRuntime.run_subordinate_react(
            SimpleNamespace(layout=probe.layout), 'never sent',
            model='gpt-4.1', provider='openai', admitted_default_route=expected)


def test_default_workspace_drift_rejected_before_tools(probe):
    from jaeger_ai.core.runtime.execution_defaults import execution_project_root
    root = str(probe.layout.workspace_dir)
    execution = {'workspace':root, '_instance_defaults':{'workspace':root}}
    probe.layout.workspace_dir = probe.layout.root/'different'
    with pytest.raises(ValueError, match='no tool dispatch'):
        execution_project_root(execution, probe.layout)


@pytest.mark.asyncio
async def test_task_endpoint_rejects_forged_instance_mode(probe):
    sid = await new_session(probe)
    request = Request({'session_id':sid, 'goal':'forged scope', 'execution':{
        'workspace':str(probe.layout.workspace_dir),
        '_instance_defaults':{'workspace':str(probe.layout.workspace_dir)}}})
    request.method = 'POST'
    response = await probe.app.handle_tasks(request)
    assert response.status == 400
    assert probe.app.task_owner.store.list_tasks() == []


def test_legacy_session_marker_is_not_a_default_scope_proof(probe, monkeypatch):
    sid = 'legacy'
    probe.app.store.ensure_session(sid, workspace=str(probe.layout.workspace_dir), metadata={
        '_instance_defaults': {'workspace':'/forged', 'route_fingerprint':'forged'}})
    from jaeger_ai.core.runtime import execution_defaults
    observed = []
    def inspect(selection, layout):
        observed.append(copy.deepcopy(selection))
        raise RuntimeError('stop before dispatch')
    monkeypatch.setattr(runtime_module.EntityRuntime, 'get_singleton', classmethod(lambda cls: SimpleNamespace(layout=probe.layout)))
    monkeypatch.setattr(execution_defaults, 'execution_project_root', inspect)
    with pytest.raises(RuntimeError, match='stop before dispatch'):
        probe.app._owner_react_turn('legacy', session_key=sid, request_id='legacy', execution=None)
    assert len(observed) == 1 and '_instance_defaults' not in observed[0]


async def admitted_default(probe):
    sid = await new_session(probe)
    await send(probe, sid)
    source = probe.app.store.get_request('r')
    probe.app.store.complete_request('r', status='completed', result={'output':'saved'})
    return sid, source


@pytest.mark.asyncio
async def test_real_retry_keeps_instance_mode_and_route_without_default_lookup(probe, monkeypatch):
    from jaeger_ai.core.runtime.execution_defaults import execution_project_root
    sid, source = await admitted_default(probe)
    probe.config.external_model.model = 'changed-later'
    monkeypatch.setattr(runtime_module, 'load_instance_config_or_default',
        lambda *a: pytest.fail('Retry must retain original snapshot, not discover defaults'))
    response = await probe.app.handle_retry_session(Request({}, sid))
    assert response.status == 202, response.text
    retried = probe.app.store.get_request(json.loads(response.text)['request_id'])
    assert retried['execution'] == source['execution']
    assert execution_project_root(retried['execution'], probe.layout) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('override,retained', [
    ({'model':'explicit-model','provider':'openai'}, {'workspace'}),
    ({'workspace':'/explicit-project'}, {'route_fingerprint'}),
    ({'model':'explicit-model','provider':'openai','workspace':'/explicit-project'}, set()),
])
async def test_retry_explicit_overrides_keep_only_compatible_default_components(probe, override, retained):
    sid, source = await admitted_default(probe)
    body = {'text':source['input_text'], 'request_id':'retry', **source['execution'], **override}
    response = await probe.app._admit_and_start_retry(sid, body, 'r', source_execution=source['execution'])
    assert response.status == 202, response.text
    result = probe.app.store.get_request('retry')['execution']
    assert set(result.get('_instance_defaults', {})) == retained
    for key, value in override.items():
        assert result[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['missing', 'other_session', 'changed_source', 'caller', 'tools'])
async def test_inheritance_refuses_bad_source_and_authority(probe, bad):
    from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
    sid, source = await admitted_default(probe)
    choices = copy.deepcopy(source['execution'])
    origin = {'request_id':'r', 'session_id':sid, 'expected':copy.deepcopy(source['execution'])}
    if bad == 'missing':
        origin['request_id'] = 'missing'
    elif bad == 'other_session':
        origin['session_id'] = 'another-session'
    elif bad == 'changed_source':
        with probe.app.store._immediate() as conn:
            altered = {**source['execution'], 'model':'tampered'}
            conn.execute('UPDATE client_requests SET execution_json=? WHERE request_id=?', (json.dumps(altered),'r'))
    elif bad == 'caller':
        choices['caller'] = 'different-caller'
    else:
        # Prove an empty admitted grant cannot become the default full catalog.
        source['execution']['allowed_tools'] = []
        origin['expected'] = copy.deepcopy(source['execution'])
        with probe.app.store._immediate() as conn:
            conn.execute('UPDATE client_requests SET execution_json=? WHERE request_id=?', (json.dumps(source['execution']),'r'))
        choices['allowed_tools'] = None
    with pytest.raises(InstanceDefaultsConflict):
        probe.app.store.admit_request('child', 'no dispatch', request_id='child-r',
            requested=choices, instance_defaults_source=origin)
    assert probe.app.store.get_request('child-r') is None


@pytest.mark.asyncio
async def test_internal_task_inherits_mode_from_original_request(probe):
    sid, source = await admitted_default(probe)
    task = probe.app.task_owner.submit('Make a later report', context={
        'session_id':sid, 'request_id':'r', 'source':'user',
        'user_text':'Queue this work in the background', 'execution':source['execution']})
    await probe.app.task_owner._execute(task['task_id'])
    child = probe.app.store.get_request(task['task_id']+':0')
    assert child is not None
    assert child['execution']['_instance_defaults'] == source['execution']['_instance_defaults']
    assert child['execution']['workspace'] == source['execution']['workspace']
    assert child['execution']['allowed_tools'] == source['execution']['allowed_tools']


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['missing', 'other_session', 'forged_marker', 'changed_workspace'])
async def test_internal_task_cannot_promote_unproved_instance_metadata(probe, bad):
    sid, source = await admitted_default(probe)
    task = probe.app.task_owner.submit('Make a later report', context={
        'session_id':sid, 'request_id':'r', 'source':'user',
        'user_text':'Queue this work in the background', 'execution':source['execution']})
    def corrupt(current):
        if bad == 'missing':
            current.provenance['request_id'] = 'missing'
        elif bad == 'other_session':
            current.provenance['session_id'] = 'other-session'
        elif bad == 'forged_marker':
            current.payload['execution']['_instance_defaults']['route_fingerprint'] = 'forged'
        else:
            current.payload['execution']['workspace'] = '/changed'
    probe.app.task_owner.store.update_task(task['task_id'], corrupt)
    await probe.app.task_owner._execute(task['task_id'])
    assert probe.app.store.get_request(task['task_id']+':0') is None
    stored = probe.app.task_owner.store.get_task(task['task_id'])
    assert stored.state.value == 'paused'
    assert 'no dispatch' in stored.error


@pytest.mark.asyncio
async def test_recovered_child_cannot_widen_task_narrowing(probe):
    sid, source = await admitted_default(probe)
    narrowed = {**source['execution'], 'allowed_tools': []}
    task = probe.app.task_owner.submit('Make a later report', context={
        'session_id':sid, 'request_id':'r', 'source':'user',
        'user_text':'Queue this work in the background', 'execution':narrowed})
    owner = probe.app.task_owner
    current = owner.store.get_task(task['task_id'])
    child_execution = owner._continuation_execution(current)
    child_execution['allowed_tools'] = None
    probe.app.store.admit_request('task:'+current.task_id, owner._continuation_prompt(current),
        request_id=current.task_id+':0', requested=child_execution,
        instance_defaults_source=owner._instance_defaults_source(current))
    probe.launches.clear()
    await owner._execute(current.task_id)
    assert probe.launches == []
    assert owner.store.get_task(current.task_id).state.value == 'paused'


@pytest.mark.asyncio
async def test_historical_source_marker_cannot_establish_inheritance(probe):
    from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
    sid, source = await admitted_default(probe)
    with probe.app.store._immediate() as conn:
        conn.execute('UPDATE client_requests SET digest_version=1 WHERE request_id=?', ('r',))
    with pytest.raises(InstanceDefaultsConflict, match='Historical'):
        probe.app.store.admit_request('child', 'no dispatch', request_id='child-r', requested=source['execution'],
            instance_defaults_source={'session_id':sid,'request_id':'r','claimed':source['execution']['_instance_defaults']})


@pytest.mark.asyncio
async def test_retry_cannot_use_a_different_canonical_session_as_marker_source(probe):
    from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
    sid, source = await admitted_default(probe)
    probe.app.store.ensure_session('other')
    with pytest.raises(InstanceDefaultsConflict, match='originating session'):
        probe.app.store.admit_request('other', source['input_text'], request_id='cross-retry',
            requested=source['execution'], retry_of='r',
            instance_defaults_source={'session_id':sid,'request_id':'r'})
    assert probe.app.store.get_request('cross-retry') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('adapter', ['package', 'module'])
async def test_handoff_adapter_preserves_default_mode_without_transmitting_parent_route(probe, adapter, monkeypatch):
    import importlib
    sid, source = await admitted_default(probe)
    if adapter == 'package':
        module = importlib.import_module('jaeger_agent.tools.call_agent')
        args = ('bounded work',)
    else:
        from pathlib import Path
        from jaeger_os.core.tools import tool_registry
        # Inspect the shipped adapter without double-registering the package's
        # same-named tools into this test process.
        monkeypatch.setattr(tool_registry, 'register_tool_from_function', lambda **kw: lambda fn: fn)
        path = Path(__file__).resolve().parents[4]/'jaeger_ai/modules/team-handoff/call_agent.py'
        spec = importlib.util.spec_from_file_location('handoff_adapter_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = ('native:specialist','bounded work')
    opts = dict(from_agent_id='native:jaeger',require_approval=True,request_id='child',
        parent_run_id='',permitted_context='',timeout_seconds=30,tools=[])
    context = {'owner':probe.app.task_owner,'session_id':sid,'request_id':'r','execution':source['execution']}
    body = module._handoff_body(*args, context, project_id='', **opts)
    assert not {'workspace','model','provider','_instance_defaults'} & set(body)
    # Explicit project always wins, even when the parent uses instance mode.
    project = module._handoff_body(*args, context, project_id='explicit-project', **opts)
    assert project['project_id'] == 'explicit-project' and 'workspace' not in project
    # Before this patch, explicit parent routes were not copied by these
    # adapters: the specialist's own configured/selected route keeps precedence.
    explicit = {**context, 'execution':{'workspace':'/explicit','model':'chosen-model','provider':'openai'}}
    result = module._handoff_body(*args, explicit, project_id='', **opts)
    assert result['workspace'] == '/explicit'
    assert not {'model','provider','_instance_defaults'} & set(result)
    forged = {**context, 'request_id':'missing-source'}
    with pytest.raises(ValueError, match='no dispatch'):
        module._handoff_body(*args, forged, project_id='', **opts)


@pytest.mark.parametrize('selection', [None, {}, {'workspace': '/explicit/project'},
    {'model': 'gpt-4.1', '_instance_defaults': {'route_fingerprint': 'route-only'}}])
def test_gateway_markerless_workspace_does_not_require_runtime_layout(probe, monkeypatch, selection):
    # Legacy/custom Entity implementations need no layout unless admission
    # actually froze an instance workspace that must be revalidated.
    monkeypatch.setattr(runtime_module.EntityRuntime, 'get_singleton',
                        classmethod(lambda cls: SimpleNamespace()))
    def stop(*args):
        raise RuntimeError('workspace validated before dispatch')
    monkeypatch.setattr(probe.app, '_turn_stream_callbacks', stop)
    with pytest.raises(RuntimeError, match='workspace validated before dispatch'):
        probe.app._owner_react_turn('test', session_key='missing-layout',
                                   request_id='missing-layout', execution=selection)


def test_gateway_frozen_workspace_requires_runtime_layout_before_effects(probe, monkeypatch):
    monkeypatch.setattr(runtime_module.EntityRuntime, 'get_singleton',
                        classmethod(lambda cls: SimpleNamespace()))
    def forbidden(*args):
        pytest.fail('Missing frozen workspace proof must reject before callbacks or dispatch')
    monkeypatch.setattr(probe.app, '_turn_stream_callbacks', forbidden)
    root = str(probe.layout.workspace_dir)
    with pytest.raises(ValueError, match='Admitted default workspace changed; no tool dispatch'):
        probe.app._owner_react_turn('test', session_key='missing-layout', request_id='missing-layout',
                                   execution={'workspace': root, '_instance_defaults': {'workspace': root}})
