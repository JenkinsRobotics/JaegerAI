import {it,expect,vi} from 'vitest';import {GatewayClient} from './gateway';
it('uses existing session/control routes with only model pointer CAS fields',async()=>{
 const client=new GatewayClient();const json=vi.spyOn(client,'json').mockResolvedValue({});
 const body={model:'@owned:model',operation_id:'owned-model-choice',expected_model_revision:3};
 await client.modelSettings.saveVersioned('owned/home',body);
 expect(json).toHaveBeenCalledWith('/v1/sessions/owned%2Fhome',body,'PATCH');
 await client.modelSettings.operation('owned-model-choice');expect(json).toHaveBeenLastCalledWith('/v1/control-operations/owned-model-choice');
});
it('cancels only the exact original model intent without introducing execution or permission fields',async()=>{
 const client=new GatewayClient();const json=vi.spyOn(client,'json').mockResolvedValue({});const intent={operation_id:'owned-original-choice',model:'@owned:model',expected_model_revision:0};
 await client.modelSettings.cancelPending('owned',intent);expect(json).toHaveBeenCalledWith('/v1/sessions/owned',{cancel_model_choice:intent},'PATCH');
});
