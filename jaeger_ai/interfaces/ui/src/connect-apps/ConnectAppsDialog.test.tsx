import {act} from 'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{ConnectAppsDialog}from'./ConnectAppsDialog';import type{JaegerSource}from'../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT=true;
it('uses registry availability and requires explicit confirmation before an install',async()=>{
 const install=vi.fn(async()=>({state:{value:'installing'}}));const source={connectApps:{list:async()=>({apps:[{id:'owned',name:'Owned integration',status:'available',actions:['install'],state:{value:'not_installed'}},{id:'future',name:'Unavailable integration',status:'coming_soon',actions:[],state:{value:'coming_soon'}}],categories:[],connected_count:0}),state:vi.fn(),install}}as unknown as JaegerSource;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<ConnectAppsDialog open source={source} onClose={()=>{}}/>));
 expect(el.textContent).toContain('Unavailable integration');expect([...el.querySelectorAll('button')].filter(b=>b.textContent==='Install…')).toHaveLength(1);
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent==='Install…')!.click();});expect(install).not.toHaveBeenCalled();
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent==='Cancel')!.click();});expect(install).not.toHaveBeenCalled();
 await act(async()=>root.unmount());el.remove();
});
