import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {MCPControls} from './MCPControls';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('persists an unknown connection command and recovers only its exact receipt',async()=>{
 const key='jaeger.ui.mcp.operation.v1.owned-mcp';localStorage.removeItem(key);
 const mutate=vi.fn(async()=>{throw Error('Response lost');});
 const operation=vi.fn(async(id:string)=>({receipt:{ok:true,operation_id:id,result:{id:'owned-mcp',state:'disconnected'}}}));
 const controls={mutate,operation},host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<MCPControls controls={controls} server={{id:'owned-mcp',name:'Owned fixture',state:'loaded_not_probed',actions:['disconnect']}} refresh={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Disconnect Owned fixture')!.click());
  expect(mutate).not.toHaveBeenCalled();
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Confirm disconnect')!.click());
  const saved=JSON.parse(localStorage.getItem(key)!);
  expect(mutate).toHaveBeenCalledExactlyOnceWith('owned-mcp','disconnect',{operation_id:saved.operation_id,expected_state:'loaded_not_probed'});
  expect(host.textContent).not.toContain('Gateway confirmed');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check MCP operation')!.click());
  expect(operation).toHaveBeenCalledExactlyOnceWith(saved.operation_id);expect(mutate).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(key)).toBeNull();expect(host.textContent).toContain('Gateway confirmed connection transition');
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
