from types import SimpleNamespace

from jaeger_ai.core.instance.schemas import Config
from jaeger_ai.core.models.session_selection import select_client


def test_external_pick_preserves_instance_config_and_other_client(monkeypatch):
    from jaeger_ai.core.models import external_model
    config=Config(instance_name="test", model={"model_path":"test.gguf"})
    config.external_model.enabled=True
    config.external_model.provider='ollama'
    config.external_model.base_url='http://configured-host:11434'
    config.external_model.model='original'
    original=config.model_dump()
    default=SimpleNamespace(model_name='original',provider='ollama')
    monkeypatch.setattr(external_model,'ExternalModelClient',lambda ext,layout:SimpleNamespace(ext=ext,model_name=ext.model,provider=ext.provider))
    selected=select_client(default,config,None,'picked','ollama-local')
    assert selected.model_name=='picked'
    assert selected.ext.base_url=='http://configured-host:11434'
    assert config.model_dump()==original
    assert default.model_name=='original'
    assert select_client(default,config,None,None,None) is default
    assert select_client(default,config,None,'original','ollama') is default


def test_conversation_pick_preserves_history_and_does_not_change_another_session(monkeypatch):
    from jaeger_ai import main
    from jaeger_ai.core import sessions
    from jaeger_ai.core.models import session_selection
    default=SimpleNamespace(model_name='default-model')
    picks=[]
    monkeypatch.setattr(main,'_session_model_clients',{})
    monkeypatch.setattr(main,'_jaeger_agents_by_session',{})
    monkeypatch.setattr(main,'_carried_session_messages',{})
    monkeypatch.setattr(main,'_pipeline',{})
    monkeypatch.setattr(sessions,'get_store',lambda:None)
    def select(client, config, layout, model, provider):
        return client if not model else SimpleNamespace(model_name=model)
    monkeypatch.setattr(session_selection,'select_client',select)
    def evict(session):
        main._jaeger_agents_by_session.pop(session,None)
        main._session_model_clients.pop(session,None)
    monkeypatch.setattr(main,'evict_session',evict)
    def turn(client,text,session_key):
        agent=main._jaeger_agents_by_session.setdefault(session_key,SimpleNamespace(messages=main._carried_session_messages.pop(session_key,[])))
        agent.messages.append(text)
        picks.append((session_key,client.model_name,list(agent.messages)))
        return dict(text='answer',tool_activity=[],spoke_via_tool=False,elapsed_s=0,skipped_final=False,error=None)
    monkeypatch.setattr(main,'_run_turn',turn)
    main.run_for_voice(default,'first',session_key='a')
    main.run_for_voice(default,'second',session_key='a',model='chosen',provider='ollama')
    main.run_for_voice(default,'other',session_key='b')
    assert picks==[('a','default-model',['first']),('a','chosen',['first','second']),('b','default-model',['other'])]
