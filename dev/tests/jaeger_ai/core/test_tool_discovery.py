"""Discovery acceptance: model-facing scope, session isolation and permission boundaries."""
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from pydantic import BaseModel
from jaeger_agent import JaegerAgent, ProviderAdapter
from jaeger_agent.skill_registry import toolset_scoping as scopes
from jaeger_agent.skill_registry.tool_selection import ToolSelection, selection_scope
from jaeger_agent.tools.meta import list_tools, load_tools, describe_tool
from jaeger_agent.tool_executor import DirectToolExecutor, tool_allowlist
from jaeger_os.core.tools import tool_registry as registry
from jaeger_os.core.tools.tool_schema import ToolDef

class Args(BaseModel):
    pass

class Adapter(ProviderAdapter):
    name = 'fixture'
    def format_messages(self, messages, tools, system):
        self.tools = tools
        return {'messages': messages, 'tools': tools}
    def call(self, formatted, interrupt_event, **kwargs):
        return {'role': 'assistant', 'content': 'done'}
    def parse_response(self, raw): return raw
    def supports(self, feature): return False

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    snapshot = registry.snapshot_registry()
    registry.clear_registry()
    monkeypatch.delenv('JAEGER_FULL_TOOLS', raising=False)
    monkeypatch.delenv('JAEGER_TOOLSET_SCOPING', raising=False)
    yield
    registry.restore_registry(snapshot)
    scopes.reset_toolsets()


def add(name, description='', **kwargs):
    tool = ToolDef(name, description, Args, lambda: {'executed': True}, **kwargs)
    registry.register_tool_instance(tool)
    return tool


def test_untrusted_actual_turn_cannot_infer_terminal_or_execute_it():
    terminal = add('terminal', 'Run shell commands')
    add('get_time')
    adapter = Adapter()
    agent = JaegerAgent(adapter=adapter, scope_tools=True)
    with scopes.untrusted_content():
        agent.run_turn('Use terminal command python to debug code')
        assert 'terminal' not in {t.name for t in adapter.tools}
        assert DirectToolExecutor().execute(terminal, {})['error_type'] == 'permission_denied'
        result = agent._execute_prepared(agent._prepare_dispatch({'name':'terminal','arguments':{},'id':'denied'}))
        assert result['error_type'] == 'permission_denied'
    assert terminal.fn() == {'executed': True}


def test_every_intent_category_resolves_and_code_is_selected_in_actual_turn():
    assert scopes.resolve_groups(set(scopes._INTENT_PATTERNS))
    add('terminal')
    add('session_organize')
    adapter = Adapter()
    agent = JaegerAgent(adapter=adapter, scope_tools=True)
    agent.run_turn('Organize my conversation and debug python code')
    assert {'terminal','session_organize'} <= {t.name for t in adapter.tools}


def test_parallel_agents_do_not_share_loaded_tools():
    add('terminal'); add('get_weather')
    a, b = (JaegerAgent(adapter=Adapter(), scope_tools=True) for _ in range(2))
    barrier = threading.Barrier(2)
    def select(agent, name):
        with selection_scope(agent._tool_selection):
            assert load_tools(tools=[name])['ok']
            barrier.wait(timeout=2)
            return {t.name for t in agent.tools}
    with ThreadPoolExecutor(2) as pool:
        fa, fb = pool.submit(select,a,'terminal'), pool.submit(select,b,'get_weather')
        assert fa.result() == {'terminal'}
        assert fb.result() == {'get_weather'}
    assert JaegerAgent(adapter=Adapter(), scope_tools=True).tools == []


def test_ranked_multiword_exact_and_bounded_search():
    add('inbox_search', 'Search messages in the work inbox')
    for i in range(25): add(f'doc_{i}', 'Search documentation')
    assert list_tools('search inbox')['tools'][0]['tool'] == 'inbox_search'
    assert list_tools('inbox_search', limit=1)['count'] == 1
    assert list_tools(limit=999)['count'] == 20
    assert list_tools('absent zzz')['tools'] == []


def test_admission_filters_before_ranking_and_cannot_load_denied_tools():
    add('private_inbox', 'Search the inbox'); add('allowed_inbox', 'Search the inbox')
    state = ToolSelection(scoped=True)
    with selection_scope(state), tool_allowlist(['allowed_inbox']):
        assert list_tools('inbox',limit=1)['tools'][0]['tool'] == 'allowed_inbox'
        assert not describe_tool('private_inbox')['ok']
        assert not load_tools(tools=['private_inbox'])['ok']
        assert load_tools(tools=['allowed_inbox'])['ok']
    assert state.names == {'allowed_inbox'}


def test_explicit_catalog_cannot_discover_outside_tools():
    a=add('get_time'); add('terminal')
    agent=JaegerAgent(adapter=Adapter(), tools=[a])
    with selection_scope(agent._tool_selection):
        assert {r['tool'] for r in list_tools()['tools']} == {'get_time'}
        assert not load_tools('code')['ok']


def test_unknown_permission_is_not_read_only_and_unavailable_tool_not_loaded():
    add('needs_setup', 'Search inbox', check_fn=lambda: False)
    with selection_scope(ToolSelection(scoped=True)):
        assert describe_tool('needs_setup')['permission_tier'] == 'UNKNOWN'
        result = list_tools('search inbox')['tools'][0]
        assert not result['available'] and result['unavailable_reason']
        assert not load_tools(tools=['needs_setup'])['ok']


def test_gated_mcp_exact_load_retains_other_tools_hidden():
    names=['mcp__fixture__search','mcp__fixture__write']
    for name in names: add(name, 'Search inbox')
    scopes.register_mcp_server_toolset('fixture',names,gated=True)
    try:
        agent=JaegerAgent(adapter=Adapter())
        assert agent.tools == []
        with selection_scope(agent._tool_selection):
            assert list_tools('search inbox')['tools'][0]['toolset'] == 'fixture'
            assert load_tools(tools=[names[0]])['ok']
        assert [t.name for t in agent.tools] == names[:1]
    finally: scopes.unregister_mcp_server_toolset('fixture')


def test_loading_exact_tool_changes_next_actual_model_step_and_receipt():
    from jaeger_agent.loop.callbacks import AgentCallbacks
    registry.register_tool_from_function(load_tools)
    add('terminal')
    seen, receipts = [], []
    class LoadingAdapter(Adapter):
        def call(self, formatted, interrupt_event, **kwargs):
            seen.append({t.name for t in self.tools})
            if len(seen) == 1:
                return {'role':'assistant','content':None,'tool_calls':[
                    {'id':'load','name':'load_tools','arguments':{'tools':['terminal']}}]}
            return {'role':'assistant','content':'done'}
    agent=JaegerAgent(adapter=LoadingAdapter(), scope_tools=True,
                      callbacks=AgentCallbacks(tool_selection=receipts.append))
    agent.run_turn('Find the needed capability')
    assert 'terminal' not in seen[0] and 'terminal' in seen[1]
    assert receipts[1]['selected_count'] == 2
    assert next(t for t in receipts[1]['tools'] if t['tool']=='terminal')['selection_reason']=='Explicitly loaded'


def test_exact_loading_survives_emergency_core_reduction():
    add('get_time');add('terminal')
    agent=JaegerAgent(adapter=Adapter(), scope_tools=False)
    with selection_scope(agent._tool_selection):
        assert agent._slim_tools_to_core_for_overflow()
        agent._refresh_tool_catalog()
        assert agent.tool_names()==['get_time']
        assert load_tools(tools=['terminal'])['ok']
        assert set(agent.tool_names())=={'get_time','terminal'}
