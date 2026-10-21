import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {it,expect,vi} from 'vitest';
import {MCPResources} from './MCPResources';
import type {MCPResources as Controls} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const server={id:'owned-resources',name:'Owned fixture'};
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent===text)!;
async function mounted(controls:Controls,run:()=>Promise<void>){const host=document.createElement('div');document.body.append(host);const root=createRoot(host);try{await act(async()=>root.render(<MCPResources controls={controls} server={server} onClose={()=>{}}/>));await run();}finally{await act(async()=>root.unmount());host.remove();for(const key of Object.keys(localStorage))if(key.startsWith('jaeger.ui.mcp-resource.operation.v1.'+server.id))localStorage.removeItem(key);}}
it('requires explicit catalog, read, review and import, using the staged digest without granting context',async()=>{
 const staged={id:'snapshot',server_id:server.id,resource_id:'resource',title:'Owned text',text:'literal <script>reference</script>',digest:'owned-digest',redacted:false,observed_at:1,source:'configured_mcp_resource',authority:'reference_data_only'};
 const mutate=vi.fn(async(_server:string,action:string,body:Record<string,unknown>)=>({ok:true,operation_id:String(body.operation_id),result:action==='list'?{catalog:{server_id:server.id,resources:[{id:'resource',title:'Owned text',description:'Reference only',mime:'text/plain'}],next_page:null,truncated:false}}:action==='read'?{snapshot:staged}:{document:{id:'owned-document',revision:1}}}));
 const snapshot=vi.fn(async()=>staged),operation=vi.fn();
 await mounted({mutate,snapshot,operation} as Controls,async()=>{
  expect(mutate).not.toHaveBeenCalled();expect(snapshot).not.toHaveBeenCalled();
  await act(async()=>button('Read resource catalog from server').click());expect(mutate).toHaveBeenCalledTimes(1);
  await act(async()=>button('Read Owned text').click());expect(snapshot).toHaveBeenCalledExactlyOnceWith(server.id,'snapshot');
  expect(document.body.textContent).toContain(staged.text);expect(document.querySelector('script')).toBeNull();
  await act(async()=>button('Import reviewed text to Library').click());expect(mutate).toHaveBeenCalledTimes(2);
  await act(async()=>button('Confirm resource import').click());
  expect(mutate.mock.calls[2][2]).toMatchObject({snapshot_id:'snapshot',expected_digest:'owned-digest'});
  expect(document.body.textContent).toContain('No bot context or grants changed');
 });
});
it('recovers an unknown read through receipt and local snapshot only, never replaying provider action',async()=>{
 const operation_id='owned-unknown';localStorage.setItem('jaeger.ui.mcp-resource.operation.v1.'+server.id+'.'+operation_id,JSON.stringify({operation_id,action:'read'}));
 const mutate=vi.fn(),snapshot=vi.fn(async()=>{throw Error('Volatile cache expired');});
 const operation=vi.fn(async()=>({receipt:{ok:true,operation_id,result:{snapshot:{id:'old-snapshot',server_id:server.id,digest:'old',title:'Owned expired',resource_id:'resource',redacted:false,observed_at:1,source:'configured_mcp_resource',authority:'reference_data_only'}}}}));
 await mounted({mutate,snapshot,operation} as Controls,async()=>{
  expect(mutate).not.toHaveBeenCalled();await act(async()=>button('Check resource operation').click());
  expect(operation).toHaveBeenCalledExactlyOnceWith(operation_id);expect(mutate).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain('No automatic provider read occurred');
  expect(button('Read resource catalog from server')).toBeTruthy();
 });
});
