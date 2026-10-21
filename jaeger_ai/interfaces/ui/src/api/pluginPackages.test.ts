import {expect,it,vi} from 'vitest';import {GatewayClient} from './gateway';
it('uses explicit package/startup bodies and reads receipts without re-sending commands',async()=>{
 const fetcher=vi.fn().mockResolvedValue({ok:true,text:async()=>JSON.stringify({receipt:null})});vi.stubGlobal('fetch',fetcher);
 try{const client=new GatewayClient();const body={operation_id:'owned',expected_revision:1,enabled:false};await client.plugins.startup!('owned:id',body);expect(fetcher).toHaveBeenLastCalledWith('/v1/runtime/plugins/owned%3Aid/startup',expect.objectContaining({method:'POST',body:JSON.stringify(body)}));
 const review={action:'install' as const,session_id:'owned-home',attachment_id:'owned-wheel'};await client.plugins.packages!.preview(review);expect(fetcher).toHaveBeenLastCalledWith('/v1/runtime/plugins/packages/preview',expect.objectContaining({method:'POST',body:JSON.stringify(review)}));
 await client.plugins.packages!.operation('owned-op');expect(fetcher).toHaveBeenLastCalledWith('/v1/runtime/plugins/package-operations/owned-op',expect.objectContaining({method:'GET',body:undefined}));
 }finally{vi.unstubAllGlobals();}
});
