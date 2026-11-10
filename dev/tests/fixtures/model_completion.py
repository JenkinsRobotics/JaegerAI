"""An inert provider adapter for Gateway model-only contract tests."""
from types import SimpleNamespace
import pytest
from jaeger_ai.core.instance.schemas import Config

@pytest.fixture
def model_completion(monkeypatch):
    config=Config(instance_name='test',model={'model_path':'unused'},external_model={
        'enabled':True,'provider':'ollama','model':'owned-model','base_url':'http://127.0.0.1:11434/v1'})
    monkeypatch.setattr('jaeger_ai.core.entity.runtime.load_instance_config_or_default',lambda _:config)
    monkeypatch.setattr('jaeger_ai.core.models.external_model.ExternalModelClient',lambda ext,layout:SimpleNamespace(ext=ext,kind='external'))
    class Adapter:
        calls=[]
        answer='remembered'
        finish=True
        def supports(self,feature):return True
        def format_messages(self,messages,tools,system):return {'messages':[{'role':'system','content':system},*messages]}
        def call(self,payload,interrupt,**kwargs):
            self.calls.append(payload)
            if kwargs.get('on_delta'):
                kwargs['on_delta']('Hello')
                if not self.finish:raise RuntimeError('Model stream ended before confirming completion')
                kwargs['on_delta'](' there')
            return {'content':self.answer,'model':'owned-model'}
        def parse_response(self,raw):return raw
    adapter=Adapter()
    monkeypatch.setattr('jaeger_agent.loop.runtime_bridge._adapter_for_client',lambda _:adapter)
    return adapter
