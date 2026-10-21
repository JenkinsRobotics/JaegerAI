import {expect,it,vi} from 'vitest';import {GatewayClient} from './gateway';
it('sends the claim command as the actual JSON body and reads the original operation receipt',async()=>{
 const fetcher=vi.fn().mockResolvedValue({ok:true,text:async()=>JSON.stringify({ok:true})});vi.stubGlobal('fetch',fetcher);
 try{const client=new GatewayClient();const body={operation_id:'owned-operation',expected_revision:'a'.repeat(64),text:'reviewed correction'};
 await client.semanticClaimControls.mutate('clm:owned','correct',body);
 expect(fetcher).toHaveBeenCalledWith('/v1/runtime/memory/claims/clm%3Aowned/correct',expect.objectContaining({method:'POST',body:JSON.stringify(body),credentials:'same-origin'}));
 await client.semanticClaimControls.operation('owned-operation');expect(fetcher).toHaveBeenLastCalledWith('/v1/runtime/memory/claim-operations/owned-operation',expect.objectContaining({method:'GET',body:undefined}));
 }finally{vi.unstubAllGlobals();}
});
