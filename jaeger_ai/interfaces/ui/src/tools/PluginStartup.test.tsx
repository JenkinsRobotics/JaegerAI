import {act} from 'react';import {createRoot} from 'react-dom/client';import {expect,it,vi} from 'vitest';
import {PluginStartup} from './PluginStartup';import type {InstalledPlugin,PluginControls} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const row={id:'owned',name:'Owned plugin',startup_revision:7,startup_policy:'legacy',startup_editable:true,startup_approvable:true} as InstalledPlugin;
it('can disable the legacy default directly and only saves after explicit confirmation',async()=>{
 localStorage.clear();const startup=vi.fn(async(id:string,body:{operation_id:string})=>({ok:true,operation_id:body.operation_id,result:{id,scope:'future_discovery_only',startup_policy:'disabled',activation_performed:false}}));
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);const refresh=vi.fn();
 const click=async(label:string)=>act(async()=>[...element.querySelectorAll('button')].find(b=>b.textContent===label)!.click());
 try{await act(async()=>root.render(<PluginStartup row={row} controls={{startup,operation:vi.fn()} as unknown as PluginControls} refresh={refresh}/>));await click('Disable future startup');expect(startup).not.toHaveBeenCalled();await click('Confirm startup policy');expect(startup).toHaveBeenCalledWith('owned',expect.objectContaining({expected_revision:7,enabled:false}));expect(element.textContent).toContain('No code loaded or unloaded');expect(refresh).toHaveBeenCalledOnce();}finally{await act(async()=>root.unmount());element.remove();}
});
it('retains an uncertain command through remount and checks its receipt without re-enabling code',async()=>{
 localStorage.clear();const key='jaeger.ui.plugin-startup.v1.owned';localStorage.setItem(key,JSON.stringify({operation_id:'owned-unknown',expected_revision:7,enabled:true}));
 const startup=vi.fn(),operation=vi.fn().mockResolvedValueOnce({receipt:null}).mockResolvedValueOnce({receipt:{ok:true,operation_id:'owned-unknown',result:{id:'owned',scope:'future_discovery_only',startup_policy:'enabled_revision',activation_performed:false}}});
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
 try{await act(async()=>root.render(<PluginStartup row={{...row,startup_approvable:false}} controls={{startup,operation} as unknown as PluginControls} refresh={()=>{}}/>));await act(async()=>element.querySelector('button')!.click());expect(localStorage.getItem(key)).not.toBeNull();await act(async()=>element.querySelector('button')!.click());expect(startup).not.toHaveBeenCalled();expect(localStorage.getItem(key)).toBeNull();expect(element.textContent).not.toContain('Review exact revision for startup');}finally{await act(async()=>root.unmount());element.remove();}
});
