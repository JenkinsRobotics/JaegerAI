import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi} from 'vitest';
import {PluginCatalog} from './PluginCatalog';import type {PluginControls} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('catalog never activates code and unknown hook changes reconcile without replay',async()=>{
 const key='jaeger.ui.plugin-hooks.operation.v1.owned-plugin';localStorage.removeItem(key);
 const list=vi.fn(async()=>({plugins:[{id:'owned-plugin',name:'Owned plugin',package:'local-fixture',version:'1',state:'loaded',active_hooks:0,hook_count:1,tool_count:1,command_count:0,actions:['pause_hooks'],provenance:'metadata'}],scope:'current_process',activation_performed:false}));
 const mutate=vi.fn(async()=>{throw Error('Lost acknowledgment');});
 const operation=vi.fn(async(id:string)=>({receipt:{ok:true,operation_id:id,result:{id:'owned-plugin',state:'hooks_paused',scope:'managed_hook_dispatch_only'}}}));
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
 const button=(text:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent===text)!;
 try{
  await act(async()=>root.render(<PluginCatalog controls={{list,mutate,operation} as PluginControls}/>));expect(mutate).not.toHaveBeenCalled();
  await act(async()=>button('Pause lifecycle hooks').click());expect(mutate).not.toHaveBeenCalled();
  await act(async()=>button('Confirm hook change').click());expect(mutate).toHaveBeenCalledTimes(1);expect(localStorage.getItem(key)).not.toBeNull();
  await act(async()=>button('Check hook operation').click());expect(mutate).toHaveBeenCalledTimes(1);expect(operation).toHaveBeenCalledTimes(1);expect(localStorage.getItem(key)).toBeNull();
  expect(element.textContent).toContain('Other plugin capabilities unchanged');
 }finally{await act(async()=>root.unmount());element.remove();localStorage.removeItem(key);}
});
it('shows retained versus replaced package revisions without offering a stale resume',async()=>{
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);const mutate=vi.fn();
 const controls={list:async()=>({plugins:[{id:'owned-old',name:'Owned plugin',package:'local-fixture',version:'1',state:'hooks_paused',distribution_state:'replaced',active_hooks:0,hook_count:1,tool_count:1,command_count:0,actions:[],provenance:'metadata'},{id:'owned-new',name:'Owned plugin',package:'local-fixture',version:'2',state:'installed_not_loaded',distribution_state:'current',activation_blocked_by_loaded_revision:true,active_hooks:0,hook_count:0,tool_count:0,command_count:0,actions:[],provenance:'metadata'}],scope:'current_process',activation_performed:false}),mutate,operation:vi.fn()} as PluginControls;
 try{await act(async()=>root.render(<PluginCatalog controls={controls}/>));expect(element.textContent).toContain('Distribution replaced');expect(element.textContent).toContain('No hot replacement or activation was performed');expect(element.textContent).not.toContain('Resume lifecycle hooks');expect(mutate).not.toHaveBeenCalled();}finally{await act(async()=>root.unmount());element.remove();}
});
